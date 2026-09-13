from __future__ import annotations

import copy
import hashlib
import io
import json
import threading
from pathlib import Path

import pytest
from test_review import _new_handoff

from deepseek_survey.artifacts import read_json, write_json
from deepseek_survey.codex_bridge import CodexBridge, CodexError, codex_environment
from deepseek_survey.codex_review import missing_evidence, review_inputs, save_review
from deepseek_survey.desktop import DesktopServer
from deepseek_survey.web import ResearchLibrary, make_handler
from deepseek_survey.web_jobs import ResearchJobs


@pytest.fixture
def review_jobs(tmp_path):
    run = tmp_path / "runs" / "source-run"
    run.mkdir(parents=True)
    _new_handoff(run)
    bundle = read_json(run / "review_bundle.json")
    # Bind the actual source snapshot as production pipeline does.
    snapshot = {"paper_id": "paper-1", "source": "pdf", "page_count": 1,
                "text": "Before. An exact evidence quote about measured performance. After."}
    write_json(run / "sources" / "P01.json", snapshot)
    entry = {"paper_id": "paper-1", "sha256": hashlib.sha256((run / "sources" / "P01.json").read_bytes()).hexdigest()}
    write_json(run / "sources" / "manifest.json", {"P01": entry})
    bundle["source_cards"][0]["source"]["manifest"] = entry
    write_json(run / "review_bundle.json", bundle)
    return ResearchJobs(ResearchLibrary(tmp_path / "runs"), tmp_path / "config.toml")


def response(**changes):
    return {"main_markdown": "# 研究结果\n\n按原需求核对实验设置 [P01]。",
            "review_markdown": "核对所提供的原文引文上下文及实验设置，未逐页复查全文。",
            "decision": "approved", "unresolved_issues": [], "coverage_gaps": [],
            "reviewed_task_ids": ["P01"], "classification": [{"task_id": "P01", "category": "Systems"}],
            "reread_requests": [], **changes}


class FakeBridge:
    def __init__(self, raw=None):
        self.raw = raw or response()
        self.calls = []
        self.authenticated = True
    def connect(self):
        return {"authenticated": self.authenticated, "models": [
            {"id": "gpt-6-astra", "efforts": ["high"]}]}
    def complete(self, **kwargs):
        self.calls.append(kwargs)
        kwargs["progress"]("Codex subscribed review")
        return copy.deepcopy(self.raw), {"model": kwargs["model"], "billing": "codex_subscription"}
    def close(self):
        pass


def request(**changes):
    return {"source_run": "source-run", "model": "gpt-6-astra", "effort": "high",
            "request_id": "codex-request-001", **changes}


def finish(jobs):
    jobs.thread.join(timeout=4)
    assert not jobs.thread.is_alive()


def snapshot(directory):
    return {str(p.relative_to(directory)): p.read_bytes() for p in directory.rglob("*") if p.is_file()}


def test_subscription_review_preserves_source_and_binds_published_report(review_jobs):
    jobs = review_jobs
    fake = jobs.subscription.bridge = FakeBridge()
    source = jobs.library.run_path("source-run")
    original = snapshot(source)
    job = jobs.subscription.start(request())
    finish(jobs)
    assert jobs.get(job["id"])["status"] == "completed"
    assert jobs.library.detail(job["id"])["review_state"] == "approved"
    assert snapshot(source) == original
    assert fake.calls[0]["model"] == "gpt-6-astra"
    prompt = json.loads(fake.calls[0]["prompt"])
    assert prompt["bundle"]["research_question"] == "Question"
    assert prompt["bundle"]["source_cards"][0]["evidence_context"][0]["matched"]
    assert jobs.subscription.start(request())["id"] == job["id"]
    assert len(fake.calls) == 1


@pytest.mark.parametrize("changes", [{"model": "gpt-invented"}, {"effort": "ultra"},
                                     {"source_run": "../escape"}, {"output_dir": "C:/outside"}])
def test_invalid_review_never_calls_a_model_or_creates_run(review_jobs, changes):
    review_jobs.subscription.bridge = FakeBridge()
    with pytest.raises(ValueError):
        review_jobs.subscription.start(request(**changes))
    assert len(review_jobs.library.index()["runs"]) == 1
    assert not review_jobs.subscription.bridge.calls


def test_missing_subscription_does_not_fall_back_to_api(review_jobs):
    fake = review_jobs.subscription.bridge = FakeBridge()
    fake.authenticated = False
    with pytest.raises(ValueError, match="登录"):
        review_jobs.subscription.start(request())
    assert not fake.calls
    assert len(review_jobs.library.index()["runs"]) == 1


@pytest.mark.parametrize("missing", ["snapshot", "manifest", "tampered"])
def test_missing_or_unbound_sources_cannot_be_approved(review_jobs, missing):
    jobs = review_jobs
    run = jobs.library.run_path("source-run")
    if missing == "snapshot":
        (run / "sources" / "P01.json").unlink()
    elif missing == "manifest":
        (run / "sources" / "manifest.json").unlink()
    else:
        write_json(run / "sources" / "P01.json", {"paper_id": "wrong", "text": "modified"})
    jobs.subscription.bridge = FakeBridge()
    job = jobs.subscription.start(request())
    finish(jobs)
    assert jobs.get(job["id"])["status"] == "insufficient_evidence"
    assert jobs.library.detail(job["id"])["decision"]["reread_requests"]
    assert not (jobs.library.run_path(job["id"]) / "report_final.md").exists()


def test_invalid_citation_blocks_publication(review_jobs):
    jobs = review_jobs
    jobs.subscription.bridge = FakeBridge(response(main_markdown="Fabricated [P99]"))
    job = jobs.subscription.start(request())
    finish(jobs)
    assert jobs.get(job["id"])["status"] == "failed"
    assert not (jobs.library.run_path(job["id"]) / "report_final.md").exists()


