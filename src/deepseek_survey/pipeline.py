from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .artifacts import new_run_directory, read_json, write_json, write_text
from .arxiv import rank_search_results, search_arxiv
from .config import AppConfig
from .models import (
    CategoryPlan,
    CategorySynthesis,
    Paper,
    PrimaryClassification,
    ResearchResult,
    ScreeningDecision,
    ScreeningItem,
    SurveyNarrative,
    SurveySynthesis,
    SynthesisPlan,
)
from .papers import PaperContent, fetch_all_papers, truncate_paper
from .prompts import (
    READER_SYSTEM,
    SCREENING_SYSTEM,
    SYNTHESIS_SYSTEM,
    category_plan_prompt,
    category_synthesis_prompt,
    primary_classification_prompt,
    reader_prompt,
    screening_prompt,
    survey_narrative_prompt,
)
from .provenance import (
    fingerprint,
    model_identity,
    reader_alias,
    reader_identity,
    reviewer_alias,
    screening_alias,
)
from .providers import BudgetExceededError, RoutedClient
from .review import finalize_review, prepare_review, run_api_review
from .rounds import RoundContext, filter_previously_selected, load_saved_round_context
from .validation import (
    validate_category_plan,
    validate_category_synthesis,
    validate_primary_classification,
    validate_research_result,
    validate_survey_narrative,
    validate_synthesis,
    validate_synthesis_plan,
)

Progress = Callable[[str], None]


async def _gather_settled(*coroutines: Any) -> list[Any]:
    """Settle every sibling before persisting budgets, including on interruption."""
    tasks = [asyncio.ensure_future(coroutine) for coroutine in coroutines]
    try:
        values = await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    for value in values:
        if isinstance(value, BaseException):
            raise value
    return values


def _screening_errors(
    raw: dict[str, Any],
    papers: list[Paper],
    target: int,
    categories: tuple[str, ...],
) -> tuple[ScreeningDecision | None, list[str]]:
    try:
        decision = ScreeningDecision.model_validate(raw)
    except ValidationError as exc:
        return None, [str(exc)]

    errors: list[str] = []
    candidate_ids = {paper.paper_id for paper in papers}
    selected_ids = [item.paper_id for item in decision.selected]
    if len(selected_ids) != target:
        errors.append(f"screening must select exactly {target} papers, got {len(selected_ids)}")
    if len(set(selected_ids)) != len(selected_ids):
        errors.append("screening contains duplicate paper IDs")
    unknown = set(selected_ids) - candidate_ids
    if unknown:
        errors.append(f"screening invented unknown paper IDs: {sorted(unknown)}")
    invalid_categories = sorted(
        {item.category_hint for item in decision.selected} - set(categories)
    )
    if invalid_categories:
        errors.append(f"screening used unknown categories: {invalid_categories}")
    deferred = [item.paper_id for item in decision.deferred_candidates]
    if (len(deferred) != len(set(deferred)) or set(deferred) - candidate_ids
            or set(deferred) & set(selected_ids) or len(deferred) > 8):
        errors.append("deferred candidates must be up to 8 unique unselected candidate IDs")
    return decision, errors


def _task_instruction(
    task_id: str,
    paper: Paper,
    screening: ScreeningItem,
    categories: tuple[str, ...],
) -> str:
    return f"""# {task_id} 论文阅读指令

- 论文：{paper.title}
- 论文 ID：{paper.paper_id}
- URL：{paper.url}
- 阅读焦点：{screening.reading_focus}
- 入选理由：{screening.rationale}
- 初始分类：{screening.category_hint}

任务要求：仅依据调度器提供的 PDF 提取文本（失败时为摘要），分析研究问题、系统设计、实验设置、
贡献、关键发现、局限及其与当前综述主题的关系。输出必须符合 `ResearchResult` JSON
Schema；分类只能取自以下集合：{', '.join(categories)}。至少提供两条可在输入原文中逐字匹配的
短证据，PDF 证据必须带正确页码。禁止用模型记忆补充输入中没有的事实。
"""


async def discover(config: AppConfig, destination: Path, progress: Progress = print) -> list[Paper]:
    progress(f"[discover] searching {len(config.search.queries)} arXiv queries")
    papers = await search_arxiv(config.search, progress=progress)
    write_json(destination, [paper.model_dump(mode="json") for paper in papers])
    progress(f"[discover] saved {len(papers)} unique candidates to {destination}")
    return papers


