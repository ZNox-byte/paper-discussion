from __future__ import annotations

import asyncio
import io
import json
import threading
from dataclasses import replace
from pathlib import Path
from typing import ClassVar

import pytest

from deepseek_survey.artifacts import read_json, write_json
from deepseek_survey.config import ModelConfig, load_config
from deepseek_survey.models import Paper
from deepseek_survey.web import ResearchLibrary, make_handler
from deepseek_survey.web_jobs import JobConflict, ResearchJobs, SearchRequest, research_config


@pytest.fixture
def jobs(tmp_path, monkeypatch):
    base = load_config("config.toml")
    base = replace(base, models={**base.models, "another_flash": ModelConfig("ds", "test-fast", "flash")})
    monkeypatch.setattr("deepseek_survey.web_jobs.load_config", lambda _: base)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "private-test-key-never-return")
    return ResearchJobs(ResearchLibrary(tmp_path / "runs"), Path("config.toml"))


def payload(**changes):
    return {"question": "我想看算法的实验数据，比较准确率和计算开销，说明数据集及硬件条件。",
            "keywords": "speculative decoding", "flash_model": "another_flash", "target_papers": 2,
            "date_from": "2025-01-01", "date_to": "2025-12-31", "request_id": "test-request-001", **changes}


def paper(year=2025):
    return Paper(paper_id=f"paper-{year}", title=f"Paper {year}", abstract="Results abstract",
                 published=f"{year}-06-01T00:00:00Z", url="https://arxiv.org/abs/test")


def finish(jobs):
    jobs.thread.join(timeout=5)
    assert not jobs.thread.is_alive(), "Worker did not finish"


def test_freeform_requirement_and_flash_routing(jobs):
    request = SearchRequest.model_validate(payload())
    config = research_config(load_config("config.toml"), request.model_copy(update={"flash_model": "ds_flash"}), jobs.library.root)
    assert config.project.research_question.startswith(request.question)
    assert config.routing.reader == config.routing.screening == "ds_flash"
    assert config.routing.reader_fallback is None
    assert config.project.target_papers == config.validation.minimum_results_for_synthesis == 2
    assert config.search.sort_by == "submittedDate"


@pytest.mark.parametrize("change", [
    {"flash_model": "ds_pro"}, {"flash_model": "undefined"}, {"question": ""},
    {"target_papers": 0}, {"target_papers": 33}, {"target_papers": True},
    {"max_results": 100000}, {"date_from": "2025-12-31", "date_to": "2025-01-01"},
    {"date_from": "not-a-date"}, {"date_to": "2999-01-01"},
    {"output_dir": "C:/outside"},
])
def test_invalid_submissions_do_not_create_runs(jobs, change):
    with pytest.raises(ValueError):
        jobs.start_search(payload(**change))
    assert jobs.library.index()["runs"] == []


def test_model_menu_excludes_pro_and_secrets(jobs):
    settings = jobs.settings()
    assert [m["alias"] for m in settings["models"]] == ["ds_flash", "another_flash"]
    assert all(m["available"] for m in settings["models"])
    assert "private-test-key-never-return" not in json.dumps(settings)


