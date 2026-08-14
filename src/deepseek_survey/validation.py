from __future__ import annotations

import re
import unicodedata
from typing import Any

from pydantic import ValidationError

from .config import ValidationConfig
from .models import (
    CategoryPlan,
    CategorySynthesis,
    Paper,
    PrimaryClassification,
    ResearchResult,
    SurveyNarrative,
    SurveySynthesis,
    SynthesisPlan,
    ValidationReport,
)
from .papers import PaperContent

TASK_ID_PATTERN = re.compile(r"\bP\d{2}\b")
BRACKET_PATTERN = re.compile(r"\[([^\[\]]+)\]")


def extract_task_citations(text: str) -> set[str]:
    """Return task IDs used as bracketed citations, ignoring prose such as p99 latency."""
    citations: set[str] = set()
    for bracketed in BRACKET_PATTERN.findall(text):
        citations.update(TASK_ID_PATTERN.findall(bracketed))
    return citations


def _normalize_category_task_id(value: str, allowed_task_ids: set[str]) -> str:
    """Repair harmless formatting drift such as `17` or `p17` when P17 is allowed."""
    match = re.fullmatch(r"[Pp]?(\d{1,2})", value.strip())
    if not match:
        return value
    candidate = f"P{int(match.group(1)):02d}"
    return candidate if candidate in allowed_task_ids else value


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).replace("\u00ad", "")
    value = re.sub(r"-\s*\n\s*", "", value)
    return re.sub(r"\s+", " ", value).strip().casefold()


def _quote_on_page(quote: str, page: int, text: str) -> bool:
    pattern = re.compile(
        rf"\[PAGE {page}\](.*?)(?=\n\[PAGE \d+\]|\Z)",
        flags=re.DOTALL,
    )
    match = pattern.search(text)
    return bool(match and normalize_text(quote) in normalize_text(match.group(1)))


def validate_research_result(
    raw: dict[str, Any],
    *,
    task_id: str,
    paper: Paper,
    content: PaperContent,
    allowed_categories: tuple[str, ...],
    config: ValidationConfig,
) -> tuple[ResearchResult | None, ValidationReport]:
    try:
        result = ResearchResult.model_validate(raw)
    except ValidationError as exc:
        return None, ValidationReport(valid=False, errors=[str(exc)])

    errors: list[str] = []
    if result.task_id != task_id:
        errors.append(f"task_id must be {task_id!r}, got {result.task_id!r}")
    if result.paper_id != paper.paper_id:
        errors.append(f"paper_id must be {paper.paper_id!r}, got {result.paper_id!r}")
    if normalize_text(result.title) != normalize_text(paper.title):
        errors.append("title does not exactly identify the assigned paper")

    unknown_categories = sorted(set(result.categories) - set(allowed_categories))
    if unknown_categories:
        errors.append(f"unknown categories: {unknown_categories}")

    normalized_source = normalize_text(content.text)
    total_evidence = len(result.evidence)
    grounded_evidence = []
    evidence_issues: list[str] = []
    for index, evidence in enumerate(result.evidence, start=1):
        normalized_quote = normalize_text(evidence.quote)
        if len(normalized_quote) < config.minimum_quote_chars:
            evidence_issues.append(f"evidence[{index}] quote is shorter than minimum")
            continue
        if normalized_quote not in normalized_source:
            evidence_issues.append(f"evidence[{index}] quote is not verbatim in supplied text")
            continue
        if content.source == "pdf" and evidence.page is None:
            evidence_issues.append(f"evidence[{index}] must include a page number for PDF content")
            continue
        if (
            evidence.page is not None
            and content.source == "pdf"
            and not _quote_on_page(evidence.quote, evidence.page, content.text)
        ):
            evidence_issues.append(
                f"evidence[{index}] quote is not on claimed page {evidence.page}"
            )
            continue
        grounded_evidence.append(evidence)

    required_evidence = config.minimum_grounded_evidence
    grounded = len(grounded_evidence)
    if grounded < required_evidence:
        errors.extend(evidence_issues)
        errors.append(
            f"only {grounded} grounded evidence items; at least {required_evidence} required"
        )
    elif not errors:
        # Invalid extras are removed so only evidence actually grounded in the supplied paper
        # reaches classification and synthesis.
        result.evidence = grounded_evidence

    return result, ValidationReport(
        valid=not errors,
        errors=errors,
        warnings=evidence_issues if grounded >= required_evidence else [],
        grounded_evidence_count=grounded,
        total_evidence_count=total_evidence,
        dropped_evidence_count=len(evidence_issues),
    )