async def _screen_candidates(
    client: RoutedClient,
    config: AppConfig,
    papers: list[Paper],
    run_dir: Path,
    usage: list[dict[str, Any]],
    progress: Progress,
) -> ScreeningDecision:
    target = config.project.target_papers
    if len(papers) < target:
        raise RuntimeError(
            f"Only {len(papers)} unique candidates were found; at least {target} are required. "
            "Add search queries or provide a larger candidates JSON file."
        )
    pool_size = min(len(papers), max(96, target * 4))
    pool = rank_search_results(papers, config.search)[:pool_size]
    write_json(run_dir / "screening" / "candidate_pool.json", [p.model_dump() for p in pool])
    base_prompt = screening_prompt(
        pool,
        target=target,
        research_question=config.project.research_question,
        categories=config.categories,
    )
    errors: list[str] = []
    for attempt in range(2):
        prompt = base_prompt
        if errors:
            prompt += "\n\nPrevious output failed validation. Correct these errors:\n- " + "\n- ".join(
                errors
            )
        progress(
            f"[screen] requesting {screening_alias(config)} "
            f"(attempt {attempt + 1}/2); waiting for non-streaming response"
        )
        raw, metadata = await client.complete_json(
            system=SCREENING_SYSTEM,
            user=prompt,
            max_tokens=config.deepseek.max_tokens_screening,
            model=screening_alias(config),
        )
        metadata.update({"stage": "screening", "attempt": attempt + 1})
        usage.append(metadata)
        write_json(run_dir / "screening" / f"raw_attempt_{attempt + 1}.json", raw)
        decision, errors = _screening_errors(raw, pool, target, config.categories)
        if decision is not None and not errors:
            write_json(run_dir / "screening" / "selection.json", decision)
            progress(f"[screen] selected exactly {target} papers from {pool_size} candidates")
            return decision
        write_json(run_dir / "screening" / f"errors_attempt_{attempt + 1}.json", errors)
    raise RuntimeError(f"Screening failed validation twice: {errors}")


def _reader_input(
    config: AppConfig, task_id: str, paper: Paper,
    screening: ScreeningItem, content: PaperContent,
) -> str:
    return fingerprint({
        "system": READER_SYSTEM,
        "prompt": reader_prompt(
            task_id=task_id, paper=paper, screening=screening, content=content,
            research_question=config.project.research_question,
            language=config.project.language, categories=config.categories,
        ),
        "schema": ResearchResult.model_json_schema(),
        "validation": asdict(config.validation),
        "search": asdict(config.search),
    })


async def _read_one(
    *,
    client: RoutedClient,
    config: AppConfig,
    run_dir: Path,
    task_id: str,
    paper: Paper,
    screening: ScreeningItem,
    content: PaperContent,
    semaphore: asyncio.Semaphore,
    usage: list[dict[str, Any]],
) -> ResearchResult:
    errors: list[str] = []
    primary = reader_alias(config)
    routing = getattr(config, "routing", None)
    fallback = routing.reader_fallback if routing else None
    attempts = [primary] * (config.validation.max_repair_attempts + 1)
    if fallback and fallback != primary:
        attempts.append(fallback)
    input_sha256 = _reader_input(config, task_id, paper, screening, content)
    first_attempt = len(list((run_dir / "raw").glob(f"{task_id}_attempt_*.json")))
    async with semaphore:
        for attempt, model in enumerate(attempts, start=first_attempt + 1):
            prompt = reader_prompt(
                task_id=task_id,
                paper=paper,
                screening=screening,
                content=content,
                research_question=config.project.research_question,
                language=config.project.language,
                categories=config.categories,
                correction_errors=errors or None,
            )
            try:
                raw, metadata = await client.complete_json(
                    system=READER_SYSTEM,
                    user=prompt,
                    max_tokens=config.deepseek.max_tokens_reader,
                    model=model,
                )
            except BudgetExceededError:
                raise
            except Exception as exc:  # noqa: BLE001 -- isolate provider failures per reading task
                errors = [f"API request failed ({type(exc).__name__}): {exc}"]
                write_json(run_dir / "raw" / f"{task_id}_attempt_{attempt}.json",
                           {"error": errors[0], "model_alias": model})
                continue
            metadata.update({"stage": "reading", "task_id": task_id, "attempt": attempt,
                             "model_alias": model})
            usage.append(metadata)
            write_json(run_dir / "raw" / f"{task_id}_attempt_{attempt}.json", raw)
            result, validation = validate_research_result(
                raw,
                task_id=task_id,
                paper=paper,
                content=content,
                allowed_categories=config.categories,
                config=config.validation,
            )
            write_json(
                run_dir / "validation" / f"{task_id}_attempt_{attempt}.json",
                validation,
            )
            errors = validation.errors
            if result is not None and validation.valid:
                write_json(run_dir / "results" / f"{task_id}.json", result)
                write_json(run_dir / "provenance" / f"{task_id}.json", {
                    "schema_version": 1,
                    "created_at": datetime.now(UTC).isoformat(),
                    "input_sha256": input_sha256,
                    "result_sha256": fingerprint(result.model_dump(mode="json")),
                    "model_identity": reader_identity(config),
                    "producer": {**model_identity(config, model), **metadata},
                })
                return result
    raise RuntimeError(f"{task_id} failed evidence/schema validation: {errors}")


