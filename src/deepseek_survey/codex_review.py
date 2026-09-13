"""Subscription review jobs. Each review creates a new immutable-input research run."""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .artifacts import new_run_directory, read_json, write_json, write_text
from .codex_bridge import CodexBridge
from .models import Paper, ResearchResult
from .papers import PaperContent
from .review import (
    REVIEW_CHECKLIST,
    _validate_decision,
    build_review_bundle,
    finalize_review,
    review_hashes,
)


def object_schema(properties):
    return {"type": "object", "properties": properties, "required": list(properties),
            "additionalProperties": False}


TEXT = {"type": "string"}
TEXT_LIST = {"type": "array", "items": TEXT}
OUTPUT_SCHEMA = object_schema({
    "main_markdown": TEXT, "review_markdown": TEXT,
    "decision": {"type": "string", "enum": ["approved", "needs_revision", "insufficient_evidence"]},
    "unresolved_issues": TEXT_LIST, "reviewed_task_ids": TEXT_LIST, "coverage_gaps": TEXT_LIST,
    "classification": {"type": "array", "items": object_schema({"task_id": TEXT, "category": TEXT})},
    "reread_requests": {"type": "array", "items": object_schema({"task_id": TEXT, "question": TEXT, "reason": TEXT})},
})


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source_run: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    model: str = Field(min_length=1, max_length=120)
    effort: str = Field(default="high", pattern=r"^(low|medium|high|xhigh|max|ultra)$")
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")


def review_inputs(library, source_id: str):
    """Normalize old cards and rebuild quote contexts from verified saved source bytes."""
    detail = library.detail(source_id)
    source = library.run_path(source_id)
    manifest_path = source / "sources" / "manifest.json"
    source_manifest = read_json(manifest_path) if manifest_path.is_file() else {}
    results, papers, contents, snapshots, provenance = [], {}, {}, {}, {}
    for entry in detail["papers"]:
        if not entry["result"]:
            continue
        raw = dict(entry["result"])
        # The viewer exposes both names for old cards; the strict model accepts one.
        if "experimental_setup" in raw:
            raw.pop("data_and_training", None)
        if "relation_to_topic" in raw:
            raw.pop("relation_to_deepseek", None)
        result = ResearchResult.model_validate(raw)
        results.append(result)
        papers[result.paper_id] = Paper(
            paper_id=result.paper_id, title=entry["title"], abstract=entry["abstract"],
            authors=entry["authors"], published=entry["published"], url=entry["url"] or "",
            pdf_url=entry["pdf_url"])
        provenance[result.task_id] = entry["producer"]
        if entry["has_source"]:
            source_path = source / "sources" / f"{result.task_id}.json"
            source_entry = source_manifest.get(result.task_id, {})
            if (source_entry.get("paper_id") != result.paper_id
                    or source_entry.get("sha256") != hashlib.sha256(source_path.read_bytes()).hexdigest()):
                continue
            snapshot = read_json(source_path)
            text = library.source(source_id, result.task_id)["text"]
            snapshots[result.task_id] = snapshot
            contents[result.paper_id] = PaperContent(
                paper_id=result.paper_id, source=entry["source"], text=text, full_text=text,
                page_count=entry["page_count"], warning="; ".join(entry["warnings"]) or None)
    if not results:
        raise ValueError("此记录没有完整阅读卡片，请先完成 Flash 阅读再终审")
    original = source / "review_bundle.json"
    if not original.is_file():
        original = source / "review" / "review_bundle.json"
    old_bundle = read_json(original) if original.is_file() else {}
    question = detail["question"] or old_bundle.get("research_question", "")
    if not question:
        question = "围绕该研究主题核验算法方法、实验条件与证据，按时间整理技术进展。"
    categories = old_bundle.get("categories") or sorted({c for r in results for c in r.categories})
    bundle = build_review_bundle(
        title=detail["title"], research_question=question, synthesis=None,
        results=results, papers_by_id=papers, contents=contents, categories=tuple(categories),
        planned_total=detail["target"] or len(results), failures=detail["failures"],
        screening=old_bundle.get("screening", {}), provenance=provenance)
    bundle["source_run"] = source_id
    bundle["review_scope"] = "阅读卡片及本地原文中重新定位的引文上下文；不代表已逐页重读全文。"
    if detail["review_record"]:
        bundle["previous_review"] = {"review_record": detail["review_record"],
                                     "decision": detail["decision"]}
    return bundle, snapshots


