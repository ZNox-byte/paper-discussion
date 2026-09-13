from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest

from deepseek_survey.review import review_hashes
from deepseek_survey.web import ASSETS, ResearchLibrary, make_handler


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def snapshot(root: Path) -> dict:
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


@pytest.fixture
def library(tmp_path: Path):
    run = tmp_path / "20260101T000000Z"
    write_json(run / "run.json", {"schema_version": 3, "status": "completed", "title": "Systems"})
    result = {"task_id": "P01", "paper_id": "paper-1", "title": "Bound title",
              "one_sentence_summary": "Bound summary", "categories": ["Systems"],
              "evidence": [{"claim": "Bound claim", "quote": "Exact quotation", "page": 1}]}
    source = {"paper_id": "paper-1", "source": "pdf", "full_text": "Exact quotation"}
    write_json(run / "sources" / "P01.json", source)
    source_entry = {"paper_id": "paper-1", "sha256": hashlib.sha256(
        (run / "sources" / "P01.json").read_bytes()).hexdigest()}
    write_json(run / "sources" / "manifest.json", {"P01": source_entry})
    bundle = {"schema_version": 3, "planned_total": 1, "categories": ["Systems"],
              "source_cards": [{"task_id": "P01", "reading_card": result,
                                "paper": {"paper_id": "paper-1", "title": "Bound title"},
                                "source": {"source": "pdf", "manifest": source_entry,
                                           "text_sha256": hashlib.sha256(b"Exact quotation").hexdigest()},
                                "evidence_context": [{**result["evidence"][0], "context": "Bound context"}]}]}
    write_json(run / "review_bundle.json", bundle)
    write_json(run / "tasks" / "manifest.json", [{"task_id": "P01", "paper_id": "paper-1"}])
    write_json(run / "results" / "P01.json", result)
    (run / "review").mkdir()
    (run / "review" / "main.md").write_text("# Approved\n\nEvidence [P01].", encoding="utf-8")
    (run / "review" / "review.md").write_text("Checked source evidence.", encoding="utf-8")
    decision = {"reviewer": "Test Pro", "decision": "approved", "reviewed_task_ids": ["P01"],
                "classification": [{"task_id": "P01", "category": "Systems"}],
                "unresolved_issues": [], "coverage_gaps": [], "reread_requests": [],
                **review_hashes(run)}
    write_json(run / "review" / "decision.json", decision)
    return ResearchLibrary(tmp_path), run


def test_real_legacy_shapes_and_unscreened_candidates(tmp_path: Path):
    completed = tmp_path / "20260101T000000Z"
    write_json(completed / "run.json", {"title": "Research", "status": "completed"})
    write_json(completed / "tasks" / "manifest.json", [{"task_id": "P01", "paper_id": "old-paper"}])
    write_json(completed / "results" / "P01.json", {"paper_id": "old-paper", "data_and_training": "Old setup"})
    write_json(completed / "content_status.json", [{"paper_id": "old-paper", "source": "pdf"}])
    write_json(completed / "classification.json", {"Historical": ["P01"]})
    (completed / "report_final.md").write_text("# Legacy\nText\n## 逐篇阅读卡片\nAppendix", encoding="utf-8")
    discovered = tmp_path / "20260102T000000Z"
    write_json(discovered / "candidates.json", [{"paper_id": "new-paper", "title": "Candidate"}])
    lib = ResearchLibrary(tmp_path)
    assert lib.index()["default_run"] == completed.name
    detail = lib.detail(completed.name)
    assert detail["review_state"] == "legacy_completed"
    assert "Appendix" not in detail["reports"]["final"]["text"]
    paper = detail["papers"][0]
    assert paper["result"]["experimental_setup"] == "Old setup"
    assert paper["category"] == "Historical"
    assert not paper["has_source"]
    assert not detail["usage_complete"]
    candidate = lib.detail(discovered.name)
    assert candidate["candidates"][0]["disposition"] == "unscreened"
    assert candidate["round"] is None and candidate["reports"] == {}
    assert not candidate["has_bundle"]


def test_approved_display_and_download_use_bound_artifacts_without_writes(library):
    lib, run = library
    write_json(run / "results" / "P01.json", {"title": "Changed result"})
    write_json(run / "candidates.json", [{"paper_id": "paper-1", "title": "Changed metadata"}])
    (run / "report_final.md").write_text("Changed exported report", encoding="utf-8")
    before = snapshot(run)
    detail = lib.detail(run.name)
    assert detail["review_state"] == "approved"
    assert detail["papers"][0]["title"] == "Bound title"
    assert detail["papers"][0]["evidence_context"][0]["context"] == "Bound context"
    content, filename = lib.download(run.name, "final")
    assert content.decode() == detail["reports"]["final"]["text"]
    assert filename.endswith("approved-main.md")
    assert lib.source(run.name, "P01")["text"] == "Exact quotation"
    assert snapshot(run) == before


