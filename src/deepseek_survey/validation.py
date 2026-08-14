from __future__ import annotations

import re
import unicodedata
from typing import Any

from pydantic import ValidationError

from .config import ValidationConfig
from .models import Paper, ResearchResult, SurveySynthesis, ValidationReport
from .papers import PaperContent


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
    for section in synthesis.category_syntheses:
        if section.category not in allowed_categories:
            errors.append(f"unknown synthesis category: {section.category}")
        represented.update(section.paper_ids)

    unknown = represented - task_ids
    missing = task_ids - represented
    if unknown:
        errors.append(f"synthesis references unknown task IDs: {sorted(unknown)}")
    if missing:
        errors.append(f"synthesis omits task IDs from taxonomy: {sorted(missing)}")

    prose_sections = [
        synthesis.abstract,
        synthesis.scope_and_method,
        synthesis.conclusion,
        *synthesis.cross_paper_findings,
        *synthesis.technical_comparisons,
        *synthesis.research_gaps,
    ]
    for section in synthesis.category_syntheses:
        prose_sections.extend([section.overview, *section.trends])
        if not re.search(r"P\d{2}", section.overview):
            errors.append(f"category overview lacks a task-ID citation: {section.category}")
        for index, trend in enumerate(section.trends, start=1):
            if not re.search(r"P\d{2}", trend):
                errors.append(
                    f"category trend lacks a task-ID citation: {section.category}[{index}]"
                )
    for field_name, claims in (
        ("cross_paper_findings", synthesis.cross_paper_findings),
        ("technical_comparisons", synthesis.technical_comparisons),
        ("research_gaps", synthesis.research_gaps),
    ):
        for index, claim in enumerate(claims, start=1):
            if not re.search(r"P\d{2}", claim):
                errors.append(f"{field_name}[{index}] lacks a task-ID citation")
    cited = set(re.findall(r"P\d{2}", "\n".join(prose_sections)))
    if cited - task_ids:
        errors.append(f"synthesis contains invented citations: {sorted(cited - task_ids)}")
    # Every report must be represented in the taxonomy; prose citation coverage may be lower.
    if len(cited & task_ids) < max(1, int(len(task_ids) * 0.75)):
        errors.append("fewer than 75% of task IDs are cited in synthesis text")
    return synthesis, errors