def missing_evidence(bundle):
    return [card["task_id"] for card in bundle["source_cards"] if (
        card["source"]["source"] in {"unavailable", "abstract", "unknown"}
        or not card["evidence_context"]
        or any(not e.get("matched") for e in card["evidence_context"]))]


def save_review(run: Path, bundle, raw, metadata):
    write_json(run / "review" / "codex_response.json", raw)
    write_json(run / "review" / "codex_metadata.json", metadata)
    if not isinstance(raw, dict):
        raise TypeError("审阅结果必须为对象")
    main, record = raw.get("main_markdown", ""), raw.get("review_markdown", "")
    if not isinstance(main, str) or not isinstance(record, str):
        raise TypeError("审阅正文必须是文本")
    decision = {k: raw.get(k) for k in OUTPUT_SCHEMA["properties"] if not k.endswith("_markdown")}
    decision.update(schema_version=3, reviewer=f"Codex / {metadata['model']}", model_identity=metadata)
    gaps = missing_evidence(bundle)
    if gaps and decision["decision"] == "approved":
        # Local gates can withhold publication; they never manufacture approval.
        decision["decision"] = "insufficient_evidence"
        issue = "缺少可核验的全文引文上下文：" + ", ".join(gaps)
        decision["unresolved_issues"] = [*(decision.get("unresolved_issues") or []), issue]
        decision["reread_requests"] = [*(decision.get("reread_requests") or []), *[
            {"task_id": task, "question": "补齐关键结论、实验数字与比较条件的原文上下文", "reason": issue}
            for task in gaps]]
        record += "\n\n应用核验：模型的批准被拦截。" + issue + "；当前未批准。"
    _validate_decision(bundle, decision, main, record, require_approved=False)
    # Pin to the exact evidence bytes sent to Codex, even if local files change mid-turn.
    expected = metadata["bundle_sha256"]
    if hashlib.sha256((run / "review_bundle.json").read_bytes()).hexdigest() != expected:
        raise ValueError("审阅期间证据包发生变化，已拒绝发布，请重新审阅")
    write_text(run / "review" / "main.md", main.rstrip() + "\n")
    write_text(run / "review" / "review.md", record.rstrip() + "\n")
    decision.update(review_hashes(run))
    write_json(run / "review" / "decision.json", decision)
    status = decision["decision"]
    write_json(run / "review" / "status.json", {"schema_version": 3, "status": status,
                                               "reviewer": decision["reviewer"]})
    manifest = read_json(run / "run.json")
    write_json(run / "run.json", {**manifest, "status": status, "review_status": status})
    if status == "approved":
        finalize_review(run)
        status = "completed"
    return status