async def _run_readers(
    *,
    client: RoutedClient,
    config: AppConfig,
    run_dir: Path,
    task_specs: list[tuple[str, Paper, ScreeningItem]],
    contents: dict[str, PaperContent],
    usage: list[dict[str, Any]],
    progress: Progress,
) -> list[ResearchResult]:
    execution = getattr(config, "execution", None)
    concurrency = execution.reader_concurrency if execution else config.deepseek.reader_concurrency
    semaphore = asyncio.Semaphore(concurrency)
    results: list[ResearchResult] = []
    failures: list[str] = []
    finished = 0

    async def execute(spec: tuple[str, Paper, ScreeningItem]) -> ResearchResult:
        task_id, paper, screening = spec
        existing_path = run_dir / "results" / f"{task_id}.json"
        if existing_path.exists():
            existing_raw = read_json(existing_path)
            provenance_path = run_dir / "provenance" / f"{task_id}.json"
            provenance = read_json(provenance_path) if provenance_path.exists() else None
            strict = execution and execution.resume_policy == "strict"
            expected_input = _reader_input(
                config, task_id, paper, screening, contents[paper.paper_id]
            )
            cache_matches = bool(provenance and (
                provenance.get("input_sha256") == expected_input
                and provenance.get("result_sha256") == fingerprint(existing_raw)
                and (not strict or provenance.get("model_identity") == reader_identity(config))
            ))
            if provenance is None and not strict:
                cache_matches = True
            existing, report = validate_research_result(
                existing_raw,
                task_id=task_id,
                paper=paper,
                content=contents[paper.paper_id],
                allowed_categories=config.categories,
                config=config.validation,
            )
            if existing is not None and report.valid and cache_matches:
                if provenance is None:
                    write_json(provenance_path, {
                        "schema_version": 1,
                        "input_sha256": expected_input,
                        "result_sha256": fingerprint(existing_raw),
                        "model_identity": None,
                        "producer": {"origin": "legacy_unknown"},
                    })
                return existing
        return await _read_one(
            client=client,
            config=config,
            run_dir=run_dir,
            task_id=task_id,
            paper=paper,
            screening=screening,
            content=contents[paper.paper_id],
            semaphore=semaphore,
            usage=usage,
        )

    # All 32 coroutines are scheduled at once; the default semaphore permits all 32 API calls.
    pending = [asyncio.create_task(execute(spec), name=spec[0]) for spec in task_specs]
    try:
        for completed in asyncio.as_completed(pending):
            try:
                result = await completed
                results.append(result)
                finished += 1
                progress(
                    f"[read] {result.task_id} validated; {len(results)}/{len(task_specs)} passed, "
                    f"{finished}/{len(task_specs)} finished"
                )
            # Keep successful siblings so a resumed run can reuse their artifacts.
            except Exception as exc:  # noqa: BLE001
                failures.append(str(exc))
                finished += 1
                progress(
                    f"[read] task failed: {exc}; {len(results)}/{len(task_specs)} passed, "
                    f"{finished}/{len(task_specs)} finished"
                )
    finally:
        for task in pending:
            if not task.done():
                task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    write_json(run_dir / "failures.json", failures)
    return sorted(results, key=lambda item: item.task_id)