def validate_primary_classification(
    raw: dict[str, Any],
    *,
    task_ids: set[str],
    allowed_categories: tuple[str, ...],
) -> tuple[PrimaryClassification | None, list[str]]:
    try:
        classification = PrimaryClassification.model_validate(raw)
    except ValidationError as exc:
        return None, [str(exc)]

    errors: list[str] = []
    counts: dict[str, int] = {}
    for assignment in classification.assignments:
        assignment.task_id = _normalize_category_task_id(assignment.task_id, task_ids)
        counts[assignment.task_id] = counts.get(assignment.task_id, 0) + 1
        if assignment.category not in allowed_categories:
            errors.append(
                f"{assignment.task_id} uses unknown primary category: {assignment.category}"
            )
        if assignment.task_id not in extract_task_citations(assignment.rationale):
            errors.append(f"{assignment.task_id} rationale must cite [{assignment.task_id}]")
    represented = set(counts)
    unknown = represented - task_ids
    missing = task_ids - represented
    duplicates = sorted(task_id for task_id, count in counts.items() if count > 1)
    if unknown:
        errors.append(f"classification references unknown task IDs: {sorted(unknown)}")
    if missing:
        errors.append(f"classification omits task IDs: {sorted(missing)}")
    if duplicates:
        errors.append(f"classification repeats task IDs: {duplicates}")
    return classification, errors


def validate_synthesis_plan(
    raw: dict[str, Any],
    *,
    task_ids: set[str],
    allowed_categories: tuple[str, ...],
) -> tuple[SynthesisPlan | None, list[str]]:
    try:
        plan = SynthesisPlan.model_validate(raw)
    except ValidationError as exc:
        return None, [str(exc)]

    errors: list[str] = []
    category_names: list[str] = []
    primary_counts: dict[str, int] = {}
    step_counts: dict[str, int] = {}
    for category in plan.categories:
        category_names.append(category.category)
        if category.category not in allowed_categories:
            errors.append(f"unknown plan category: {category.category}")
        category.paper_ids = list(
            dict.fromkeys(
                _normalize_category_task_id(task_id, task_ids)
                for task_id in category.paper_ids
            )
        )
        for task_id in category.paper_ids:
            primary_counts[task_id] = primary_counts.get(task_id, 0) + 1

        category_step_counts: dict[str, int] = {}
        for thread in category.evolution_threads:
            earlier_steps: set[str] = set()
            previous_task_id: str | None = None
            for step_index, step in enumerate(thread.ordered_steps, start=1):
                step.task_id = _normalize_category_task_id(step.task_id, task_ids)
                step.builds_on = list(
                    dict.fromkeys(
                        _normalize_category_task_id(task_id, task_ids)
                        for task_id in step.builds_on
                    )
                )
                step_counts[step.task_id] = step_counts.get(step.task_id, 0) + 1
                category_step_counts[step.task_id] = (
                    category_step_counts.get(step.task_id, 0) + 1
                )
                if step_index == 1:
                    # The first node is structurally the local foundation even when Pro used a
                    # looser label or referenced a paper in another thread.
                    step.relation_to_previous = "foundation"
                    step.builds_on = []
                else:
                    if step.relation_to_previous == "foundation":
                        step.relation_to_previous = "orthogonal"
                    step.builds_on = [
                        task_id for task_id in step.builds_on if task_id in earlier_steps
                    ]
                    if not step.builds_on and previous_task_id is not None:
                        # Preserve sequence without inventing causality: an independent item is
                        # related to the preceding item as orthogonal work, not direct improvement.
                        step.builds_on = [previous_task_id]
                        step.relation_to_previous = "orthogonal"
                rationale_citations = extract_task_citations(step.relationship_rationale)
                missing_citations = {step.task_id, *step.builds_on} - rationale_citations
                if missing_citations:
                    step.relationship_rationale = (
                        step.relationship_rationale.rstrip()
                        + " "
                        + " ".join(f"[{task_id}]" for task_id in sorted(missing_citations))
                    )
                earlier_steps.add(step.task_id)
                previous_task_id = step.task_id

        category_ids = set(category.paper_ids)
        planned_step_ids = set(category_step_counts)
        if planned_step_ids - category_ids:
            errors.append(
                f"plan category {category.category} threads contain non-primary IDs: "
                f"{sorted(planned_step_ids - category_ids)}"
            )
        if category_ids - planned_step_ids:
            errors.append(
                f"plan category {category.category} threads omit primary IDs: "
                f"{sorted(category_ids - planned_step_ids)}"
            )
        repeated = sorted(
            task_id for task_id, count in category_step_counts.items() if count > 1
        )
        if repeated:
            errors.append(f"plan category {category.category} repeats step IDs: {repeated}")

    duplicate_categories = sorted(
        name for name in set(category_names) if category_names.count(name) > 1
    )
    if duplicate_categories:
        errors.append(f"plan repeats categories: {duplicate_categories}")
    represented = set(primary_counts)
    unknown = represented - task_ids
    missing = task_ids - represented
    duplicates = sorted(
        task_id for task_id, count in primary_counts.items() if count > 1
    )
    repeated_steps = sorted(task_id for task_id, count in step_counts.items() if count > 1)
    if unknown:
        errors.append(f"plan references unknown task IDs: {sorted(unknown)}")
    if missing:
        errors.append(f"plan omits task IDs: {sorted(missing)}")
    if duplicates:
        errors.append(f"plan assigns task IDs to multiple categories: {duplicates}")
    if repeated_steps:
        errors.append(f"plan repeats task IDs across evolution threads: {repeated_steps}")
    return plan, errors


