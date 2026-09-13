from __future__ import annotations

import asyncio
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from deepseek_survey import pipeline
from deepseek_survey.artifacts import read_json, write_json, write_text
from deepseek_survey.config import (
    AppConfig,
    DeepSeekConfig,
    ExecutionConfig,
    ModelConfig,
    ProjectConfig,
    ProviderConfig,
    ReviewConfig,
    RoutingConfig,
    SearchConfig,
    ValidationConfig,
)
from deepseek_survey.models import Paper, ScreeningItem
from deepseek_survey.papers import PaperContent, truncate_paper
from deepseek_survey.prompts import READER_SYSTEM, SCREENING_SYSTEM
from deepseek_survey.review import finalize_review, review_hashes

CATEGORY = "Systems"
FIRST_QUOTE = "First exact quotation long enough for source validation."
SECOND_QUOTE = "Second exact quotation long enough for source validation."
SOURCE_TEXT = f"[PAGE 1]\n{FIRST_QUOTE}\n[PAGE 2]\n{SECOND_QUOTE}"


def _config(tmp_path: Path, *, resume_policy: str = "reuse") -> AppConfig:
    return AppConfig(
        project=ProjectConfig("Test survey", "Question?", "en", 32, tmp_path, 10_000),
        deepseek=DeepSeekConfig(
            base_url="https://provider.example.test/v1",
            screening_model="worker-flash-a",
            reader_model="worker-flash-a",
            synthesis_model="reviewer-pro",
            thinking="disabled",
            reader_concurrency=4,
            max_tokens_screening=1_000,
            max_tokens_reader=1_000,
            max_tokens_synthesis=2_000,
            request_timeout_seconds=10,
            max_retries=0,
        ),
        search=SearchConfig("https://search.example.test", 32, 4, 10, ("test",)),
        validation=ValidationConfig(2, 20, 0, 28),
        categories=(CATEGORY,),
        source_path=tmp_path / "config.toml",
        providers={
            "worker-provider": ProviderConfig(
                protocol="openai_compatible",
                base_url="https://provider.example.test/v1",
                api_key_env="TEST_WORKER_KEY",
                max_retries=0,
            ),
        },
        models={
            "flash-a": ModelConfig("worker-provider", "worker-flash-a", "flash"),
            "flash-b": ModelConfig("worker-provider", "worker-flash-b", "flash"),
            "upper": ModelConfig("worker-provider", "reviewer-pro", "pro"),
        },
        routing=RoutingConfig(screening="flash-a", reader="flash-a", reviewer="upper"),
        review=ReviewConfig(mode="external", name="External reviewer"),
        execution=ExecutionConfig(reader_concurrency=4, resume_policy=resume_policy),
    )


def _tasks(count: int = 32) -> list[tuple[str, Paper, ScreeningItem]]:
    return [
        (
            f"P{number:02d}",
            Paper(
                paper_id=f"paper-{number:02d}",
                title=f"Paper {number:02d}",
                abstract="A systems research paper.",
                url=f"https://papers.example.test/{number}",
            ),
            ScreeningItem(
                paper_id=f"paper-{number:02d}",
                relevance_score=90,
                rationale="Relevant supplied evidence.",
                reading_focus="Inspect source claims and experiment conditions.",
                category_hint=CATEGORY,
            ),
        )
        for number in range(1, count + 1)
    ]


def _contents(tasks: list[tuple[str, Paper, ScreeningItem]]) -> dict[str, PaperContent]:
    return {
        paper.paper_id: PaperContent(paper.paper_id, "pdf", SOURCE_TEXT, 2)
        for _, paper, _ in tasks
    }