async def _synthesize(
    *,
    client: RoutedClient,
    config: AppConfig,
    run_dir: Path,
    results: list[ResearchResult],
    usage: list[dict[str, Any]],
    papers_by_id: dict[str, Paper] | None = None,
    progress: Progress | None = None,
) -> SurveySynthesis:
    report_progress = progress or (lambda _message: None)
    # Every synthesis cache belongs to exact cards, prompts and upper model settings.
    cache_key = fingerprint({
        "results": [r.model_dump(mode="json") for r in results],
        "papers": {key: paper.model_dump(mode="json")
                   for key, paper in (papers_by_id or {}).items()},
        "model": model_identity(config, reviewer_alias(config)),
        "max_tokens_synthesis": config.deepseek.max_tokens_synthesis,
        "synthesis_thinking": config.deepseek.synthesis_thinking,
        "question": config.project.research_question,
        "categories": config.categories,
        "language": config.project.language,
        "prompts": Path(__file__).with_name("prompts.py").read_text(encoding="utf-8"),
    })
    write_json(run_dir / "upper" / "current.json", {"input_sha256": cache_key})
    run_dir = run_dir / "upper" / cache_key
    task_ids = {result.task_id for result in results}
    final_path = run_dir / "synthesis" / "evolution_validated.json"
    if final_path.exists():
        saved, saved_errors = validate_synthesis(
            read_json(final_path),
            task_ids=task_ids,
            allowed_categories=config.categories,
        )
        if saved is not None and not saved_errors:
            report_progress("[synthesis] reusing validated upper-model synthesis")
            return saved

    plan_path = run_dir / "synthesis" / "plan_validated.json"
    plan: SynthesisPlan | None = None
    if plan_path.exists():
        plan, plan_errors = validate_synthesis_plan(
            read_json(plan_path),
            task_ids=task_ids,
            allowed_categories=config.categories,
        )
        if plan_errors:
            plan = None
    if plan is None:
        classification_path = (
            run_dir / "synthesis" / "primary_classification_validated.json"
        )
        classification: PrimaryClassification | None = None
        if classification_path.exists():
            classification, classification_errors = validate_primary_classification(
                read_json(classification_path),
                task_ids=task_ids,
                allowed_categories=config.categories,
            )
            if classification_errors:
                classification = None
        if classification is None:
            base_classification_prompt = primary_classification_prompt(
                research_question=config.project.research_question,
                categories=config.categories,
                results=results,
            )
            classification_errors: list[str] = []
            for attempt in range(2):
                prompt = base_classification_prompt
                if classification_errors:
                    prompt += (
                        "\n\nPrevious classification failed validation. Correct every error:\n- "
                        + "\n- ".join(classification_errors)
                    )
                report_progress(
                    f"[synthesis-classify] requesting {reviewer_alias(config)} "
                    f"(attempt {attempt + 1}/2)"
                )
                raw, metadata = await client.complete_json(
                    system=SYNTHESIS_SYSTEM,
                    user=prompt,
                    max_tokens=min(config.deepseek.max_tokens_synthesis, 5_000),
                    model=reviewer_alias(config),
                    thinking=config.deepseek.synthesis_thinking,
                )
                metadata.update(
                    {
                        "stage": "synthesis_primary_classification",
                        "schema_version": 2,
                        "attempt": attempt + 1,
                    }
                )
                usage.append(metadata)
                write_json(
                    run_dir
                    / "synthesis"
                    / f"primary_classification_raw_attempt_{attempt + 1}.json",
                    raw,
                )
                classification, classification_errors = (
                    validate_primary_classification(
                        raw,
                        task_ids=task_ids,
                        allowed_categories=config.categories,
                    )
                )
                write_json(
                    run_dir
                    / "synthesis"
                    / f"primary_classification_errors_attempt_{attempt + 1}.json",
                    classification_errors,
                )
                if classification is not None and not classification_errors:
                    write_json(classification_path, classification)
                    break
            else:
                raise RuntimeError(
                    "Primary classification failed validation twice: "
                    f"{classification_errors}"
                )
        else:
            report_progress("[synthesis-classify] reusing validated primary assignments")
        assert classification is not None

        assignments_by_category: dict[str, list[str]] = {
            category: [] for category in config.categories
        }
        for assignment in classification.assignments:
            assignments_by_category[assignment.category].append(assignment.task_id)
        active_assignments = [
            (category, assignments_by_category[category])
            for category in config.categories
            if assignments_by_category[category]
        ]
        plan_semaphore = asyncio.Semaphore(4)

        async def plan_category(
            index: int, category: str, assigned_ids: list[str]
        ) -> CategoryPlan:
            category_dir = run_dir / "synthesis" / "plans" / f"C{index:02d}"
            validated_path = category_dir / "validated.json"
            expected_ids = set(assigned_ids)
            saved_plan_candidates = [validated_path]
            saved_plan_candidates.extend(
                sorted(category_dir.glob("raw_attempt_*.json"), reverse=True)
            )
            for saved_path in saved_plan_candidates:
                if not saved_path.exists():
                    continue
                saved_category_plan, saved_errors = validate_category_plan(
                    read_json(saved_path),
                    category=category,
                    expected_task_ids=expected_ids,
                )
                if saved_category_plan is not None and not saved_errors:
                    write_json(validated_path, saved_category_plan)
                    report_progress(f"[synthesis-plan] reusing {category}")
                    return saved_category_plan
            base_prompt = category_plan_prompt(
                category=category,
                task_ids=assigned_ids,
                results=results,
                papers_by_id=papers_by_id,
            )
            errors: list[str] = []
            existing_attempts = len(list(category_dir.glob("raw_attempt_*.json")))
            async with plan_semaphore:
                for attempt in range(2):
                    artifact_attempt = existing_attempts + attempt + 1
                    prompt = base_prompt
                    if errors:
                        prompt += (
                            "\n\nPrevious category plan failed validation. "
                            "Correct every error:\n- "
                            + "\n- ".join(errors)
                        )
                    report_progress(
                        f"[synthesis-plan] {category} (attempt {attempt + 1}/2)"
                    )
                    raw, metadata = await client.complete_json(
                        system=SYNTHESIS_SYSTEM,
                        user=prompt,
                        max_tokens=min(config.deepseek.max_tokens_synthesis, 4_000),
                        model=reviewer_alias(config),
                        thinking=config.deepseek.synthesis_thinking,
                    )
                    metadata.update(
                        {
                            "stage": "synthesis_category_plan",
                            "schema_version": 2,
                            "category": category,
                            "attempt": attempt + 1,
                            "artifact_attempt": artifact_attempt,
                        }
                    )
                    usage.append(metadata)
                    write_json(category_dir / f"raw_attempt_{artifact_attempt}.json", raw)
                    category_plan, errors = validate_category_plan(
                        raw,
                        category=category,
                        expected_task_ids=expected_ids,
                    )
                    write_json(
                        category_dir / f"errors_attempt_{artifact_attempt}.json", errors
                    )
                    if category_plan is not None and not errors:
                        write_json(validated_path, category_plan)
                        return category_plan
            raise RuntimeError(f"Category planning failed twice for {category}: {errors}")

        category_plans = await _gather_settled(
            *[
                plan_category(index, category, assigned_ids)
                for index, (category, assigned_ids) in enumerate(
                    active_assignments, start=1
                )
            ]
        )
        assembled_plan = SynthesisPlan(categories=category_plans)
        plan, plan_errors = validate_synthesis_plan(
            assembled_plan.model_dump(mode="json"),
            task_ids=task_ids,
            allowed_categories=config.categories,
        )
        if plan is None or plan_errors:
            raise RuntimeError(f"Assembled synthesis plan failed validation: {plan_errors}")
        write_json(plan_path, plan)
    else:
        report_progress("[synthesis-plan] reusing validated classification/evolution plan")
    assert plan is not None

    category_semaphore = asyncio.Semaphore(4)

    async def synthesize_category(
        index: int, category_plan: CategoryPlan
    ) -> CategorySynthesis:
        category_dir = run_dir / "synthesis" / "categories" / f"C{index:02d}"
        validated_path = category_dir / "validated.json"
        if validated_path.exists():
            saved_category, saved_errors = validate_category_synthesis(
                read_json(validated_path),
                plan=category_plan,
                task_ids=task_ids,
            )
            if saved_category is not None and not saved_errors:
                report_progress(
                    f"[synthesis-category] reusing {category_plan.category}"
                )
                return saved_category

        base_prompt = category_synthesis_prompt(
            plan=category_plan,
            results=results,
            language=config.project.language,
        )
        errors: list[str] = []
        async with category_semaphore:
            for attempt in range(2):
                prompt = base_prompt
                if errors:
                    prompt += (
                        "\n\nPrevious category output failed validation. Correct every error:\n- "
                        + "\n- ".join(errors)
                    )
                report_progress(
                    f"[synthesis-category] {category_plan.category} "
                    f"(attempt {attempt + 1}/2)"
                )
                raw, metadata = await client.complete_json(
                    system=SYNTHESIS_SYSTEM,
                    user=prompt,
                    max_tokens=min(config.deepseek.max_tokens_synthesis, 6_000),
                    model=reviewer_alias(config),
                    thinking=config.deepseek.synthesis_thinking,
                )
                metadata.update(
                    {
                        "stage": "synthesis_category",
                        "schema_version": 2,
                        "category": category_plan.category,
                        "attempt": attempt + 1,
                    }
                )
                usage.append(metadata)
                write_json(category_dir / f"raw_attempt_{attempt + 1}.json", raw)
                section, errors = validate_category_synthesis(
                    raw,
                    plan=category_plan,
                    task_ids=task_ids,
                )
                write_json(category_dir / f"errors_attempt_{attempt + 1}.json", errors)
                if section is not None and not errors:
                    write_json(validated_path, section)
                    return section
        raise RuntimeError(
            f"Category synthesis failed twice for {category_plan.category}: {errors}"
        )

    category_syntheses = await _gather_settled(
        *[
            synthesize_category(index, category_plan)
            for index, category_plan in enumerate(plan.categories, start=1)
        ]
    )

    narrative_path = run_dir / "synthesis" / "narrative_validated.json"
    narrative: SurveyNarrative | None = None
    if narrative_path.exists():
        narrative, narrative_errors = validate_survey_narrative(
            read_json(narrative_path), task_ids=task_ids
        )
        if narrative_errors:
            narrative = None
    if narrative is None:
        base_narrative_prompt = survey_narrative_prompt(
            title=config.project.title,
            research_question=config.project.research_question,
            language=config.project.language,
            planned_total=config.project.target_papers,
            result_count=len(results),
            task_ids=sorted(task_ids),
            category_syntheses=category_syntheses,
        )
        narrative_errors: list[str] = []
        for attempt in range(2):
            prompt = base_narrative_prompt
            if narrative_errors:
                prompt += (
                    "\n\nPrevious narrative failed validation. Correct every error:\n- "
                    + "\n- ".join(narrative_errors)
                )
            report_progress(
                f"[synthesis-narrative] requesting {reviewer_alias(config)} "
                f"(attempt {attempt + 1}/2)"
            )
            raw, metadata = await client.complete_json(
                system=SYNTHESIS_SYSTEM,
                user=prompt,
                max_tokens=min(config.deepseek.max_tokens_synthesis, 8_000),
                model=reviewer_alias(config),
                thinking=config.deepseek.synthesis_thinking,
            )
            metadata.update(
                {
                    "stage": "synthesis_narrative",
                    "schema_version": 2,
                    "attempt": attempt + 1,
                }
            )
            usage.append(metadata)
            write_json(
                run_dir / "synthesis" / f"narrative_raw_attempt_{attempt + 1}.json",
                raw,
            )
            narrative, narrative_errors = validate_survey_narrative(
                raw, task_ids=task_ids
            )
            write_json(
                run_dir / "synthesis" / f"narrative_errors_attempt_{attempt + 1}.json",
                narrative_errors,
            )
            if narrative is not None and not narrative_errors:
                write_json(narrative_path, narrative)
                break
        else:
            raise RuntimeError(
                f"Survey narrative failed validation twice: {narrative_errors}"
            )
    else:
        report_progress("[synthesis-narrative] reusing validated global narrative")
    assert narrative is not None

    synthesis = SurveySynthesis(
        **narrative.model_dump(mode="python"),
        category_syntheses=category_syntheses,
    )
    validated, errors = validate_synthesis(
        synthesis.model_dump(mode="json"),
        task_ids=task_ids,
        allowed_categories=config.categories,
    )
    if validated is None or errors:
        raise RuntimeError(f"Assembled synthesis failed validation: {errors}")
    write_json(final_path, validated)
    return validated