def test_changed_main_invalidates_approval(library):
    lib, run = library
    (run / "review" / "main.md").write_text("Changed [P01]", encoding="utf-8")
    detail = lib.detail(run.name)
    assert detail["review_state"] == "stale"
    assert detail["approval_error"]
    assert detail["reports"]["review_main"]["label"] == "待审正文"


def test_missing_root_bundle_and_missing_hash_cannot_approve(library):
    lib, run = library
    (run / "review_bundle.json").rename(run / "review" / "review_bundle.json")
    decision_path = run / "review" / "decision.json"
    decision = json.loads(decision_path.read_text())
    decision.pop("bundle_sha256")
    write_json(decision_path, decision)
    assert lib.detail(run.name)["review_state"] == "stale"


def test_reread_does_not_attach_old_evidence_context(library):
    lib, run = library
    write_json(run / "review" / "decision.json", {"decision": "needs_revision"})
    write_json(run / "results" / "P01.json", {
        "paper_id": "paper-1", "evidence": [{"claim": "New claim", "quote": "New quote"}]})
    assert lib.detail(run.name)["papers"][0]["evidence_context"] == [{}]


@pytest.mark.parametrize("source", [
    {"paper_id": "wrong-paper", "full_text": "Exact quotation"},
    {"paper_id": "paper-1", "full_text": "Replaced source text"},
])
def test_changed_or_mismatched_source_is_not_served(library, source):
    lib, run = library
    write_json(run / "sources" / "P01.json", source)
    assert not lib.detail(run.name)["papers"][0]["has_source"]
    with pytest.raises(FileNotFoundError):
        lib.source(run.name, "P01")


@pytest.mark.parametrize("run_id", ["..", "../outside", "C:\\outside", "a/b", "a%2fb"])
def test_run_traversal_rejected(library, run_id):
    lib, _ = library
    with pytest.raises(ValueError):
        lib.detail(run_id)


def test_symlinked_artifact_cannot_escape_run(library):
    lib, run = library
    outside = lib.root / "outside.md"
    outside.write_text("Private", encoding="utf-8")
    try:
        (run / "report_final.md").symlink_to(outside)
    except OSError:
        pytest.skip("Creating symlinks is not available in this Windows session")
    with pytest.raises(ValueError, match="路径"):
        lib.download(run.name, "final")


class Connection:
    def __init__(self, request: bytes):
        self.request = io.BytesIO(request)
        self.response = bytearray()

    def makefile(self, *args):
        return self.request

    def sendall(self, data):
        self.response.extend(data)


def request(lib, path, method="GET"):
    connection = Connection(f"{method} {path} HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n".encode())
    make_handler(lib)(connection, ("127.0.0.1", 9999), None)
    headers, body = bytes(connection.response).split(b"\r\n\r\n", 1)
    return headers, body


def test_http_routes_assets_download_and_read_only_methods(library):
    lib, run = library
    before = snapshot(run)
    for asset in ("/", "/app.js", "/style.css", "/favicon.svg"):
        headers, body = request(lib, asset)
        assert b"200 OK" in headers and body
        assert b"Content-Security-Policy:" in headers
    headers, body = request(lib, "/api/runs")
    assert json.loads(body)["runs"][0]["id"] == run.name
    headers, body = request(lib, f"/api/download?run={run.name}&kind=final")
    assert b"attachment" in headers and b"Evidence [P01]" in body
    for path in ("/.env", "/config.toml", "/../config.toml", "/api/runs/unknown"):
        assert b"404" in request(lib, path)[0]
    assert b"400" in request(lib, "/api/runs/%2E%2E")[0]
    assert b"501" in request(lib, "/api/runs", "POST")[0]
    assert snapshot(run) == before


def test_static_html_assets_exist():
    import re

    html = (ASSETS / "index.html").read_text(encoding="utf-8")
    for asset in re.findall(r'(?:src|href)="/([^"?]+)"', html):
        assert (ASSETS / asset).is_file()


def test_serve_cli_needs_no_config_or_keys(monkeypatch, tmp_path):
    from deepseek_survey import cli

    calls = []
    monkeypatch.setattr("deepseek_survey.web.serve", lambda root, port: calls.append((root, port)))
    monkeypatch.setattr("sys.argv", ["deepseek-survey", "--config", "nonexistent.toml", "serve",
                                    "--runs", str(tmp_path), "--port", "9876"])
    cli.main()
    assert calls == [(tmp_path, 9876)]
