from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from deepseek_survey.models import Evidence, Paper, ResearchResult
from deepseek_survey.papers import PaperContent
from deepseek_survey.review import (
    finalize_codex_review,
    finalize_review,
    prepare_review,
    review_hashes,
    run_api_review,
)


def _write_json(path: Path, value: dict[str, str]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def test_finalize_codex_review_preserves_flash_cards_and_updates_status(
    tmp_path: Path,
) -> None:
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    _write_json(
        tmp_path / "run.json",
        {"status": "awaiting_codex_review", "pro_synthesis_status": "completed"},
    )
    _write_json(review_dir / "status.json", {"status": "awaiting_codex_review"})
    (tmp_path / "report_pro.md").write_text(
        "# Pro draft\n\n## 逐篇阅读卡片\n\n### P01\nFlash evidence.\n",
        encoding="utf-8",
    )
    (review_dir / "codex_main.md").write_text(
        "# Reviewed survey\n\nReviewed synthesis.\n", encoding="utf-8"
    )
    (review_dir / "codex_review.md").write_text(
        "# Review record\n\nApproved with revisions.\n", encoding="utf-8"
    )

    final_path = finalize_codex_review(tmp_path)

    final_text = final_path.read_text(encoding="utf-8")
    assert final_text.startswith("# Reviewed survey")
    assert "# Pro draft" not in final_text
    assert "## 逐篇阅读卡片" in final_text
    assert "Flash evidence." in final_text
    manifest = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    review_status = json.loads(
        (review_dir / "status.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "completed"
    assert manifest["final_report"] == str(final_path)
    assert review_status["status"] == "completed"


def test_finalize_codex_review_requires_pro_synthesis(tmp_path: Path) -> None:
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    _write_json(tmp_path / "run.json", {"pro_synthesis_status": "pending"})
    _write_json(review_dir / "status.json", {"status": "pending"})
    (tmp_path / "report_pro.md").write_text(
        "# Draft\n\n## 逐篇阅读卡片\n", encoding="utf-8"
    )
    (review_dir / "codex_main.md").write_text("body", encoding="utf-8")
    (review_dir / "codex_review.md").write_text("review", encoding="utf-8")

    with pytest.raises(ValueError, match="Pro 分类汇总尚未完成"):
        finalize_codex_review(tmp_path)


def _new_handoff(tmp_path: Path, count: int = 1, planned: int = 1):
    config = SimpleNamespace(
        project=SimpleNamespace(title="Survey", research_question="Question", target_papers=planned, language="zh-CN"),
        review=SimpleNamespace(name="Independent reviewer", mode="external", max_rounds=1),
        categories=("Systems",),
        routing=SimpleNamespace(reviewer="review-pro"),
        models={"review-pro": SimpleNamespace(model="provider-pro", provider="example", max_output_tokens=16000, thinking="disabled")},
        deepseek=SimpleNamespace(max_tokens_synthesis=16000),
    )
    papers = {}
    contents = {}
    results = []
    for number in range(1, count + 1):
        paper_id = f"paper-{number}"
        task_id = f"P{number:02d}"
        papers[paper_id] = Paper(paper_id=paper_id, title=f"Paper {number}", abstract="Abstract", url="https://example.test/paper")
        contents[paper_id] = PaperContent(paper_id=paper_id, source="pdf", text="[PAGE 1]\nBefore the claim. An exact evidence quote about measured performance. After the claim.", page_count=1)
        results.append(ResearchResult(
            task_id=task_id, paper_id=paper_id, title=f"Paper {number}", one_sentence_summary="Summary", research_question="Question",
            methodology="Method", experimental_setup="Setup", main_contributions=["Contribution"], key_findings=["Finding"],
            limitations=["Limitation"], relation_to_topic="Related", categories=["Systems"],
            evidence=[Evidence(claim="Claim", quote="An exact evidence quote about measured performance.", page=1)], confidence=0.8,
        ))
    bundle = prepare_review(tmp_path, config, results, papers, contents, failures=[{"task_id": f"P{number:02d}"} for number in range(count + 1, planned + 1)])
    return config, bundle, results, papers, contents


def _approve(tmp_path: Path, bundle: dict, *, main: str | None = None):
    ids = [card["task_id"] for card in bundle["source_cards"]]
    main = main or ("# Reviewed survey\n\n" + " ".join(f"Evidence [{task}]." for task in ids))
    (tmp_path / "review" / "main.md").write_text(main, encoding="utf-8")
    (tmp_path / "review" / "review.md").write_text("Reviewed the original evidence and the comparison conditions.", encoding="utf-8")
    decision = {
        "reviewer": "Different provider Pro", "decision": "approved", "unresolved_issues": [],
        "reviewed_task_ids": ids, "classification": [{"task_id": task, "category": "Systems"} for task in ids],
        "coverage_gaps": [], "reread_requests": [], **review_hashes(tmp_path),
    }
    _write_json(tmp_path / "review" / "decision.json", decision)
    return decision


def test_external_handoff_has_source_context_without_pro_draft(tmp_path: Path) -> None:
    _, bundle, *_ = _new_handoff(tmp_path)
    assert bundle["schema_version"] == 3
    assert bundle["review_status"] == "awaiting_review"
    assert "synthesis" not in bundle
    assert not (tmp_path / "report_draft.md").exists()
    context = bundle["source_cards"][0]["evidence_context"][0]
    assert context["matched"] is True
    assert context["located_page"] == 1
    assert "Before the claim." in context["context"]
    assert bundle["source_cards"][0]["source"]["text_sha256"]
    assert (tmp_path / "report_cards.md").is_file()
    assert (tmp_path / "review" / "decision.template.json").is_file()
    assert not (tmp_path / "review" / "decision.json").exists()


def test_generic_finalizer_accepts_external_reviewer_and_preserves_evidence(tmp_path: Path) -> None:
    _, bundle, *_ = _new_handoff(tmp_path)
    _approve(tmp_path, bundle)
    # A separate appendix edit must not enter the approved final report.
    (tmp_path / "report_cards.md").write_text("Unapproved appendix", encoding="utf-8")
    final = finalize_review(tmp_path)
    assert "An exact evidence quote" in final.read_text(encoding="utf-8")
    assert "Unapproved appendix" not in final.read_text(encoding="utf-8")
    manifest = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert manifest["reviewer"] == "Different provider Pro"
    assert manifest["status"] == "completed"


@pytest.mark.parametrize("change,match", [
    ({"decision": "needs_revision"}, "approved"),
    ({"decision": "insufficient_evidence"}, "approved"),
    ({"unresolved_issues": [{"severity": "critical", "issue": "Unsupported performance"}]}, "未解决"),
    ({"reviewed_task_ids": []}, "reviewed_task_ids"),
    ({"classification": []}, "classification"),
    ({"classification": [{"task_id": "P01", "category": "Unknown"}]}, "未知分类"),
    ({"reread_requests": [{"task_id": "P01", "question": "Confirm baseline"}]}, "补读"),
])
def test_new_review_rejects_unapproved_or_incomplete_decisions(tmp_path: Path, change: dict, match: str) -> None:
    _, bundle, *_ = _new_handoff(tmp_path)
    decision = _approve(tmp_path, bundle)
    decision.update(change)
    _write_json(tmp_path / "review" / "decision.json", decision)
    with pytest.raises(ValueError, match=match):
        finalize_review(tmp_path)
    assert not (tmp_path / "report_final.md").exists()


@pytest.mark.parametrize("path", ["review/main.md", "review_bundle.json"])
def test_review_approval_is_bound_to_current_body_and_evidence(tmp_path: Path, path: str) -> None:
    _, bundle, *_ = _new_handoff(tmp_path)
    _approve(tmp_path, bundle)
    with (tmp_path / path).open("a", encoding="utf-8") as stream:
        stream.write("\n ")
    with pytest.raises(ValueError, match="sha256"):
        finalize_review(tmp_path)


def test_new_review_requires_citations_in_body(tmp_path: Path) -> None:
    _, bundle, *_ = _new_handoff(tmp_path)
    _approve(tmp_path, bundle, main="# Review\nUncited prose.")
    with pytest.raises(ValueError, match="正文引用"):
        finalize_review(tmp_path)


def test_partial_28_of_32_run_can_be_approved_only_with_explicit_gaps(tmp_path: Path) -> None:
    _, bundle, *_ = _new_handoff(tmp_path, count=28, planned=32)
    decision = _approve(tmp_path, bundle)
    with pytest.raises(ValueError, match="覆盖缺口"):
        finalize_review(tmp_path)
    main_path = tmp_path / "review" / "main.md"
    with main_path.open("a", encoding="utf-8") as stream:
        stream.write("\n\n覆盖限制：28/32，P29–P32 阅读失败，不纳入综合。")
    decision["coverage_gaps"] = ["P29–P32 阅读失败，综合只覆盖有效的 28 篇。"]
    decision.update(review_hashes(tmp_path))
    _write_json(tmp_path / "review" / "decision.json", decision)
    assert finalize_review(tmp_path).is_file()


def test_legacy_alias_cannot_bypass_new_review_gate(tmp_path: Path) -> None:
    _, bundle, *_ = _new_handoff(tmp_path)
    decision = _approve(tmp_path, bundle)
    decision["decision"] = "needs_revision"
    _write_json(tmp_path / "review" / "decision.json", decision)
    with pytest.raises(ValueError, match="approved"):
        finalize_codex_review(tmp_path)


def test_missing_new_bundle_cannot_use_legacy_finalizer(tmp_path: Path) -> None:
    _new_handoff(tmp_path)
    (tmp_path / "review_bundle.json").unlink()
    with pytest.raises(FileNotFoundError, match="新版运行"):
        finalize_codex_review(tmp_path)


def test_prepare_invalidates_stale_approval(tmp_path: Path) -> None:
    config, bundle, results, papers, contents = _new_handoff(tmp_path)
    _approve(tmp_path, bundle)
    results[0].one_sentence_summary = "New evidence changes the summary."
    prepare_review(tmp_path, config, results, papers, contents)
    decision = json.loads((tmp_path / "review" / "decision.json").read_text(encoding="utf-8"))
    assert decision["decision"] == "needs_revision"
    assert (tmp_path / "review" / "decision.previous.json").is_file()


def test_reopening_unchanged_handoff_does_not_invalidate_approval(tmp_path: Path) -> None:
    config, bundle, results, papers, contents = _new_handoff(tmp_path)
    _approve(tmp_path, bundle)
    regenerated = prepare_review(tmp_path, config, results, papers, contents)
    assert regenerated == bundle
    assert finalize_review(tmp_path).is_file()


def test_revised_handoff_carries_previous_reread_feedback(tmp_path: Path) -> None:
    config, bundle, results, papers, contents = _new_handoff(tmp_path)
    decision = _approve(tmp_path, bundle)
    decision.update({"decision": "needs_revision", "unresolved_issues": ["Baseline unclear"], "reread_requests": [{"task_id": "P01", "question": "Verify baseline"}]})
    _write_json(tmp_path / "review" / "decision.json", decision)
    results[0].experimental_setup = "Baseline checked against supplementary table."
    regenerated = prepare_review(tmp_path, config, results, papers, contents)
    assert regenerated["previous_review"]["unresolved_issues"] == ["Baseline unclear"]
    assert regenerated["previous_review"]["reread_requests"] == decision["reread_requests"]
    assert regenerated["previous_review"]["round"] == 1


class _ReviewerClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def complete_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0), {"requested_model": kwargs["model"], "model": "provider-pro", "usage": {"total_tokens": 10}}


@pytest.mark.asyncio
async def test_api_review_uses_configured_upper_alias_and_repairs_invalid_approval(tmp_path: Path) -> None:
    config, bundle, *_ = _new_handoff(tmp_path)
    approved = {
        "reviewer": "Independent reviewer", "decision": "approved", "unresolved_issues": [],
        "reviewed_task_ids": ["P01"], "classification": [{"task_id": "P01", "category": "Systems"}],
        "coverage_gaps": [], "reread_requests": [], "main_markdown": "# Survey\nEvidence [P01].",
        "review_markdown": "Checked the quote context, experimental conditions and limitations.",
    }
    invalid = {**approved, "main_markdown": "Missing citations."}
    client = _ReviewerClient([invalid, approved])
    usage = []
    decision = await run_api_review(client=client, config=config, run_dir=tmp_path, bundle=bundle, usage=usage)
    assert len(client.calls) == 2
    assert all(call["model"] == "review-pro" for call in client.calls)
    assert "repair_errors" in client.calls[1]["user"]
    assert decision["decision"] == "approved"
    assert len(usage) == 2
    assert not (tmp_path / "report_final.md").exists()
    assert finalize_review(tmp_path).is_file()


@pytest.mark.asyncio
async def test_api_evidence_insufficiency_stays_unapproved_and_requests_reread(tmp_path: Path) -> None:
    config, bundle, *_ = _new_handoff(tmp_path)
    response = {
        "reviewer": "Independent reviewer", "decision": "insufficient_evidence", "unresolved_issues": ["Baseline unknown"],
        "reviewed_task_ids": ["P01"], "classification": [], "coverage_gaps": [],
        "reread_requests": [{"task_id": "P01", "question": "Find the baseline settings"}],
        "main_markdown": "Pending synthesis [P01].", "review_markdown": "Baseline evidence needs verification.",
    }
    client = _ReviewerClient([response])
    decision = await run_api_review(client=client, config=config, run_dir=tmp_path, bundle=bundle)
    assert len(client.calls) == 1
    assert decision["decision"] == "insufficient_evidence"
    assert decision["reread_requests"][0]["task_id"] == "P01"
    with pytest.raises(ValueError, match="approved"):
        finalize_review(tmp_path)
    # A later round retains every prior raw response for audit.
    second_client = _ReviewerClient([{**response, "review_markdown": "Further review still needs the baseline."}])
    await run_api_review(client=second_client, config=config, run_dir=tmp_path, bundle=bundle)
    first_record = json.loads((tmp_path / "review" / "api_response_1.json").read_text(encoding="utf-8"))
    second_record = json.loads((tmp_path / "review" / "api_response_2.json").read_text(encoding="utf-8"))
    assert first_record["review_markdown"] == response["review_markdown"]
    assert second_record["review_markdown"] != first_record["review_markdown"]