async def _prepare_sources(
    config: AppConfig, run_dir: Path,
    task_specs: list[tuple[str, Paper, ScreeningItem]],
) -> dict[str, PaperContent]:
    contents: dict[str, PaperContent] = {}
    missing: list[Paper] = []
    manifest_path = run_dir / "sources" / "manifest.json"
    saved_manifest = read_json(manifest_path) if manifest_path.exists() else {}
    focus_path = run_dir / "review" / "reread_focus.json"
    focus = read_json(focus_path) if focus_path.exists() else {}
    for task_id, paper, _ in task_specs:
        path = run_dir / "sources" / f"{task_id}.json"
        entry = saved_manifest.get(task_id, {})
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == entry.get("sha256"):
            saved = read_json(path)
            if saved.get("paper_sha256") == fingerprint(paper.model_dump(mode="json")):
                full_text = saved.get("full_text") or saved["text"]
                text = (full_text if task_id in focus
                        else truncate_paper(full_text, config.project.max_paper_chars))
                contents[paper.paper_id] = PaperContent(
                    paper_id=paper.paper_id, source=saved["source"], text=text,
                    page_count=saved.get("page_count"), warning=saved.get("warning"),
                    full_text=full_text,
                )
                continue
        missing.append(paper)
    if missing:
        contents.update(await fetch_all_papers(
            missing, max_chars=config.project.max_paper_chars,
            concurrency=config.search.download_concurrency,
            timeout_seconds=config.search.request_timeout_seconds,
        ))
    manifest = {}
    for task_id, paper, _ in task_specs:
        content = contents[paper.paper_id]
        if task_id in focus and content.full_text:
            content = replace(content, text=content.full_text)
            contents[paper.paper_id] = content
        path = run_dir / "sources" / f"{task_id}.json"
        write_json(path, {
            **asdict(content), "full_text": content.full_text or content.text,
            "paper_sha256": fingerprint(paper.model_dump(mode="json")),
            "sampled": (content.full_text or content.text) != content.text,
        })
        manifest[task_id] = {
            "path": f"sources/{task_id}.json", "paper_id": paper.paper_id,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "source": content.source, "warning": content.warning,
        }
    write_json(manifest_path, manifest)
    return contents


