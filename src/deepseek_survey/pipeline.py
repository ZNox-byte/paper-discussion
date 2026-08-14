from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .artifacts import new_run_directory, read_json, write_json, write_text
from .arxiv import deterministic_rank, search_arxiv
from .config import AppConfig
from .deepseek import DeepSeekClient
from .models import (
    Paper,
    ResearchResult,
    ScreeningDecision,
    ScreeningItem,
    SurveySynthesis,
)
from .papers import PaperContent, fetch_all_papers
from .prompts import (
    READER_SYSTEM,
    SCREENING_SYSTEM,
    SYNTHESIS_SYSTEM,
    reader_prompt,
    screening_prompt,
    synthesis_prompt,
)
from .report import render_report
from .rounds import RoundContext, filter_previously_selected, load_saved_round_context
from .validation import validate_research_result, validate_synthesis

Progress = Callable[[str], None]


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
    client: DeepSeekClient,
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
    pool = sorted(papers, key=deterministic_rank)[:pool_size]
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
            f"[screen] requesting {config.deepseek.screening_model} "
            f"(attempt {attempt + 1}/2); waiting for non-streaming response"
        )
        raw, metadata = await client.complete_json(
            system=SCREENING_SYSTEM,
            user=prompt,
            max_tokens=config.deepseek.max_tokens_screening,
            model=config.deepseek.screening_model,
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
    raise RuntimeError(f"DeepSeek screening failed validation twice: {errors}")


async def _read_one(
    *,
    client: DeepSeekClient,
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
    async with semaphore:
        for attempt in range(config.validation.max_repair_attempts + 1):
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
                    model=config.deepseek.reader_model,
                )
            except Exception as exc:
                raise RuntimeError(f"{task_id} API request failed: {exc}") from exc
            metadata.update({"stage": "reading", "task_id": task_id, "attempt": attempt + 1})
            usage.append(metadata)
            write_json(run_dir / "raw" / f"{task_id}_attempt_{attempt + 1}.json", raw)
            result, validation = validate_research_result(
                raw,
                task_id=task_id,
                paper=paper,
                content=content,
                allowed_categories=config.categories,
                config=config.validation,
            )
            write_json(
                run_dir / "validation" / f"{task_id}_attempt_{attempt + 1}.json",
                validation,
            )
            errors = validation.errors
            if result is not None and validation.valid:
                write_json(run_dir / "results" / f"{task_id}.json", result)
                return result
    raise RuntimeError(f"{task_id} failed evidence/schema validation: {errors}")


async def _run_readers(
    *,
    client: DeepSeekClient,
    config: AppConfig,
    run_dir: Path,
    task_specs: list[tuple[str, Paper, ScreeningItem]],
    contents: dict[str, PaperContent],
    usage: list[dict[str, Any]],
    progress: Progress,
) -> list[ResearchResult]:
    semaphore = asyncio.Semaphore(config.deepseek.reader_concurrency)
    results: list[ResearchResult] = []
    failures: list[str] = []
    finished = 0

    async def execute(spec: tuple[str, Paper, ScreeningItem]) -> ResearchResult:
        task_id, paper, screening = spec
        existing_path = run_dir / "results" / f"{task_id}.json"
        if existing_path.exists():
            existing_raw = read_json(existing_path)
            existing, report = validate_research_result(
                existing_raw,
                task_id=task_id,
                paper=paper,
                content=contents[paper.paper_id],
                allowed_categories=config.categories,
                config=config.validation,
            )
            if existing is not None and report.valid:
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
    for completed in asyncio.as_completed(pending):
        try:
            result = await completed
            results.append(result)
            finished += 1
            progress(
                f"[read] {result.task_id} validated; {len(results)}/{len(task_specs)} passed, "
                f"{finished}/{len(task_specs)} finished"
            )
        # Keep collecting successful siblings so a resumed run can reuse their artifacts.
        except Exception as exc:  # noqa: BLE001
            failures.append(str(exc))
            finished += 1
            progress(
                f"[read] task failed: {exc}; {len(results)}/{len(task_specs)} passed, "
                f"{finished}/{len(task_specs)} finished"
            )

    write_json(run_dir / "failures.json", failures)
    return sorted(results, key=lambda item: item.task_id)


async def _synthesize(
    *,
    client: DeepSeekClient,
    config: AppConfig,
    run_dir: Path,
    results: list[ResearchResult],
    usage: list[dict[str, Any]],
) -> SurveySynthesis:
    prompt = synthesis_prompt(
        title=config.project.title,
        research_question=config.project.research_question,
        language=config.project.language,
        categories=config.categories,
        results=results,
        planned_total=config.project.target_papers,
    )
    errors: list[str] = []
    task_ids = {result.task_id for result in results}
    for attempt in range(2):
        attempt_prompt = prompt
        if errors:
            attempt_prompt += (
                "\n\nPrevious synthesis failed validation. Correct these errors:\n- "
                + "\n- ".join(errors)
            )
        raw, metadata = await client.complete_json(
            system=SYNTHESIS_SYSTEM,
            user=attempt_prompt,
            max_tokens=config.deepseek.max_tokens_synthesis,
            model=config.deepseek.synthesis_model,
        )
        metadata.update({"stage": "synthesis", "attempt": attempt + 1})
        usage.append(metadata)
        write_json(run_dir / "synthesis" / f"raw_attempt_{attempt + 1}.json", raw)
        synthesis, errors = validate_synthesis(
            raw, task_ids=task_ids, allowed_categories=config.categories
        )
        write_json(run_dir / "synthesis" / f"errors_attempt_{attempt + 1}.json", errors)
        if synthesis is not None and not errors:
            write_json(run_dir / "synthesis" / "validated.json", synthesis)
            return synthesis
    raise RuntimeError(f"Synthesis failed validation twice: {errors}")


async def run_pipeline(
    config: AppConfig,
    client: DeepSeekClient,
    *,
    candidates_path: Path | None = None,
    resume_dir: Path | None = None,
    round_context: RoundContext | None = None,
    progress: Progress = print,
) -> Path:
    run_dir = resume_dir.resolve() if resume_dir else new_run_directory(config.project.output_dir)
    if resume_dir and (run_dir / "run.json").exists():
        previous_manifest = read_json(run_dir / "run.json")
        previous_title = previous_manifest.get("title")
        if previous_title and previous_title != config.project.title:
            raise ValueError(
                "续跑目录的研究主题与当前 config.toml 不匹配；"
                "请恢复该轮原配置，或不带 --resume 启动新的研究系列。"
            )
    run_dir.mkdir(parents=True, exist_ok=True)
    if resume_dir:
        round_context = load_saved_round_context(run_dir)
    elif round_context is None:
        round_context = RoundContext.first()
    usage: list[dict[str, Any]] = []
    manifest: dict[str, Any] = {
        "status": "running",
        "title": config.project.title,
        "round_number": round_context.round_number,
        "parent_run": str(round_context.parent_run) if round_context.parent_run else None,
        "previous_paper_count": len(round_context.previous_papers),
        "target_papers": config.project.target_papers,
        "models": {
            "screening": config.deepseek.screening_model,
            "reading": config.deepseek.reader_model,
            "synthesis": config.deepseek.synthesis_model,
        },
        "reader_concurrency": config.deepseek.reader_concurrency,
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
            papers = sorted(papers, key=deterministic_rank)
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

        progress("[prepare] downloading/extracting the 32 selected papers")
        selected_papers = [spec[1] for spec in task_specs]
        contents = await fetch_all_papers(
            selected_papers,
            max_chars=config.project.max_paper_chars,
            concurrency=config.search.download_concurrency,
            timeout_seconds=config.search.request_timeout_seconds,
        )
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
            f"[read] scheduling {len(task_specs)} tasks on {config.deepseek.reader_model} "
            f"with concurrency {config.deepseek.reader_concurrency}"
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
        progress(
            f"[synthesis] requesting {config.deepseek.synthesis_model} for classification "
            "and cross-paper survey"
        )
        synthesis = await _synthesize(
            client=client,
            config=config,
            run_dir=run_dir,
            results=results,
            usage=usage,
        )
        final_classification = {
            section.category: section.paper_ids for section in synthesis.category_syntheses
        }
        write_json(run_dir / "classification.json", final_classification)
        report = render_report(
            synthesis,
            results,
            papers_by_id,
            round_number=round_context.round_number,
            cumulative_paper_count=len(corpus),
            planned_paper_count=len(task_specs),
            failed_task_count=len(failures),
        )
        write_text(run_dir / "report.md", report)
        write_json(run_dir / "api_usage.json", usage)
        manifest["status"] = "completed_with_gaps" if failures else "completed"
        manifest["validated_results"] = len(results)
        manifest["failed_results"] = len(failures)
        manifest["report"] = str(run_dir / "report.md")
        write_json(run_dir / "run.json", manifest)
        progress(f"[done] report written to {run_dir / 'report.md'}")
        return run_dir
    except Exception as exc:
        manifest["status"] = "failed"
        manifest["error"] = str(exc)
        write_json(run_dir / "api_usage.json", usage)
        write_json(run_dir / "run.json", manifest)
        raise
