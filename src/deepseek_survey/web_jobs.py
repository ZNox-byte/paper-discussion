"""Local UI jobs: natural-language discovery and explicitly started Flash reading."""
from __future__ import annotations

import asyncio
import os
import re
import secrets
import threading
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .artifacts import new_run_directory, read_json, write_json
from .config import AppConfig, load_config
from .pipeline import discover, run_pipeline
from .providers import RoutedClient

ACTIVE = {"queued", "running", "stopping"}
UI_CATEGORIES = ("算法与方法", "理论与复杂度", "实验与性能评估", "系统与应用", "数据与基准", "综述与复现")


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=8, max_length=6000)
    title: str = Field(default="", max_length=120)
    keywords: str = Field(default="", max_length=2000)
    date_from: date | None = None
    date_to: date | None = None
    flash_model: str = Field(max_length=120)
    target_papers: int = Field(default=8, ge=1, le=32, strict=True)
    max_results: int = Field(default=50, ge=10, le=100, strict=True)
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")

    @model_validator(mode="after")
    def dates_and_keywords(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("开始日期不能晚于结束日期")
        if self.date_to and self.date_to > datetime.now(UTC).date():
            raise ValueError("结束日期不能晚于今天")
        if len([line for line in self.keywords.splitlines() if line.strip()]) > 6:
            raise ValueError("最多填写 6 行检索词或检索式")
        return self


class ReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source_run: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    flash_model: str = Field(max_length=120)
    target_papers: int = Field(ge=1, le=32, strict=True)
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")


def query_with_dates(query: str, request: SearchRequest) -> str:
    if not request.date_from and not request.date_to:
        return query
    start = request.date_from or date(1991, 1, 1)
    end = request.date_to or datetime.now(UTC).date()
    return f"({query}) AND submittedDate:[{start:%Y%m%d}0000 TO {end:%Y%m%d}2359]"


def research_config(base: AppConfig, request: SearchRequest, root: Path) -> AppConfig:
    model = base.models.get(request.flash_model)
    if model is None or model.tier != "flash":
        raise ValueError("请选择已配置的 Flash 模型，下层不能使用 Pro")
    # The user's words are retained exactly, including any algorithm/data emphasis.
    scope = (f"\n\n检索范围：arXiv，首次提交日期 {request.date_from or '不限'} 至 "
             f"{request.date_to or '检索当日'}。检索有数量上限；不将最新发表等同于最先进。")
    return replace(
        base,
        project=replace(base.project, title=request.title or request.question.splitlines()[0][:70],
                        research_question=request.question + scope, target_papers=request.target_papers,
                        output_dir=root),
        routing=replace(base.routing, screening=request.flash_model, reader=request.flash_model,
                        reader_fallback=None),
        search=replace(base.search, queries=(), max_results_per_query=request.max_results,
                       sort_by="submittedDate", sort_order="descending"),
        categories=UI_CATEGORIES,
        validation=replace(base.validation, minimum_results_for_synthesis=min(
            base.validation.minimum_results_for_synthesis, request.target_papers)),
        execution=replace(base.execution, reader_concurrency=min(
            base.execution.reader_concurrency, request.target_papers)),
    )


class JobConflict(ValueError):
    pass


class ResearchJobs:
    def __init__(self, library, config_path: Path):
        self.library = library
        self.config_path = config_path.resolve()
        self.token = secrets.token_urlsafe(32)
        self.session = secrets.token_hex(16)
        self.lock = threading.RLock()
        self.active_id: str | None = None
        self.thread: threading.Thread | None = None
        self.loop = None
        self.task = None
        self.stopping = False
        from .codex_review import SubscriptionReview
        self.subscription = SubscriptionReview(self)

    def settings(self) -> dict:
        try:
            config = load_config(self.config_path)
        except (OSError, ValueError, KeyError):
            return {"csrf_token": self.token, "models": [],
                    "error": "无法读取项目模型配置，请检查 config.toml；已有结果仍可浏览。"}
        models = []
        for alias, model in config.models.items():
            if model.tier != "flash":
                continue
            provider = config.providers[model.provider]
            models.append({"alias": alias, "provider": model.provider, "model": model.model,
                           "available": bool(os.environ.get(provider.api_key_env, "").strip()),
                           "key_env": provider.api_key_env})
        return {"csrf_token": self.token, "models": models, "default_model": config.routing.reader,
                "default_question": config.project.research_question,
                "reviewer": "Codex 订阅", "review_mode": "codex_subscription",
                "max_requests": config.execution.max_requests,
                "max_total_tokens": config.execution.max_total_tokens}

    def _clean(self, text: str) -> str:
        try:
            config = load_config(self.config_path)
            for provider in config.providers.values():
                secret = os.environ.get(provider.api_key_env, "").strip()
                if secret:
                    text = text.replace(secret, "[redacted]")
        except (OSError, ValueError, KeyError):
            pass
        return text[:1500]

    def get(self, run_id: str) -> dict:
        run = self.library.run_path(run_id)
        if not (run / "ui_job.json").is_file():
            raise FileNotFoundError("没有该 UI 任务")
        with self.lock:
            job = read_json(run / "ui_job.json")
            if job["status"] in ACTIVE and (job.get("session") != self.session
                                             or self.active_id != run_id):
                job["status"] = "interrupted"
                job["message"] = "任务服务已重启，旧任务未自动继续。已保存产物仍可查看。"
            job.pop("session", None)
            candidates = run / "candidates.json"
            job["candidate_count"] = len(read_json(candidates)) if candidates.exists() else 0
            job["read_count"] = len(list((run / "results").glob("P*.json")))
            return job

    def list(self) -> dict:
        jobs = []
        for item in self.library.index()["runs"]:
            try:
                jobs.append(self.get(item["id"]))
            except (FileNotFoundError, ValueError, OSError):
                continue
            if len(jobs) == 20:
                break
        return {"jobs": jobs, "active_id": self.active_id}

    def _update(self, run: Path, **changes) -> None:
        with self.lock:
            job = read_json(run / "ui_job.json")
            job.update(changes, updated_at=datetime.now(UTC).isoformat())
            write_json(run / "ui_job.json", job)

    def _progress(self, run: Path, message: str) -> None:
        with self.lock:
            job = read_json(run / "ui_job.json")
            message = self._clean(message)
            self._update(run, message=message, logs=[*job["logs"], message][-40:])

    def start_search(self, payload: dict) -> dict:
        request = SearchRequest.model_validate(payload)
        config = research_config(load_config(self.config_path), request, self.library.root)
        # Query planning uses only the selected Flash; no upper reviewer key is needed.
        planning = replace(config, review=replace(config.review, mode="external"))
        if not request.keywords and (missing := RoutedClient(planning).check_keys()):
            raise ValueError("自然语言检索需要所选 Flash 的密钥：" + ", ".join(missing)
                             + "。也可填写手动英文检索词，先检索文献。")
        return self._start("search", request, config)

    def start_read(self, payload: dict) -> dict:
        reading = ReadRequest.model_validate(payload)
        source = self.get(reading.source_run)
        if source["kind"] != "search" or source["status"] != "completed":
            raise ValueError("请先完成一次文献检索，再开始阅读")
        if source["candidate_count"] < reading.target_papers:
            raise ValueError(f"仅找到 {source['candidate_count']} 篇候选，请减少阅读篇数或扩大检索范围")
        request = SearchRequest.model_validate({**source["request"],
            "flash_model": reading.flash_model, "target_papers": reading.target_papers,
            "request_id": reading.request_id})
        config = research_config(load_config(self.config_path), request, self.library.root)
        config = replace(config, search=replace(config.search, queries=tuple(source["queries"])))
        config = replace(config, review=replace(config.review, mode="external", name="Codex"))
        if missing := RoutedClient(config).check_keys():
            raise ValueError("阅读所需密钥尚未设置：" + ", ".join(missing))
        return self._start("read", request, config, reading.source_run)

    def _start(self, kind: Literal["search", "read"], request: SearchRequest,
               config: AppConfig, source_run: str | None = None) -> dict:
        with self.lock:
            for old in self.list()["jobs"]:
                if old["request"]["request_id"] == request.request_id:
                    if (old["kind"] != kind or old.get("source_run") != source_run
                            or old["request"] != request.model_dump(mode="json")):
                        raise JobConflict("此提交编号已用于不同请求，请重新提交")
                    return old
            if self.active_id:
                raise JobConflict("已有任务正在执行，请等它完成或先停止任务")
            run = new_run_directory(self.library.root)
            now = datetime.now(UTC).isoformat()
            job = {"id": run.name, "kind": kind, "status": "queued", "session": self.session,
                   "request": request.model_dump(mode="json"), "source_run": source_run,
                   "queries": list(config.search.queries), "message": "准备任务…", "logs": [],
                   "created_at": now, "updated_at": now}
            write_json(run / "ui_job.json", job)
            write_json(run / "run.json", {"title": config.project.title, "status": "searching"
                                          if kind == "search" else "queued", "schema_version": 3,
                                          "target_papers": request.target_papers,
                                          "configuration": {"question": config.project.research_question}})
            self.active_id = run.name
            self.stopping = False
            self.thread = threading.Thread(target=self._worker, args=(run, kind, request, config, source_run),
                                           daemon=True, name=f"research-{run.name}")
            self.thread.start()
            return self.get(run.name)

    def _worker(self, run: Path, kind: str, request: SearchRequest,
                config: AppConfig, source_run: str | None) -> None:
        try:
            asyncio.run(self._execute(run, kind, request, config, source_run))
        except asyncio.CancelledError:
            self._update(run, status="interrupted", message="已停止任务，已保存结果保留。")
            manifest = read_json(run / "run.json")
            write_json(run / "run.json", {**manifest, "status": "interrupted"})
        except Exception as exc:  # noqa: BLE001 -- contain worker failures and release the active slot
            message = self._clean(f"{type(exc).__name__}: {exc}")
            self._update(run, status="failed", message=message)
            manifest = read_json(run / "run.json")
            write_json(run / "run.json", {**manifest, "status": "failed", "error": message})
        finally:
            with self.lock:
                self.active_id = None
                self.loop = self.task = None

    async def _execute(self, run: Path, kind: str, request: SearchRequest,
                       config: AppConfig, source_run: str | None) -> None:
        with self.lock:
            self.loop, self.task = asyncio.get_running_loop(), asyncio.current_task()
            if self.stopping:
                raise asyncio.CancelledError
        self._update(run, status="running")
        progress = lambda message: self._progress(run, message)
        if kind == "search":
            queries = [line.strip() for line in request.keywords.splitlines() if line.strip()]
            if queries:
                queries = [q if re.search(r"\b(?:all|ti|abs|au|cat|id):", q) else
                           'all:"' + q.replace('"', '').replace('\\', '') + '"' for q in queries]
            else:
                progress("正在由所选 Flash 根据你的完整需求生成英文检索式…")
                planning = replace(config, review=replace(config.review, mode="external"))
                async with RoutedClient(planning) as client:
                    try:
                        raw, metadata = await client.complete_json(
                            model=request.flash_model, max_tokens=1800,
                            system="You translate user research requests into arXiv search queries. "
                                   "Return JSON only: {\"queries\": [\"all:...\"]}, 1 to 4 queries. "
                                   "Preserve the requested emphasis on methods, experimental data, or any "
                                   "other details without imposing fixed categories. Use English technical "
                                   "keywords, quotes for phrases and arXiv all/ti/abs fields with AND/OR. "
                                   "Include a broad topic query to avoid missing relevant papers. "
                                   "Do not invent algorithm names, claims or dates; date filtering is handled separately.",
                            user=request.question)
                        write_json(run / "api_usage.json", [{"stage": "query_planning", **metadata}])
                    finally:
                        write_json(run / "budget.json", client.budget_status)
                        write_json(run / "api_attempts.json", client.events)
                queries = raw.get("queries") if isinstance(raw, dict) else None
                if (not isinstance(queries, list) or not 1 <= len(queries) <= 4
                        or any(not isinstance(q, str) or not q.strip() or len(q) > 500 for q in queries)):
                    raise ValueError("模型没有返回有效检索式，请重试或填写手动检索词")
            queries = list(dict.fromkeys(query_with_dates(q, request) for q in queries))
            self._update(run, queries=queries)
            config = replace(config, search=replace(config.search, queries=tuple(queries)))
            papers = await discover(config, run / "candidates.json", progress)
            # Apply the same inclusive dates locally to guard against unexpected provider results.
            papers = [p for p in papers if (not request.date_from and not request.date_to) or (
                p.published and (not request.date_from or p.published[:10] >= str(request.date_from))
                and (not request.date_to or p.published[:10] <= str(request.date_to)))]
            write_json(run / "candidates.json", [p.model_dump(mode="json") for p in papers])
            manifest = read_json(run / "run.json")
            write_json(run / "run.json", {**manifest, "status": "discovered", "search_queries": queries})
            self._update(run, status="completed", message=f"找到 {len(papers)} 篇去重候选论文，可查看摘要或开始阅读。")
        else:
            source = self.library.run_path(source_run)
            write_json(run / "candidates.json", read_json(source / "candidates.json"))
            async with RoutedClient(config) as client:
                await run_pipeline(config, client, resume_dir=run, progress=progress)
            status = read_json(run / "run.json").get("status", "awaiting_review")
            self._update(run, status=status, message="阅读产物已保存。" + (
                "可在“审阅与问题”中启动 Codex 订阅终审。" if status == "awaiting_review" else "可打开研究结果查看。"))

    def cancel(self, run_id: str) -> dict:
        with self.lock:
            if self.active_id != run_id or self.get(run_id)["status"] not in ACTIVE:
                raise JobConflict("该任务当前没有运行")
            self.stopping = True
            self._update(self.library.run_path(run_id), status="stopping", message="正在停止，保存已完成产物…")
            if self.subscription.active_id == run_id:
                self.subscription.cancel_event.set()
            if self.loop and self.task:
                self.loop.call_soon_threadsafe(self.task.cancel)
            return self.get(run_id)