def validate_category_plan(
    raw: dict[str, Any],
    *,
    category: str,
    expected_task_ids: set[str],
) -> tuple[CategoryPlan | None, list[str]]:
    if "properties" in raw and raw.get("type") == "object":
        return None, ["model returned a JSON Schema instead of a CategoryPlan instance"]
    try:
        category_plan = CategoryPlan.model_validate(raw)
    except ValidationError as exc:
        return None, [str(exc)]
    plan, errors = validate_synthesis_plan(
        {"categories": [category_plan.model_dump(mode="json")]},
        task_ids=expected_task_ids,
        allowed_categories=(category,),
    )
    if plan is None:
        return None, errors
    validated_category = plan.categories[0]
    if validated_category.category != category:
        errors.append(
            f"category plan must be {category!r}, got {validated_category.category!r}"
        )
    if set(validated_category.paper_ids) != expected_task_ids:
        errors.append(
            f"category plan paper_ids must be {sorted(expected_task_ids)}, "
            f"got {sorted(validated_category.paper_ids)}"
        )
    return validated_category, errors


def validate_category_synthesis(
    raw: dict[str, Any],
    *,
    plan: CategoryPlan,
    task_ids: set[str],
) -> tuple[CategorySynthesis | None, list[str]]:
    try:
        section = CategorySynthesis.model_validate(raw)
    except ValidationError as exc:
        return None, [str(exc)]

    errors: list[str] = []
    if section.category != plan.category:
        errors.append(f"category must be {plan.category!r}, got {section.category!r}")
    section.paper_ids = list(
        dict.fromkeys(
            _normalize_category_task_id(task_id, task_ids) for task_id in section.paper_ids
        )
    )
    if set(section.paper_ids) != set(plan.paper_ids):
        errors.append(
            f"category paper_ids must exactly match plan: expected {sorted(plan.paper_ids)}, "
            f"got {sorted(section.paper_ids)}"
        )

    generated_threads = {thread.thread_name: thread for thread in section.evolution_threads}
    if len(generated_threads) != len(section.evolution_threads):
        errors.append("category contains duplicate evolution thread names")
    if set(generated_threads) != {thread.thread_name for thread in plan.evolution_threads}:
        errors.append("category evolution thread names do not match plan")

    prose: list[str] = [section.overview, *section.lateral_connections, *section.trends]
    if not extract_task_citations(section.overview):
        errors.append("category overview lacks a task-ID citation")
    for index, item in enumerate(section.lateral_connections, start=1):
        if not extract_task_citations(item):
            errors.append(f"lateral_connections[{index}] lacks a task-ID citation")
    for index, item in enumerate(section.trends, start=1):
        if not extract_task_citations(item):
            errors.append(f"trends[{index}] lacks a task-ID citation")

    for planned_thread in plan.evolution_threads:
        generated = generated_threads.get(planned_thread.thread_name)
        if generated is None:
            continue
        prose.append(generated.narrative)
        if not extract_task_citations(generated.narrative):
            errors.append(
                f"thread {planned_thread.thread_name!r} narrative lacks a task-ID citation"
            )
        expected_steps = planned_thread.ordered_steps
        if len(generated.ordered_steps) != len(expected_steps):
            errors.append(
                f"thread {planned_thread.thread_name!r} step count does not match plan"
            )
            continue
        for index, (step, planned_step) in enumerate(
            zip(generated.ordered_steps, expected_steps, strict=True), start=1
        ):
            step.task_id = _normalize_category_task_id(step.task_id, task_ids)
            step.builds_on = list(
                dict.fromkeys(
                    _normalize_category_task_id(task_id, task_ids)
                    for task_id in step.builds_on
                )
            )
            location = f"thread {planned_thread.thread_name!r} step[{index}]"
            if step.task_id != planned_step.task_id:
                errors.append(f"{location} task_id does not match plan")
            if step.relation_to_previous != planned_step.relation_to_previous:
                errors.append(f"{location} relation_to_previous does not match plan")
            if step.builds_on != planned_step.builds_on:
                errors.append(f"{location} builds_on does not match plan")
            evidence_citations = extract_task_citations(step.relationship_evidence)
            missing_citations = {step.task_id, *step.builds_on} - evidence_citations
            if missing_citations:
                errors.append(
                    f"{location} relationship_evidence omits citations: "
                    f"{sorted(missing_citations)}"
                )
            prose.extend(
                [
                    step.predecessor_problem,
                    step.contribution_or_improvement,
                    step.tradeoffs,
                    step.remaining_gap,
                    step.relationship_evidence,
                ]
            )

    invented = extract_task_citations("\n".join(prose)) - task_ids
    if invented:
        errors.append(f"category contains invented citations: {sorted(invented)}")
    return section, errors