def test_changed_bundle_cannot_be_bound_after_the_fact(review_jobs):
    run = review_jobs.library.run_path("source-run")
    bundle, _ = review_inputs(review_jobs.library, "source-run")
    assert not missing_evidence(bundle)
    with pytest.raises(ValueError, match="发生变化"):
        save_review(run, bundle, response(), {"model": "gpt-6-astra", "bundle_sha256": "wrong"})
    assert not (run / "review" / "decision.json").exists()


def test_cancelled_review_never_publishes(review_jobs):
    entered = threading.Event()
    class WaitingBridge(FakeBridge):
        def complete(self, **kwargs):
            entered.set()
            kwargs["cancel"].wait(timeout=3)
            raise InterruptedError()
    jobs = review_jobs
    jobs.subscription.bridge = WaitingBridge()
    job = jobs.subscription.start(request())
    assert entered.wait(timeout=2)
    jobs.cancel(job["id"])
    finish(jobs)
    assert jobs.get(job["id"])["status"] == "interrupted"
    assert jobs.active_id is None
    assert not (jobs.library.run_path(job["id"]) / "report_final.md").exists()


def test_codex_environment_never_inherits_api_or_ide_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-use")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "must-not-use")
    monkeypatch.setenv("CODEX_HOME", "C:/users/existing-codex")
    env = codex_environment(tmp_path)
    assert not any("API_KEY" in k for k in env)
    assert Path(env["CODEX_HOME"]).is_relative_to(tmp_path)
    assert Path(env["TEMP"]).is_relative_to(tmp_path)


def test_account_metadata_never_returns_tokens_or_email(tmp_path, monkeypatch):
    bridge = CodexBridge(tmp_path)
    class Process:
        def poll(self):
            return None
    bridge.process = Process()
    def call(method, params):
        if method == "account/read":
            return {"account": {"type": "chatgpt", "email": "private@example.test", "planType": "pro"}}
        return {"data": [{"model": "gpt-6-astra", "displayName": "GPT-6 Astra",
                           "supportedReasoningEfforts": [{"reasoningEffort": "high"}]}]}
    monkeypatch.setattr(bridge, "call", call)
    status = bridge.status()
    assert status["authenticated"] and status["default_model"] == "gpt-6-astra"
    assert "private@example.test" not in json.dumps(status)


def test_rpc_failure_does_not_expose_upstream_credentials(tmp_path, monkeypatch):
    bridge = CodexBridge(tmp_path)
    def send(message):
        bridge.pending[message["id"]].put({"error": {"code": 401, "message": "secret-token"}})
    monkeypatch.setattr(bridge, "_send", send)
    with pytest.raises(CodexError) as exc:
        bridge.call("account/read")
    assert "secret-token" not in str(exc.value)


def test_protocol_matches_turn_and_exact_model(tmp_path, monkeypatch):
    bridge = CodexBridge(tmp_path)
    monkeypatch.setattr(bridge, "status", lambda: {"authenticated": True})
    calls = []
    def call(method, params, **_):
        calls.append((method, params))
        if method == "thread/start":
            return {"thread": {"id": "thread-1"}, "model": "gpt-6-astra", "modelProvider": "openai"}
        if method == "turn/start":
            bridge.events.put({"method": "item/completed", "params": {"threadId": "other",
                "item": {"type": "agentMessage", "text": "WRONG"}}})
            bridge.events.put({"method": "item/completed", "params": {"threadId": "thread-1", "turnId": "turn-1",
                "item": {"type": "agentMessage", "text": json.dumps(response())}}})
            bridge.events.put({"method": "turn/completed", "params": {"threadId": "thread-1",
                "turn": {"id": "turn-1", "status": "completed"}}})
            return {"turn": {"id": "turn-1"}}
        return {}
    monkeypatch.setattr(bridge, "call", call)
    raw, metadata = bridge.complete(model="gpt-6-astra", effort="high", prompt="Evidence", schema={},
                                    cancel=threading.Event(), progress=lambda _: None)
    assert raw["decision"] == "approved"
    assert metadata["billing"] == "codex_subscription"
    assert calls[0][1]["sandbox"] == "read-only"
    assert calls[1][1]["model"] == "gpt-6-astra"


@pytest.mark.parametrize("endpoint", ["/api/codex/login", "/api/codex/connect", "/api/jobs/review"])
def test_subscription_actions_require_csrf(review_jobs, endpoint):
    class Connection:
        def __init__(self, data):
            self.input = io.BytesIO(data)
            self.output = bytearray()
        def makefile(self, *_):
            return self.input
        def sendall(self, data):
            self.output.extend(data)
    conn = Connection((f"POST {endpoint} HTTP/1.0\r\nHost: localhost\r\n"
                       "Content-Type: application/json\r\nContent-Length: 2\r\n\r\n{}").encode())
    make_handler(review_jobs.library, review_jobs)(conn, ("127.0.0.1", 1234), None)
    assert b"403" in conn.output


def test_desktop_server_assets_and_shutdown(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMP", str(tmp_path))
    monkeypatch.setenv("TMP", str(tmp_path))
    import urllib.request
    app = DesktopServer(tmp_path)
    app.start()
    try:
        with urllib.request.urlopen(app.url + "/codex.js") as response:
            assert b"codex-panel" in response.read()
        with urllib.request.urlopen(app.url + "/api/codex/status") as response:
            assert not json.loads(response.read())["authenticated"]
        assert read_json(tmp_path / ".app-data" / "desktop.json")["url"] == app.url
    finally:
        app.close()
    assert not app.thread.is_alive()