def _set_reread_focus(
    run_dir: Path, task_specs: list[tuple[str, Paper, ScreeningItem]],
    requests: list[dict[str, Any]],
) -> None:
    focus_path = run_dir / "review" / "reread_focus.json"
    focus = read_json(focus_path) if focus_path.exists() else {}
    allowed = {task_id for task_id, _, _ in task_specs}
    for request in requests:
        if (not isinstance(request, dict) or request.get("task_id") not in allowed
                or not isinstance(request.get("question"), str)
                or not request["question"].strip()):
            raise ValueError("补读请求必须包含本轮有效 task_id 和非空 question")
        task_id = request["task_id"]
        original = next(item for task, _, item in task_specs if task == task_id)
        focus[task_id] = {
            "reading_focus": f"{original.reading_focus}\nUpper reviewer request: "
                             f"{request['question']}",
            "question": request["question"], "reason": request.get("reason", ""),
        }
    if requests:
        write_json(focus_path, focus)
    for index, (task_id, paper, item) in enumerate(task_specs):
        if task_id in focus:
            task_specs[index] = (task_id, paper, item.model_copy(update={
                "reading_focus": focus[task_id]["reading_focus"],
            }))


async def _reread_requested(
    client: Any, config: AppConfig, run_dir: Path,
    task_specs: list[tuple[str, Paper, ScreeningItem]], contents: dict[str, PaperContent],
    results: list[ResearchResult], requests: list[dict[str, Any]],
    usage: list[dict[str, Any]], progress: Progress,
) -> list[ResearchResult]:
    _set_reread_focus(run_dir, task_specs, requests)
    contents.update(await _prepare_sources(config, run_dir, task_specs))
    requested = {request["task_id"] for request in requests}
    result_map = {result.task_id: result for result in results}
    semaphore = asyncio.Semaphore(config.execution.reader_concurrency)
    for task_id, paper, item in task_specs:
        if task_id not in requested:
            continue
        progress(f"[reread] {task_id}: focused Flash reread using saved full text")
        result_map[task_id] = await _read_one(
            client=client, config=config, run_dir=run_dir, task_id=task_id,
            paper=paper, screening=item, content=contents[paper.paper_id],
            semaphore=semaphore, usage=usage,
        )
    failures_path = run_dir / "failures.json"
    if failures_path.exists():
        write_json(failures_path, [failure for failure in read_json(failures_path)
                                  if not any(str(failure).startswith(f"{task} ")
                                             for task in requested)])
    return sorted(result_map.values(), key=lambda result: result.task_id)