def test_manual_search_without_key_and_date_filter(jobs, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    captured = []
    async def discover(config, destination, progress):
        captured.append(config)
        return [paper(2024), paper(2025)]
    monkeypatch.setattr("deepseek_survey.web_jobs.discover", discover)
    created = jobs.start_search(payload())
    finish(jobs)
    result = jobs.get(created["id"])
    assert result["status"] == "completed" and result["candidate_count"] == 1
    assert 'submittedDate:[202501010000 TO 202512312359]' in captured[0].search.queries[0]
    assert not (jobs.library.root / created["id"] / "api_usage.json").exists()
    again = jobs.start_search(payload())
    assert again["id"] == created["id"] and len(jobs.library.index()["runs"]) == 1


class FakeClient:
    calls: ClassVar[list] = []
    def __init__(self, config):
        self.config = config
        self.events = []
        self.budget_status = {"charged_tokens": 30}
    def check_keys(self):
        return []
    async def __aenter__(self):
        return self
    async def __aexit__(self, *_):
        pass
    async def complete_json(self, **kwargs):
        self.calls.append((self.config, kwargs))
        return {"queries": ['all:"speculative decoding"']}, {"model": "test-fast", "usage": {"total_tokens": 30}}


def test_natural_language_search_uses_chosen_flash_and_saves_query_usage(jobs, monkeypatch):
    FakeClient.calls = []
    monkeypatch.setattr("deepseek_survey.web_jobs.RoutedClient", FakeClient)
    async def discover(*_):
        return [paper()]
    monkeypatch.setattr("deepseek_survey.web_jobs.discover", discover)
    created = jobs.start_search(payload(keywords=""))
    finish(jobs)
    result = jobs.get(created["id"])
    assert result["status"] == "completed"
    config, call = FakeClient.calls[0]
    assert call["user"] == payload()["question"]
    assert call["model"] == "another_flash" and config.review.mode == "external"
    assert read_json(jobs.library.root / created["id"] / "api_usage.json")[0]["stage"] == "query_planning"


def test_reading_uses_saved_question_and_new_run_without_overwriting_search(jobs, monkeypatch):
    monkeypatch.setattr("deepseek_survey.web_jobs.RoutedClient", FakeClient)
    async def discover(*_):
        return [paper()]
    monkeypatch.setattr("deepseek_survey.web_jobs.discover", discover)
    search = jobs.start_search(payload())
    finish(jobs)
    source = jobs.library.root / search["id"]
    original = {p.name: p.read_bytes() for p in source.iterdir() if p.is_file()}
    captured = []
    async def pipeline(config, client, *, resume_dir, progress):
        captured.append(config)
        write_json(resume_dir / "run.json", {"status": "awaiting_review", "title": config.project.title})
    monkeypatch.setattr("deepseek_survey.web_jobs.run_pipeline", pipeline)
    created = jobs.start_read({"source_run": search["id"], "flash_model": "ds_flash",
                               "target_papers": 1, "request_id": "reading-request-001"})
    finish(jobs)
    assert created["id"] != search["id"]
    assert captured[0].project.research_question.startswith(payload()["question"])
    assert captured[0].routing.reader == captured[0].routing.screening == "ds_flash"
    assert jobs.get(created["id"])["status"] == "awaiting_review"
    assert original == {p.name: p.read_bytes() for p in source.iterdir() if p.is_file()}


def test_cancel_and_duplicate_submission_do_not_start_extra_tasks(jobs, monkeypatch):
    started = threading.Event()
    async def discover(*_):
        started.set()
        await asyncio.Event().wait()
    monkeypatch.setattr("deepseek_survey.web_jobs.discover", discover)
    first = jobs.start_search(payload())
    assert started.wait(timeout=3)
    assert jobs.start_search(payload())["id"] == first["id"]
    with pytest.raises(JobConflict):
        jobs.start_search(payload(request_id="different-request"))
    jobs.cancel(first["id"])
    finish(jobs)
    assert jobs.active_id is None
    assert jobs.get(first["id"])["status"] == "interrupted"


def test_failure_is_visible_and_secret_redacted(jobs, monkeypatch):
    async def discover(*_):
        raise RuntimeError("provider rejected private-test-key-never-return")
    monkeypatch.setattr("deepseek_survey.web_jobs.discover", discover)
    first = jobs.start_search(payload())
    finish(jobs)
    result = jobs.get(first["id"])
    assert result["status"] == "failed"
    assert "private-test-key-never-return" not in json.dumps(result)
    assert jobs.active_id is None


class Connection:
    def __init__(self, request):
        self.input = io.BytesIO(request)
        self.output = bytearray()
    def makefile(self, *_):
        return self.input
    def sendall(self, data):
        self.output.extend(data)


def http_request(jobs, *, token=None, host="127.0.0.1:8765", origin="http://127.0.0.1:8765", data=None):
    body = json.dumps(data or payload()).encode()
    headers = ["POST /api/jobs/search HTTP/1.0", f"Host: {host}", f"Origin: {origin}",
               "Content-Type: application/json", f"Content-Length: {len(body)}"]
    if token:
        headers.append(f"X-Research-Token: {token}")
    connection = Connection(("\r\n".join(headers) + "\r\n\r\n").encode() + body)
    make_handler(jobs.library, jobs)(connection, ("127.0.0.1", 9999), None)
    return bytes(connection.output)


def test_http_paid_actions_require_same_site_token(jobs, monkeypatch):
    calls = []
    monkeypatch.setattr(jobs, "start_search", lambda data: calls.append(data) or {"id": "test"})
    assert b"403" in http_request(jobs)
    assert b"403" in http_request(jobs, token=jobs.token, origin="https://evil.test")
    assert b"403" in http_request(jobs, token=jobs.token, host="evil.test")
    assert calls == []
    assert b"202" in http_request(jobs, token=jobs.token)
    assert calls[0]["question"] == payload()["question"]