class WorkerClient:
    """A local responder that rejects any unintended upper-model request."""

    def __init__(
        self,
        *,
        invalid_tasks: set[str] | None = None,
        primary_failure: str | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.invalid_tasks = invalid_tasks or set()
        self.primary_failure = primary_failure

    async def complete_json(self, **kwargs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        self.calls.append(kwargs)
        model = kwargs["model"]
        assert model in {"flash-a", "flash-b", "worker-flash-a", "worker-flash-b"}
        metadata = {
            "provider": "worker-provider",
            "model": {"flash-a": "worker-flash-a", "flash-b": "worker-flash-b"}.get(
                model, model
            ),
            "requested_model": model,
            "model_alias": model,
            "request_id": f"request-{len(self.calls)}",
            "usage": {"total_tokens": 10},
        }
        if kwargs["system"] == SCREENING_SYSTEM:
            return {
                "selection_notes": "Selected all supplied candidates.",
                "selected": [item.model_dump() for _, _, item in _tasks()],
            }, metadata

        assert kwargs["system"] == READER_SYSTEM
        match = re.search(r"Task ID: (P\d{2})", kwargs["user"])
        assert match is not None
        task_id = match.group(1)
        number = task_id[1:]
        is_primary = model in {"flash-a", "worker-flash-a"}
        if is_primary and self.primary_failure == "api":
            raise RuntimeError("Simulated provider outage")
        invalid = task_id in self.invalid_tasks or (
            is_primary and self.primary_failure == "evidence"
        )
        return {
            "task_id": task_id,
            "paper_id": f"paper-{number}",
            "title": f"Paper {number}",
            "one_sentence_summary": "A source-grounded summary.",
            "research_question": "Question.",
            "methodology": "Method.",
            "experimental_setup": "Reported experiment conditions.",
            "main_contributions": ["Contribution."],
            "key_findings": ["Finding."],
            "limitations": ["Limitation."],
            "relation_to_topic": "Systems research.",
            "categories": [CATEGORY],
            "evidence": [
                {
                    "claim": "First claim.",
                    "quote": "Invented quote absent from the source." if invalid else FIRST_QUOTE,
                    "page": 1,
                },
                {"claim": "Second claim.", "quote": SECOND_QUOTE, "page": 2},
            ],
            "confidence": 0.9,
            "unanswered_questions": ["Replication remains unverified."],
        }, metadata


def _install_local_sources(tmp_path: Path, monkeypatch) -> Path:
    tasks = _tasks()
    candidates_path = tmp_path / "input_candidates.json"
    write_json(candidates_path, [paper.model_dump() for _, paper, _ in tasks])

    async def fake_fetch(papers: list[Paper], **_kwargs: Any) -> dict[str, PaperContent]:
        contents = _contents(tasks)
        return {paper.paper_id: contents[paper.paper_id] for paper in papers}

    monkeypatch.setattr(pipeline, "fetch_all_papers", fake_fetch)
    return candidates_path


async def _run_external(tmp_path: Path, monkeypatch, client: WorkerClient) -> Path:
    candidates_path = _install_local_sources(tmp_path, monkeypatch)

    async def forbidden_synthesis(**_kwargs: Any) -> None:
        pytest.fail("External review mode must stop before upper-model synthesis")

    monkeypatch.setattr(pipeline, "_synthesize", forbidden_synthesis)
    return await pipeline.run_pipeline(
        _config(tmp_path),
        client,  # type: ignore[arg-type]
        candidates_path=candidates_path,
        progress=lambda _: None,
    )


@pytest.mark.asyncio
async def test_external_pipeline_stops_with_reviewable_sources_and_provenance(
    tmp_path, monkeypatch
) -> None:
    client = WorkerClient()
    run_dir = await _run_external(tmp_path, monkeypatch, client)

    manifest = read_json(run_dir / "run.json")
    bundle = read_json(Path(manifest["review_bundle"]))
    assert manifest["status"] == "awaiting_review"
    assert manifest["validated_results"] == 32
    assert len(client.calls) == 33
    assert not (run_dir / "report_final.md").exists()
    assert not (run_dir / "report_pro.md").exists()
    assert bundle["review_status"] == "awaiting_review"
    assert bundle["reviewer"] == "External reviewer"
    assert bundle["planned_total"] == bundle["completed_total"] == 32
    assert len(bundle["source_cards"]) == 32
    assert not bundle.get("synthesis")

    source = read_json(run_dir / "sources" / "P01.json")
    provenance = read_json(run_dir / "provenance" / "P01.json")
    source_manifest = read_json(run_dir / "sources" / "manifest.json")
    card = next(card for card in bundle["source_cards"] if card["task_id"] == "P01")
    assert source["text"] == SOURCE_TEXT
    assert source["full_text"] == SOURCE_TEXT
    assert source["source"] == "pdf"
    assert source["page_count"] == 2
    assert "P01" in source_manifest
    assert provenance["input_sha256"]
    assert provenance["result_sha256"]
    assert provenance["producer"]["provider"] == "worker-provider"
    assert provenance["producer"]["model"] == "worker-flash-a"
    assert card["provenance"] == provenance
    assert card["reading_card"]["evidence"][0]["quote"] == FIRST_QUOTE
    assert card["evidence_context"][0]["matched"] is True
    assert FIRST_QUOTE in card["evidence_context"][0]["context"]


@pytest.mark.asyncio
async def test_external_partial_run_keeps_failed_tasks_visible(tmp_path, monkeypatch) -> None:
    run_dir = await _run_external(tmp_path, monkeypatch, WorkerClient(invalid_tasks={"P32"}))
    manifest = read_json(run_dir / "run.json")
    bundle = read_json(Path(manifest["review_bundle"]))
    assert manifest["status"] == "awaiting_review"
    assert manifest["validated_results"] == 31
    assert manifest["failed_results"] == 1
    assert bundle["planned_total"] == 32
    assert bundle["completed_total"] == 31
    assert any("P32" in str(failure) for failure in bundle["failures"])
    assert "P32" not in {card["task_id"] for card in bundle["source_cards"]}
    assert (run_dir / "sources" / "P32.json").is_file()


@pytest.mark.asyncio
async def test_resuming_completed_external_run_preserves_approval(tmp_path, monkeypatch) -> None:
    run_dir = await _run_external(tmp_path, monkeypatch, WorkerClient())
    task_ids = [task_id for task_id, _, _ in _tasks()]
    write_text(run_dir / "review" / "main.md", "Reviewed survey " + " ".join(
        f"[{task_id}]" for task_id in task_ids
    ))
    write_text(run_dir / "review" / "review.md", "Source evidence and coverage verified.")
    write_json(run_dir / "review" / "decision.json", {
        "schema_version": 3,
        "reviewer": "External reviewer",
        "decision": "approved",
        "unresolved_issues": [],
        "reread_requests": [],
        "coverage_gaps": [],
        "reviewed_task_ids": task_ids,
        "classification": [{"task_id": task_id, "category": CATEGORY} for task_id in task_ids],
        **review_hashes(run_dir),
    })
    final_path = finalize_review(run_dir)
    original_report = final_path.read_bytes()
    original_decision = (run_dir / "review" / "decision.json").read_bytes()
    next_client = WorkerClient()

    resumed = await pipeline.run_pipeline(
        _config(tmp_path), next_client, resume_dir=run_dir, progress=lambda _: None,
    )

    assert resumed == run_dir
    assert next_client.calls == []
    assert read_json(run_dir / "run.json")["status"] == "completed"
    assert read_json(run_dir / "review" / "status.json")["status"] == "completed"
    assert final_path.read_bytes() == original_report
    assert (run_dir / "review" / "decision.json").read_bytes() == original_decision


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "decisions,max_rounds,expected_reviews,expected_rereads,expected_finalizations",
    [
        (["needs_revision", "approved"], 2, 2, 1, 1),
        (["insufficient_evidence"], 2, 1, 0, 0),
        (["needs_revision", "needs_revision"], 2, 2, 1, 0),
    ],
)
async def test_api_pipeline_uses_one_upper_role_and_bounds_flash_rereads(
    tmp_path,
    monkeypatch,
    decisions: list[str],
    max_rounds: int,
    expected_reviews: int,
    expected_rereads: int,
    expected_finalizations: int,
) -> None:
    candidates_path = _install_local_sources(tmp_path, monkeypatch)
    config = _config(tmp_path)
    config = replace(config, review=replace(config.review, mode="api", max_rounds=max_rounds))
    synthesis_models: list[str] = []
    review_models: list[str] = []
    finalized: list[Path] = []
    requested_question = "Verify the omitted replication setting against the original source."

    async def fake_synthesize(**kwargs: Any) -> None:
        synthesis_models.append(kwargs["config"].routing.reviewer)

    async def fake_review(**kwargs: Any) -> dict[str, Any]:
        review_models.append(kwargs["config"].routing.reviewer)
        decision = decisions[len(review_models) - 1]
        return {
            "decision": decision,
            "reread_requests": [
                {"task_id": "P01", "question": requested_question, "reason": "Missing context."}
            ] if decision == "needs_revision" else [],
        }

    def fake_finalize(run_dir: Path) -> Path:
        finalized.append(run_dir)
        return run_dir / "report_final.md"

    monkeypatch.setattr(pipeline, "_synthesize", fake_synthesize)
    monkeypatch.setattr(pipeline, "run_api_review", fake_review)
    monkeypatch.setattr(pipeline, "finalize_review", fake_finalize)
    client = WorkerClient()
    run_dir = await pipeline.run_pipeline(
        config,
        client,  # type: ignore[arg-type]
        candidates_path=candidates_path,
        progress=lambda _: None,
    )

    assert synthesis_models == review_models == ["upper"] * expected_reviews
    assert len(finalized) == expected_finalizations
    assert len(client.calls) == 33 + expected_rereads
    assert {call["model"] for call in client.calls} == {"flash-a"}
    if expected_rereads:
        assert "Task ID: P01" in client.calls[-1]["user"]
        assert requested_question in client.calls[-1]["user"]
        provenance = read_json(run_dir / "provenance" / "P01.json")
        assert provenance["producer"]["model"] == "worker-flash-a"


async def _read_batch(
    config: AppConfig,
    run_dir: Path,
    client: WorkerClient,
    *,
    text: str = SOURCE_TEXT,
) -> list[Any]:
    tasks = _tasks(1)
    contents = _contents(tasks)
    contents["paper-01"] = replace(contents["paper-01"], text=text)
    return await pipeline._run_readers(
        client=client,  # type: ignore[arg-type]
        config=config,
        run_dir=run_dir,
        task_specs=tasks,
        contents=contents,
        usage=[],
        progress=lambda _: None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("resume_policy,expected_calls", [("reuse", 0), ("strict", 1)])
async def test_changed_reader_model_respects_resume_policy(
    tmp_path, resume_policy: str, expected_calls: int
) -> None:
    config = _config(tmp_path, resume_policy=resume_policy)
    assert len(await _read_batch(config, tmp_path, WorkerClient())) == 1
    original_provenance = read_json(tmp_path / "provenance" / "P01.json")

    replacement = replace(config, routing=replace(config.routing, reader="flash-b"))
    next_client = WorkerClient()
    assert len(await _read_batch(replacement, tmp_path, next_client)) == 1
    assert len(next_client.calls) == expected_calls
    current_provenance = read_json(tmp_path / "provenance" / "P01.json")
    if resume_policy == "reuse":
        assert current_provenance == original_provenance
    else:
        assert current_provenance["producer"]["model"] == "worker-flash-b"


@pytest.mark.asyncio
async def test_changed_source_invalidates_reader_cache_even_when_quotes_still_match(tmp_path) -> None:
    config = _config(tmp_path)
    await _read_batch(config, tmp_path, WorkerClient())
    previous = read_json(tmp_path / "provenance" / "P01.json")
    next_client = WorkerClient()
    results = await _read_batch(
        config,
        tmp_path,
        next_client,
        text=SOURCE_TEXT + "\nA newly supplied paragraph changes the available context.",
    )
    assert len(results) == 1
    assert len(next_client.calls) == 1
    assert read_json(tmp_path / "provenance" / "P01.json")["input_sha256"] != previous[
        "input_sha256"
    ]


@pytest.mark.asyncio
async def test_focused_reread_restores_previously_omitted_source_context(tmp_path, monkeypatch) -> None:
    config = _config(tmp_path)
    config = replace(config, project=replace(config.project, max_paper_chars=100))
    tasks = _tasks(1)
    omitted_context = "Replication was conducted with five independent seeds."
    full_text = "[PAGE 1]\n" + "a " * 100 + omitted_context + " b" * 500
    fetched: list[str] = []

    async def fake_fetch(papers: list[Paper], **kwargs: Any) -> dict[str, PaperContent]:
        fetched.extend(paper.paper_id for paper in papers)
        return {
            paper.paper_id: PaperContent(
                paper.paper_id, "pdf", truncate_paper(full_text, kwargs["max_chars"]), 1,
                full_text=full_text,
            )
            for paper in papers
        }

    monkeypatch.setattr(pipeline, "fetch_all_papers", fake_fetch)
    initial = await pipeline._prepare_sources(config, tmp_path, tasks)
    assert omitted_context not in initial["paper-01"].text
    pipeline._set_reread_focus(tmp_path, tasks, [{
        "task_id": "P01", "question": "What replication settings were used?",
    }])
    focused = await pipeline._prepare_sources(config, tmp_path, tasks)
    assert fetched == ["paper-01"]
    assert focused["paper-01"].text == full_text
    assert omitted_context in focused["paper-01"].text


@pytest.mark.asyncio
async def test_changed_research_question_invalidates_reader_cache(tmp_path) -> None:
    config = _config(tmp_path)
    await _read_batch(config, tmp_path, WorkerClient())
    changed = replace(config, project=replace(config.project, research_question="New question?"))
    next_client = WorkerClient()
    assert len(await _read_batch(changed, tmp_path, next_client)) == 1
    assert len(next_client.calls) == 1


@pytest.mark.asyncio
async def test_strict_cache_tracks_actual_reader_output_limit(tmp_path) -> None:
    config = _config(tmp_path, resume_policy="strict")
    await _read_batch(config, tmp_path, WorkerClient())
    changed = replace(config, deepseek=replace(config.deepseek, max_tokens_reader=2_000))
    next_client = WorkerClient()
    assert len(await _read_batch(changed, tmp_path, next_client)) == 1
    assert len(next_client.calls) == 1
    assert next_client.calls[0]["max_tokens"] == 2_000


@pytest.mark.asyncio
async def test_changed_card_cannot_reuse_its_old_provenance(tmp_path) -> None:
    config = _config(tmp_path)
    await _read_batch(config, tmp_path, WorkerClient())
    result_path = tmp_path / "results" / "P01.json"
    changed = read_json(result_path)
    changed["key_findings"] = ["An unsupported finding inserted after validation."]
    write_json(result_path, changed)

    next_client = WorkerClient()
    results = await _read_batch(config, tmp_path, next_client)
    assert len(next_client.calls) == 1
    assert results[0].key_findings == ["Finding."]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["api", "evidence"])
async def test_reader_uses_flash_fallback_after_primary_failure(tmp_path, failure: str) -> None:
    config = _config(tmp_path)
    config = replace(config, routing=replace(config.routing, reader_fallback="flash-b"))
    client = WorkerClient(primary_failure=failure)
    assert len(await _read_batch(config, tmp_path, client)) == 1
    assert [call["model"] for call in client.calls] == ["flash-a", "flash-b"]
    provenance = read_json(tmp_path / "provenance" / "P01.json")
    assert provenance["producer"]["model"] == "worker-flash-b"


@pytest.mark.asyncio
async def test_gather_settled_waits_for_siblings_before_raising() -> None:
    sibling_started = asyncio.Event()
    release_sibling = asyncio.Event()
    failure_raised = asyncio.Event()
    sibling_finished = asyncio.Event()

    async def failed_request() -> None:
        await sibling_started.wait()
        failure_raised.set()
        raise RuntimeError("first failed request")

    async def pending_request() -> None:
        sibling_started.set()
        try:
            await release_sibling.wait()
        finally:
            sibling_finished.set()

    batch = asyncio.create_task(pipeline._gather_settled(failed_request(), pending_request()))
    try:
        await failure_raised.wait()
        done, _ = await asyncio.wait({batch}, timeout=0.02)
        assert not done, "A failed request must not abandon its still-running siblings"
        release_sibling.set()
        with pytest.raises(RuntimeError, match="first failed request"):
            await batch
        assert sibling_finished.is_set()
    finally:
        release_sibling.set()
        await asyncio.gather(batch, return_exceptions=True)


@pytest.mark.asyncio
async def test_gather_settled_cancellation_waits_for_sibling_cleanup() -> None:
    both_started = asyncio.Event()
    started = 0
    cleaned_up: set[int] = set()

    async def pending_request(number: int) -> None:
        nonlocal started
        started += 1
        if started == 2:
            both_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            # Model an asynchronous response-accounting or HTTP cleanup step.
            await asyncio.sleep(0)
            cleaned_up.add(number)

    batch = asyncio.create_task(pipeline._gather_settled(pending_request(1), pending_request(2)))
    await both_started.wait()
    batch.cancel()
    with pytest.raises(asyncio.CancelledError):
        await batch
    assert cleaned_up == {1, 2}