async def run_pipeline(
    config: AppConfig,
    client: RoutedClient,
    *,
    candidates_path: Path | None = None,
    resume_dir: Path | None = None,
    round_context: RoundContext | None = None,
    reread_requests: list[dict[str, Any]] | None = None,
    progress: Progress = print,
) -> Path:
    run_dir = resume_dir.resolve() if resume_dir else new_run_directory(config.project.output_dir)
    configuration = {
        "routing": asdict(config.routing), "review": asdict(config.review),
        "execution": asdict(config.execution),
        "models": {alias: model_identity(config, alias) for alias in config.models},
        "question": config.project.research_question, "language": config.project.language,
        "categories": config.categories, "max_paper_chars": config.project.max_paper_chars,
        "validation": asdict(config.validation),
        "limits": {"screening": config.deepseek.max_tokens_screening,
                   "reader": config.deepseek.max_tokens_reader,
                   "synthesis": config.deepseek.max_tokens_synthesis},
        "prompt_version": fingerprint(
            Path(__file__).with_name("prompts.py").read_text(encoding="utf-8")
        ),
    }
    previous_manifest: dict[str, Any] = {}
    if resume_dir and (run_dir / "run.json").exists():
        previous_manifest = read_json(run_dir / "run.json")
        previous_title = previous_manifest.get("title")
        if previous_title and previous_title != config.project.title:
            raise ValueError(
                "续跑目录的研究主题与当前 config.toml 不匹配；"
                "请恢复该轮原配置，或不带 --resume 启动新的研究系列。"
            )
        if (previous_manifest.get("status") == "completed" and not reread_requests
                and fingerprint(previous_manifest.get("configuration")) == fingerprint(configuration)):
            source_manifest_path = run_dir / "sources" / "manifest.json"
            source_manifest = read_json(source_manifest_path) if source_manifest_path.exists() else {}
            sources_unchanged = bool(source_manifest) and all(
                (run_dir / "sources" / f"{task_id}.json").is_file()
                and hashlib.sha256((run_dir / "sources" / f"{task_id}.json").read_bytes()).hexdigest()
                == entry.get("sha256")
                for task_id, entry in source_manifest.items()
            )
            if sources_unchanged:
                finalize_review(run_dir)
                progress("[resume] approved result and source snapshots remain valid; no API calls")
                return run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    if resume_dir:
        round_context = load_saved_round_context(run_dir)
    elif round_context is None:
        round_context = RoundContext.first()
    usage_path = run_dir / "api_usage.json"
    usage: list[dict[str, Any]] = (
        list(read_json(usage_path)) if resume_dir and usage_path.exists() else []
    )
    if resume_dir and hasattr(client, "restore_budget") and (run_dir / "budget.json").exists():
        client.restore_budget(read_json(run_dir / "budget.json"))
    manifest: dict[str, Any] = {
        "status": "running",
        "title": config.project.title,
        "round_number": round_context.round_number,
        "parent_run": str(round_context.parent_run) if round_context.parent_run else None,
        "previous_paper_count": len(round_context.previous_papers),
        "target_papers": config.project.target_papers,
        "schema_version": 3,
        "models": {
            "screening": screening_alias(config), "reading": reader_alias(config),
            "reviewer": config.routing.reviewer if config.review.mode == "api"
            else config.review.name,
        },
        "configuration": configuration,
        "configuration_history": [
            *previous_manifest.get("configuration_history", []),
            {"started_at": datetime.now(UTC).isoformat(), "configuration": configuration},
        ],
        "reader_concurrency": config.execution.reader_concurrency,
        "run_directory": str(run_dir),
    }
    write_json(run_dir / "run.json", manifest)
    write_json(run_dir / "round_context.json", round_context.as_dict())

    try:
        saved_candidates = run_dir / "candidates.json"
        saved_selection = run_dir / "screening" / "selection.json"
        if resume_dir and saved_candidates.exists():
            papers = [Paper.model_validate(item) for item in read_json(saved_candidates)]
            progress(f"[resume] loaded {len(papers)} candidates")
        elif candidates_path:
            papers = [Paper.model_validate(item) for item in read_json(candidates_path)]
            papers = rank_search_results(papers, config.search)
            write_json(saved_candidates, [paper.model_dump() for paper in papers])
            progress(f"[discover] loaded {len(papers)} candidates from {candidates_path}")
        else:
            papers = await discover(config, saved_candidates, progress)

        eligible_papers, excluded_candidates = filter_previously_selected(
            papers, round_context
        )
        write_json(
            run_dir / "excluded_candidates.json",
            [paper.model_dump(mode="json") for paper in excluded_candidates],
        )
        progress(
            f"[round] round {round_context.round_number}: excluded "
            f"{len(excluded_candidates)} previously selected candidates; "
            f"{len(eligible_papers)} remain eligible"
        )

        if resume_dir and saved_selection.exists():
            previous_config = previous_manifest.get("configuration", {})
            if previous_config.get("question", config.project.research_question) != (
                config.project.research_question
            ) or previous_config.get("categories", list(config.categories)) != list(config.categories):
                raise ValueError("研究问题或分类体系已改变，请新建一轮以重新筛选论文。")
            if config.execution.resume_policy == "strict" and previous_config:
                old_alias = previous_config.get("routing", {}).get("screening")
                old_model = previous_config.get("models", {}).get(old_alias)
                if old_model != model_identity(config, screening_alias(config)):
                    raise ValueError("严格续跑不能混用旧筛选模型；请新建运行以比较筛选结果。")
            decision = ScreeningDecision.model_validate(read_json(saved_selection))
            _, errors = _screening_errors(
                decision.model_dump(),
                eligible_papers,
                config.project.target_papers,
                config.categories,
            )
            if errors:
                raise RuntimeError(f"Saved screening selection is invalid: {errors}")
            progress("[resume] loaded validated screening selection")
        else:
            decision = await _screen_candidates(
                client, config, eligible_papers, run_dir, usage, progress
            )

        papers_by_id = {paper.paper_id: paper for paper in papers}
        task_specs: list[tuple[str, Paper, ScreeningItem]] = []
        task_manifest: list[dict[str, Any]] = []
        for number, selected in enumerate(decision.selected, start=1):
            task_id = f"P{number:02d}"
            paper = papers_by_id[selected.paper_id]
            task_specs.append((task_id, paper, selected))
            task_manifest.append(
                {
                    "task_id": task_id,
                    "paper_id": paper.paper_id,
                    "title": paper.title,
                    "reading_focus": selected.reading_focus,
                    "category_hint": selected.category_hint,
                }
            )
            write_text(
                run_dir / "tasks" / f"{task_id}.md",
                _task_instruction(task_id, paper, selected, config.categories),
            )
        write_json(run_dir / "tasks" / "manifest.json", task_manifest)
        _set_reread_focus(run_dir, task_specs, reread_requests or [])
        current_round_papers = [
            {
                "round_number": round_context.round_number,
                "source_run": str(run_dir),
                "task_id": task_id,
                "paper_id": paper.paper_id,
                "title": paper.title,
                "doi": paper.doi,
                "url": paper.url,
            }
            for task_id, paper, _ in task_specs
        ]
        corpus = [*round_context.previous_papers, *current_round_papers]
        write_json(
            run_dir / "corpus.json",
            {
                "round_number": round_context.round_number,
                "total_unique_papers": len(corpus),
                "papers": corpus,
            },
        )

        progress(f"[prepare] downloading/extracting the {len(task_specs)} selected papers")
        contents = await _prepare_sources(config, run_dir, task_specs)
        write_json(
            run_dir / "content_status.json",
            [
                {
                    "paper_id": content.paper_id,
                    "source": content.source,
                    "page_count": content.page_count,
                    "characters_supplied": len(content.text),
                    "warning": content.warning,
                }
                for content in contents.values()
            ],
        )

        progress(
            f"[read] scheduling {len(task_specs)} tasks on {reader_alias(config)} "
            f"with concurrency {config.execution.reader_concurrency}"
        )
        results = await _run_readers(
            client=client,
            config=config,
            run_dir=run_dir,
            task_specs=task_specs,
            contents=contents,
            usage=usage,
            progress=progress,
        )
        failures = read_json(run_dir / "failures.json")
        minimum_results = config.validation.minimum_results_for_synthesis
        if len(results) < minimum_results:
            raise RuntimeError(
                f"Only {len(results)}/{len(task_specs)} reading tasks passed validation; "
                f"at least {minimum_results} are required for partial synthesis. "
                "See failures.json."
            )
        if failures:
            progress(
                f"[read] proceeding with partial synthesis: {len(results)}/{len(task_specs)} "
                f"validated, {len(failures)} excluded"
            )

        reader_classification = {
            category: [result.task_id for result in results if category in result.categories]
            for category in config.categories
        }
        write_json(run_dir / "reader_classification.json", reader_classification)
        manifest["validated_results"] = len(results)
        manifest["failed_results"] = len(failures)
        manifest["failed_tasks"] = failures
        manifest["status"] = "awaiting_review"
        write_json(run_dir / "run.json", manifest)
        selected_ids = {item.paper_id for item in decision.selected}
        screening_record = {
            "decision": decision.model_dump(mode="json"),
            "unselected_candidates": [paper.model_dump(mode="json") for paper in eligible_papers
                                      if paper.paper_id not in selected_ids],
        }
        write_json(run_dir / "screening" / "triage.json", screening_record)
        for review_round in range(config.review.max_rounds):
            failures = read_json(run_dir / "failures.json")
            current_manifest = read_json(run_dir / "run.json")
            current_manifest.update({"validated_results": len(results),
                                     "failed_results": len(failures), "failed_tasks": failures})
            write_json(run_dir / "run.json", current_manifest)
            synthesis = None
            if config.review.mode == "api":
                progress(f"[upper] synthesis and review use {reviewer_alias(config)}")
                synthesis = await _synthesize(
                    client=client, config=config, run_dir=run_dir, results=results,
                    usage=usage, papers_by_id=papers_by_id, progress=progress,
                )
            provenance = {
                result.task_id: read_json(run_dir / "provenance" / f"{result.task_id}.json")
                for result in results
            }
            bundle = prepare_review(
                run_dir, config, results, papers_by_id, contents=contents,
                usage=usage, synthesis=synthesis, screening=screening_record,
                provenance=provenance, failures=failures,
            )
            if config.review.mode == "external":
                progress(f"[review] evidence package ready for {config.review.name}: "
                         f"{run_dir / 'review_bundle.json'}")
                break
            review_decision = await run_api_review(
                client=client, config=config, run_dir=run_dir, bundle=bundle,
                synthesis=synthesis, usage=usage,
            )
            if review_decision["decision"] == "approved":
                finalize_review(run_dir)
                progress("[review] final report approved and written")
                break
            requests = review_decision.get("reread_requests", [])
            if not requests or review_round + 1 >= config.review.max_rounds:
                progress("[review] further evidence or revisions needed; see review/decision.json")
                break
            results = await _reread_requested(
                client, config, run_dir, task_specs, contents, results, requests, usage, progress
            )
        return run_dir
    except asyncio.CancelledError:
        manifest = read_json(run_dir / "run.json")
        manifest["status"] = "interrupted"
        write_json(run_dir / "run.json", manifest)
        raise
    except Exception as exc:
        if (run_dir / "run.json").exists():
            manifest = read_json(run_dir / "run.json")
        manifest["status"] = "failed"
        manifest["error"] = str(exc)
        write_json(run_dir / "api_usage.json", usage)
        write_json(run_dir / "run.json", manifest)
        raise
    finally:
        write_json(run_dir / "api_usage.json", usage)
        if hasattr(client, "events"):
            events_path = run_dir / "api_attempts.json"
            previous_events = read_json(events_path) if events_path.exists() else []
            write_json(events_path, [*previous_events, *client.events])
            write_json(run_dir / "budget.json", client.budget_status)