def validate_survey_narrative(
    raw: dict[str, Any], *, task_ids: set[str]
) -> tuple[SurveyNarrative | None, list[str]]:
    try:
        narrative = SurveyNarrative.model_validate(raw)
    except ValidationError as exc:
        return None, [str(exc)]

    errors: list[str] = []
    for field_name, claims in (
        ("cross_paper_findings", narrative.cross_paper_findings),
        ("technical_comparisons", narrative.technical_comparisons),
        ("research_gaps", narrative.research_gaps),
    ):
        for index, claim in enumerate(claims, start=1):
            if not extract_task_citations(claim):
                errors.append(f"{field_name}[{index}] lacks a task-ID citation")
    prose = [
        narrative.abstract,
        narrative.scope_and_method,
        narrative.conclusion,
        *narrative.cross_paper_findings,
        *narrative.technical_comparisons,
        *narrative.research_gaps,
    ]
    invented = extract_task_citations("\n".join(prose)) - task_ids
    if invented:
        errors.append(f"narrative contains invented citations: {sorted(invented)}")
    return narrative, errors


def validate_synthesis(
    raw: dict[str, Any],
    *,
    task_ids: set[str],
    allowed_categories: tuple[str, ...],
) -> tuple[SurveySynthesis | None, list[str]]:
    try:
        synthesis = SurveySynthesis.model_validate(raw)
    except ValidationError as exc:
        return None, [str(exc)]

    errors: list[str] = []
    represented: set[str] = set()
    primary_counts: dict[str, int] = {}
    for section in synthesis.category_syntheses:
        if section.category not in allowed_categories:
            errors.append(f"unknown synthesis category: {section.category}")
        section.paper_ids = list(
            dict.fromkeys(
                _normalize_category_task_id(task_id, task_ids)
                for task_id in section.paper_ids
            )
        )
        represented.update(section.paper_ids)
        for task_id in section.paper_ids:
            primary_counts[task_id] = primary_counts.get(task_id, 0) + 1

        thread_step_counts: dict[str, int] = {}
        for thread_index, thread in enumerate(section.evolution_threads, start=1):
            earlier_steps: set[str] = set()
            for step_index, step in enumerate(thread.ordered_steps, start=1):
                step.task_id = _normalize_category_task_id(step.task_id, task_ids)
                step.builds_on = list(
                    dict.fromkeys(
                        _normalize_category_task_id(task_id, task_ids)
                        for task_id in step.builds_on
                    )
                )
                thread_step_counts[step.task_id] = (
                    thread_step_counts.get(step.task_id, 0) + 1
                )
                location = f"{section.category}.thread[{thread_index}].step[{step_index}]"
                if step_index == 1:
                    if step.relation_to_previous != "foundation":
                        errors.append(f"{location} must start with relation foundation")
                    if step.builds_on:
                        errors.append(f"{location} foundation must not build on another step")
                else:
                    if step.relation_to_previous == "foundation":
                        errors.append(f"{location} may not be foundation after the first step")
                    if not step.builds_on:
                        errors.append(f"{location} must name at least one earlier builds_on ID")
                    invalid_predecessors = set(step.builds_on) - earlier_steps
                    if invalid_predecessors:
                        errors.append(
                            f"{location} builds_on IDs must appear earlier in the same thread: "
                            f"{sorted(invalid_predecessors)}"
                        )
                evidence_citations = extract_task_citations(step.relationship_evidence)
                required_citations = {step.task_id, *step.builds_on}
                missing_evidence_ids = required_citations - evidence_citations
                if missing_evidence_ids:
                    errors.append(
                        f"{location} relationship_evidence omits citations: "
                        f"{sorted(missing_evidence_ids)}"
                    )
                earlier_steps.add(step.task_id)

        section_ids = set(section.paper_ids)
        thread_ids = set(thread_step_counts)
        unknown_thread_ids = thread_ids - section_ids
        missing_thread_ids = section_ids - thread_ids
        repeated_thread_ids = sorted(
            task_id for task_id, count in thread_step_counts.items() if count > 1
        )
        if unknown_thread_ids:
            errors.append(
                f"{section.category} evolution threads contain non-primary IDs: "
                f"{sorted(unknown_thread_ids)}"
            )
        if missing_thread_ids:
            errors.append(
                f"{section.category} evolution threads omit primary IDs: "
                f"{sorted(missing_thread_ids)}"
            )
        if repeated_thread_ids:
            errors.append(
                f"{section.category} evolution threads repeat primary IDs: "
                f"{repeated_thread_ids}"
            )

    unknown = represented - task_ids
    missing = task_ids - represented
    if unknown:
        errors.append(f"synthesis references unknown task IDs: {sorted(unknown)}")
    if missing:
        errors.append(f"synthesis omits task IDs from taxonomy: {sorted(missing)}")
    duplicate_primary_ids = sorted(
        task_id for task_id, count in primary_counts.items() if count > 1
    )
    if duplicate_primary_ids:
        errors.append(
            "task IDs must have exactly one primary synthesis category; duplicates: "
            f"{duplicate_primary_ids}"
        )

    prose_sections = [
        synthesis.abstract,
        synthesis.scope_and_method,
        synthesis.conclusion,
        *synthesis.cross_paper_findings,
        *synthesis.technical_comparisons,
        *synthesis.research_gaps,
    ]
    for section in synthesis.category_syntheses:
        prose_sections.extend(
            [section.overview, *section.lateral_connections, *section.trends]
        )
        if not extract_task_citations(section.overview):
            errors.append(f"category overview lacks a task-ID citation: {section.category}")
        for thread_index, thread in enumerate(section.evolution_threads, start=1):
            prose_sections.append(thread.narrative)
            if not extract_task_citations(thread.narrative):
                errors.append(
                    f"evolution thread narrative lacks a task-ID citation: "
                    f"{section.category}[{thread_index}]"
                )
            for step in thread.ordered_steps:
                prose_sections.extend(
                    [
                        step.predecessor_problem,
                        step.contribution_or_improvement,
                        step.tradeoffs,
                        step.remaining_gap,
                        step.relationship_evidence,
                    ]
                )
        for index, connection in enumerate(section.lateral_connections, start=1):
            if not extract_task_citations(connection):
                errors.append(
                    f"lateral connection lacks a task-ID citation: "
                    f"{section.category}[{index}]"
                )
        for index, trend in enumerate(section.trends, start=1):
            if not extract_task_citations(trend):
                errors.append(
                    f"category trend lacks a task-ID citation: {section.category}[{index}]"
                )
    for field_name, claims in (
        ("cross_paper_findings", synthesis.cross_paper_findings),
        ("technical_comparisons", synthesis.technical_comparisons),
        ("research_gaps", synthesis.research_gaps),
    ):
        for index, claim in enumerate(claims, start=1):
            if not extract_task_citations(claim):
                errors.append(f"{field_name}[{index}] lacks a task-ID citation")
    cited = extract_task_citations("\n".join(prose_sections))
    if cited - task_ids:
        errors.append(f"synthesis contains invented citations: {sorted(cited - task_ids)}")
    # Every report must be represented in the taxonomy; prose citation coverage may be lower.
    if len(cited & task_ids) < max(1, int(len(task_ids) * 0.75)):
        errors.append("fewer than 75% of task IDs are cited in synthesis text")
    return synthesis, errors