class SubscriptionReview:
    def __init__(self, jobs):
        self.jobs = jobs
        self.bridge = CodexBridge(jobs.config_path.parent)
        self.cancel_event = threading.Event()
        self.active_id = None

    def start(self, payload):
        from .web_jobs import JobConflict

        request = ReviewRequest.model_validate(payload)
        with self.jobs.lock:
            for old in self.jobs.list()["jobs"]:
                if old["request"]["request_id"] == request.request_id:
                    if old.get("review_request") != request.model_dump():
                        raise JobConflict("此提交编号已用于其他请求")
                    return old
            if self.jobs.active_id:
                raise JobConflict("已有任务正在执行，请等它完成或先停止")
        status = self.bridge.connect()
        if not status["authenticated"]:
            raise ValueError("请先在应用中登录 Codex 订阅账号；不需要 OpenAI API Key")
        model = next((m for m in status["models"] if m["id"] == request.model), None)
        if not model:
            raise ValueError("订阅模型列表中没有所选模型，请刷新模型列表后选择；不会自动换模型")
        if request.effort not in model["efforts"]:
            raise ValueError("所选模型不支持这一推理强度，请重新选择")
        bundle, snapshots = review_inputs(self.jobs.library, request.source_run)
        if len(json.dumps(bundle, ensure_ascii=False).encode("utf-8")) > 1_500_000:
            raise ValueError("证据包过大，请减少单次阅读篇数；本次尚未调用模型")
        with self.jobs.lock:
            if self.jobs.active_id:
                raise JobConflict("已有任务正在执行")
            # Recheck idempotency after the network status request.
            for old in self.jobs.list()["jobs"]:
                if old["request"]["request_id"] == request.request_id:
                    if old.get("review_request") != request.model_dump():
                        raise JobConflict("此提交编号已用于其他请求")
                    return old
            run = new_run_directory(self.jobs.library.root)
            manifest = {}
            for task, snapshot in snapshots.items():
                path = run / "sources" / f"{task}.json"
                write_json(path, snapshot)
                manifest[task] = {"paper_id": snapshot["paper_id"],
                                  "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            write_json(run / "sources" / "manifest.json", manifest)
            for card in bundle["source_cards"]:
                card["source"]["manifest"] = manifest.get(card["task_id"], {})
                write_json(run / "results" / f"{card['task_id']}.json", card["reading_card"])
            bundle["source_manifest"] = manifest
            write_json(run / "review_bundle.json", bundle)
            write_json(run / "candidates.json", [c["paper"] for c in bundle["source_cards"]])
            write_json(run / "tasks" / "manifest.json", [
                {"task_id": c["task_id"], "paper_id": c["paper"]["paper_id"]} for c in bundle["source_cards"]])
            write_json(run / "run.json", {"schema_version": 3, "title": bundle["research_title"],
                "status": "awaiting_review", "review_status": "awaiting_review",
                "validated_results": len(bundle["source_cards"]), "target_papers": bundle["planned_total"],
                "source_run": request.source_run, "configuration": {"question": bundle["research_question"],
                                                                       "review": {"mode": "codex_subscription"}}})
            now = datetime.now(UTC).isoformat()
            write_json(run / "ui_job.json", {"id": run.name, "kind": "review", "status": "queued",
                "session": self.jobs.session, "review_request": request.model_dump(),
                "source_run": request.source_run, "created_at": now, "updated_at": now,
                "message": "准备 Codex 订阅终审…", "logs": [], "queries": [],
                "request": {"question": bundle["research_question"], "title": bundle["research_title"],
                    "target_papers": bundle["planned_total"], "flash_model": request.model,
                    "request_id": request.request_id}})
            self.jobs.active_id = self.active_id = run.name
            self.cancel_event.clear()
            self.jobs.thread = threading.Thread(target=self._worker, args=(run, bundle, request),
                                                daemon=True, name="codex-review")
            self.jobs.thread.start()
            return self.jobs.get(run.name)

    def _worker(self, run, bundle, request):
        try:
            self.jobs._update(run, status="running")
            prompt = json.dumps({
                "task": "用中文完成研究综述及独立审查。按研究需求决定重点，按发表时间梳理。不要把最新等同于最先进。",
                "requirements": [*REVIEW_CHECKLIST,
                    "逐篇使用 [P01] 引用，每篇唯一主分类，分类必须来自 categories。",
                    "不足计划篇数时在正文写出 completed_total/planned_total 的实际数字比例，并填写 coverage_gaps。",
                    "审查范围是本地重新定位的引文上下文，不可宣称逐页阅读了全文。",
                    "missing_evidence 非空时必须给出 insufficient_evidence 和补读清单，不得批准。"],
                "missing_evidence": missing_evidence(bundle), "bundle": bundle}, ensure_ascii=False)
            bundle_hash = hashlib.sha256((run / "review_bundle.json").read_bytes()).hexdigest()
            raw, metadata = self.bridge.complete(model=request.model, effort=request.effort,
                prompt=prompt, schema=OUTPUT_SCHEMA, cancel=self.cancel_event,
                progress=lambda msg: self.jobs._progress(run, msg))
            with self.jobs.lock:
                if self.cancel_event.is_set():
                    raise InterruptedError("审阅已停止")
                status = save_review(run, bundle, raw, {**metadata, "bundle_sha256": bundle_hash})
                self.jobs._update(run, status=status, message="Codex 终审已完成，报告已通过核验并发布。"
                                  if status == "completed" else "审阅意见已保存，存在待修订内容或证据缺口，尚未批准。")
        except InterruptedError:
            self.jobs._update(run, status="interrupted", message="已停止 Codex 审阅，未发布报告。")
        except Exception as exc:  # noqa: BLE001 -- retain outputs and unblock the local job queue
            self.jobs._update(run, status="interrupted" if self.cancel_event.is_set() else "failed",
                              message="已停止 Codex 审阅，未发布报告。" if self.cancel_event.is_set()
                              else self.jobs._clean(str(exc)))
        finally:
            job = self.jobs.get(run.name)
            if job["status"] in {"failed", "interrupted"}:
                manifest = read_json(run / "run.json")
                write_json(run / "run.json", {**manifest, "status": job["status"]})
            with self.jobs.lock:
                self.jobs.active_id = self.active_id = None

    def close(self):
        self.cancel_event.set()
        self.bridge.close()
