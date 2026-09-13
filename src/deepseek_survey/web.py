"""Read-only local research viewer. Never starts models or rewrites research artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
from collections import Counter
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

ASSETS = Path(__file__).with_name("web_assets")


def _json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return default


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


class ResearchLibrary:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def run_path(self, run_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
            raise ValueError("无效的研究记录")
        path = (self.root / run_id).resolve()
        if path.parent != self.root or not path.is_dir():
            raise FileNotFoundError("研究记录不存在")
        for folder in (path, *(path / name for name in
                                ("review", "tasks", "results", "sources", "provenance", "screening"))):
            if not folder.resolve().is_relative_to(path):
                raise ValueError("研究产物路径超出当前运行目录")
            for pattern in ("*.json", "*.md"):
                if any(not item.resolve().is_relative_to(path) for item in folder.glob(pattern)):
                    raise ValueError("研究产物路径超出当前运行目录")
        return path

    def index(self) -> dict:
        runs = []
        if self.root.is_dir():
            for path in sorted(self.root.iterdir(), reverse=True):
                if (path.is_dir() and path.resolve().parent == self.root
                        and re.fullmatch(r"[A-Za-z0-9_-]+", path.name)
                        and ((path / "run.json").is_file() or (path / "candidates.json").is_file())):
                    manifest = _dict(_json(path / "run.json", {}))
                    runs.append({
                        "id": path.name, "title": manifest.get("title", "未归属主题 · 候选材料"),
                        "round": manifest.get("round_number"),
                        "status": manifest.get("status", "discovered"),
                        "target": manifest.get("target_papers"),
                        "validated": manifest.get("validated_results"),
                        "has_final": (path / "report_final.md").is_file(),
                        "modified_at": datetime.fromtimestamp(
                            ((path / "run.json") if (path / "run.json").exists()
                             else path / "candidates.json").stat().st_mtime, UTC
                        ).isoformat(),
                    })
        preferred = next((r["id"] for r in runs if r["has_final"]), None)
        return {"runs": runs, "default_run": preferred or (runs[0]["id"] if runs else None),
                "read_at": datetime.now(UTC).isoformat(), "mode": "read_only"}

    def detail(self, run_id: str) -> dict:
        run = self.run_path(run_id)
        manifest = _dict(_json(run / "run.json", {}))
        bundle = _dict(_json(run / "review_bundle.json", {}))
        if not bundle:
            bundle = _dict(_json(run / "review" / "review_bundle.json", {}))
        decision = _dict(_json(run / "review" / "decision.json", {}))
        status = _dict(_json(run / "review" / "status.json", {}))
        sources = {item.get("paper_id"): item for item in
                   _list(_json(run / "content_status.json", [])) if isinstance(item, dict)}
        candidates = {item.get("paper_id"): item for item in
                      _list(_json(run / "candidates.json", [])) if isinstance(item, dict)}
        selection = _dict(_json(run / "screening" / "selection.json", {}))
        source_manifest = _dict(_json(run / "sources" / "manifest.json", {}))
        specs = _list(_json(run / "tasks" / "manifest.json", []))
        if not specs:
            specs = [{**item, "task_id": f"P{n:02d}"} for n, item in
                     enumerate(_list(selection.get("selected")), 1) if isinstance(item, dict)]
        cards = {item.get("task_id"): item for item in _list(bundle.get("source_cards"))
                 if isinstance(item, dict)}
        for task, card in cards.items():
            paper = _dict(card.get("paper"))
            if paper.get("paper_id"):
                candidates.setdefault(paper["paper_id"], paper)
            if task not in {item.get("task_id") for item in specs}:
                specs.append({"task_id": task, "paper_id": paper.get("paper_id")})
        valid_new = False
        approval_error = None
        if manifest.get("schema_version", 0) >= 3 or bundle.get("schema_version", 0) >= 3:
            if decision.get("decision") == "approved":
                try:
                    from .review import _validate_decision

                    if bundle.get("schema_version", 0) < 3 or not manifest:
                        raise ValueError("新版审批缺少新版审查包或运行记录")
                    _validate_decision(bundle, decision, _text(run / "review" / "main.md"),
                                       _text(run / "review" / "review.md"))
                    valid_new = (
                        bool(decision.get("main_sha256")) and bool(decision.get("bundle_sha256"))
                        and decision.get("main_sha256") == _digest(run / "review" / "main.md")
                        and decision.get("bundle_sha256") == _digest(run / "review_bundle.json")
                    )
                    if not valid_new:
                        approval_error = "正文或证据包与批准记录不一致"
                except (ValueError, TypeError, KeyError):
                    approval_error = "批准记录未通过完整性检查"
            review_state = "approved" if valid_new else (
                "stale" if decision.get("decision") == "approved"
                else decision.get("decision", "awaiting_review")
            )
        else:
            review_state = "legacy_completed" if manifest.get("status") == "completed" else (
                "awaiting_review" if manifest.get("status") == "awaiting_codex_review" else "unreviewed"
            )
        classification = _dict(_json(run / "classification.json", {}))
        final_categories = {}
        if valid_new:
            final_categories = {a["task_id"]: a["category"] for a in decision["classification"]}
        elif review_state == "legacy_completed":
            for category, tasks in classification.items():
                for task in _list(tasks):
                    final_categories[task] = category
        papers = []
        for spec in specs:
            task = spec.get("task_id", "")
            if not re.fullmatch(r"P\d+", task):
                continue
            card = cards.get(task, {})
            if valid_new and card:
                spec = {**spec, "paper_id": _dict(card.get("paper")).get("paper_id")}
            result = _dict(_json(run / "results" / f"{task}.json", {}))
            if valid_new and card.get("reading_card"):
                result = _dict(card["reading_card"])
            if not result:
                result = _dict(card.get("reading_card", card.get("flash_reading_card", {})))
            if (result.get("task_id") not in (None, task)
                    or result.get("paper_id") not in (None, spec.get("paper_id"))):
                result = {}
            if result:
                result.setdefault("experimental_setup", result.get("data_and_training", ""))
                result.setdefault("relation_to_topic", result.get("relation_to_deepseek", ""))
            meta = (_dict(card.get("paper")) if valid_new else
                    candidates.get(spec.get("paper_id"), _dict(card.get("paper"))))
            paper_id = meta.get("paper_id") or spec.get("paper_id") or result.get("paper_id")
            source = sources.get(paper_id, {})
            snapshot = _dict(_json(run / "sources" / f"{task}.json", {}))
            if snapshot.get("paper_id") != paper_id:
                snapshot = {}
            card_source = _dict(card.get("source"))
            trace = (_dict(card.get("provenance")) if valid_new else
                     _dict(_json(run / "provenance" / f"{task}.json", {}))
                     or _dict(card.get("provenance")))
            producer = _dict(trace.get("producer"))
            warnings = list(_list(card_source.get("warnings")))
            source_entry = (_dict(card_source.get("manifest")) if valid_new else
                            _dict(source_manifest.get(task)))
            if snapshot and source_entry and (
                    source_entry.get("paper_id") != paper_id
                    or source_entry.get("sha256") != _digest(run / "sources" / f"{task}.json")):
                snapshot = {}
                warnings.append("原文文件与来源清单不一致，已停用原文展示。")
            elif snapshot and not source_entry:
                warnings.append("来源清单缺失，原文文件未通过清单哈希核验。")
            saved_text = snapshot.get("full_text") or snapshot.get("text", "")
            if valid_new and saved_text and card_source.get("text_sha256") != hashlib.sha256(
                    saved_text.encode("utf-8")).hexdigest():
                snapshot = {}
                warnings.append("本地原文与获批证据包不一致，已停用原文展示；仍可查看包内获批引句。")
            if source.get("warning") and source["warning"] not in warnings:
                warnings.append(source["warning"])
            has_source = bool(snapshot.get("full_text") or snapshot.get("text"))
            if not has_source:
                warnings.append("历史记录未保存原文上下文，可查看已有引句或打开论文原文。")
            papers.append({
                "key": f"{run_id}:{task}", "run_id": run_id, "task_id": task,
                "paper_id": paper_id, "title": result.get("title") or meta.get("title") or spec.get("title", task),
                "published": meta.get("published"), "authors": meta.get("authors", []),
                "url": meta.get("url"), "pdf_url": meta.get("pdf_url"),
                "abstract": meta.get("abstract", ""), "result": result,
                "category": final_categories.get(task) or spec.get("category_hint")
                or next(iter(_list(result.get("categories"))), "未分类"),
                "classification_status": "final" if valid_new else (
                    "legacy" if task in final_categories else "provisional"),
                "source": snapshot.get("source") or card_source.get("source") or source.get("source", "unknown"),
                "has_source": has_source, "sampled": snapshot.get("sampled", False),
                "page_count": snapshot.get("page_count", source.get("page_count")),
                "warnings": list(dict.fromkeys(str(w) for w in warnings)),
                "status": "validated" if result else "unavailable",
                "evidence_context": [next((context for context in _list(card.get("evidence_context"))
                                            if context.get("quote") == evidence.get("quote")
                                            and context.get("claim") == evidence.get("claim")), {})
                                     for evidence in _list(result.get("evidence"))],
                "producer": {k: producer.get(k) for k in
                             ("provider", "model", "response_model", "origin") if producer.get(k)},
                "screening": next((s for s in _list(selection.get("selected"))
                                   if s.get("paper_id") == paper_id), {}),
            })
        reports = {}
        for key, filename in (("final", "report_final.md"), ("draft", "report_draft.md"),
                              ("legacy_draft", "report_pro.md"), ("cards", "report_cards.md")):
            content = _text(run / filename)
            if content:
                reports[key] = {"label": {"final": "定稿", "draft": "上层草稿",
                                          "legacy_draft": "历史草稿", "cards": "阅读卡片"}[key],
                                "text": content.split("\n## 逐篇阅读卡片")[0] if key != "cards" else content}
        if valid_new:
            reports["final"] = {"label": "已批准正文", "text": _text(run / "review" / "main.md")}
        elif _text(run / "review" / "main.md"):
            reports["review_main"] = {"label": "待审正文", "text": _text(run / "review" / "main.md")}
        if "final" in reports and not valid_new and review_state != "legacy_completed":
            reports["final"]["label"] = "历史定稿 · 待核验"
        review_record = _text(run / "review" / "review.md") or _text(run / "review" / "codex_review.md")
        categories = dict(Counter(p["category"] for p in papers if p["result"]))
        budget = _dict(_json(run / "budget.json", {}))
        usage = _list(_json(run / "api_usage.json", []))
        usage_by_model: dict[str, dict] = {}
        for event in usage:
            if not isinstance(event, dict):
                continue
            name = event.get("response_model") or event.get("model") or event.get("requested_model", "未记录")
            row = usage_by_model.setdefault(name, {"model": name, "requests": 0, "tokens": 0, "unknown": 0})
            row["requests"] += 1
            token_count = _dict(event.get("usage")).get("total_tokens")
            if isinstance(token_count, int):
                row["tokens"] += token_count
            else:
                row["unknown"] += 1
        selected_ids = {p["paper_id"] for p in papers}
        deferred = {p.get("paper_id"): p.get("rationale", "") for p in
                    _list(selection.get("deferred_candidates")) if isinstance(p, dict)}
        return {
            "id": run_id, "title": manifest.get("title", "未归属主题 · 候选材料"), "round": manifest.get("round_number"),
            "status": manifest.get("status", "discovered"), "target": manifest.get("target_papers"),
            "question": bundle.get("research_question") or _dict(manifest.get("configuration")).get("question", ""),
            "review_state": review_state, "approval_error": approval_error,
            "reviewer": decision.get("reviewer") or status.get("reviewer") or bundle.get("reviewer", "未记录"),
            "review_mode": _dict(_dict(manifest.get("configuration")).get("review")).get("mode", "external"),
            "reports": reports, "has_bundle": bool(bundle), "papers": papers, "categories": categories,
            "review_record": review_record, "decision": {
                k: decision.get(k, []) for k in ("unresolved_issues", "coverage_gaps", "reread_requests")},
            "failures": _list(_json(run / "failures.json", [])),
            "models": _dict(manifest.get("models")), "usage": list(usage_by_model.values()),
            "budget": budget, "usage_complete": bool(budget),
            "candidates": [{"paper_id": p.get("paper_id"), "title": p.get("title"),
                            "published": p.get("published"), "url": p.get("url"),
                            "abstract": p.get("abstract"),
                            "disposition": "selected" if p.get("paper_id") in selected_ids else (
                                "deferred" if p.get("paper_id") in deferred else (
                                    "unselected" if selection else "unscreened")),
                            "rationale": deferred.get(p.get("paper_id"), "")}
                           for p in candidates.values()],
            "read_at": datetime.now(UTC).isoformat(),
        }

    def source(self, run_id: str, task_id: str) -> dict:
        if not re.fullmatch(r"P\d+", task_id):
            raise ValueError("无效的论文编号")
        run = self.run_path(run_id)
        paper = next((p for p in self.detail(run_id)["papers"] if p["task_id"] == task_id), None)
        if not paper or not paper["has_source"]:
            raise FileNotFoundError("没有与这篇论文匹配的原文存档")
        source = _dict(_json(run / "sources" / f"{task_id}.json", {}))
        return {"task_id": task_id, "text": source.get("full_text") or source.get("text", ""),
                "source": source.get("source", "unavailable")}

    def download(self, run_id: str, kind: str) -> tuple[bytes, str]:
        run = self.run_path(run_id)
        filenames = {"final": "report_final.md", "draft": "report_draft.md",
                     "legacy_draft": "report_pro.md", "cards": "report_cards.md",
                     "review_main": "review/main.md", "bundle": "review_bundle.json"}
        if kind not in filenames:
            raise ValueError("不支持的导出格式")
        detail = self.detail(run_id)
        if kind == "final" and detail["review_state"] == "approved":
            return detail["reports"]["final"]["text"].encode("utf-8"), f"{run_id}-approved-main.md"
        path = run / filenames[kind]
        if kind == "bundle" and not path.exists():
            path = run / "review" / "review_bundle.json"
        if not path.is_file():
            raise FileNotFoundError("此运行尚无该产物")
        return path.read_bytes(), f"{run_id}-{path.name}"


def make_handler(library: ResearchLibrary):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlsplit(self.path)
            route = unquote(url.path)
            try:
                if route == "/api/runs":
                    return self.send_json(library.index())
                match = re.fullmatch(r"/api/runs/([^/]+)(?:/source/(P\d+))?", route)
                if match:
                    return self.send_json(library.source(*match.groups()) if match[2]
                                          else library.detail(match[1]))
                if route == "/api/download":
                    query = parse_qs(url.query)
                    data, filename = library.download(query.get("run", [""])[0],
                                                      query.get("kind", ["final"])[0])
                    return self.send_bytes(data, "application/octet-stream", filename=filename)
                if route.startswith("/api/"):
                    raise FileNotFoundError("接口不存在")
                asset = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css",
                         "/favicon.svg": "favicon.svg"}.get(route)
                if not asset:
                    raise FileNotFoundError("页面不存在")
                path = ASSETS / asset
                content_type = mimetypes.guess_type(asset)[0] or "application/octet-stream"
                if asset.endswith(".js"):
                    content_type = "text/javascript"
                return self.send_bytes(path.read_bytes(), f"{content_type}; charset=utf-8")
            except (FileNotFoundError, ValueError) as exc:
                self.send_json({"error": str(exc)}, 404 if isinstance(exc, FileNotFoundError) else 400)
            except (OSError, TypeError, KeyError):
                self.send_json({"error": "这条记录暂时无法读取，请刷新或选择其他运行。"}, 500)

        def send_json(self, data, status=200):
            self.send_bytes(json.dumps(data, ensure_ascii=False).encode("utf-8"),
                            "application/json; charset=utf-8", status)

        def send_bytes(self, content, content_type, status=200, filename=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; "
                             "style-src 'self'; img-src 'self' data:; connect-src 'self'; "
                             "object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, fmt, *args):
            return

    return Handler


def serve(runs_dir: Path, port: int = 8765) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(ResearchLibrary(runs_dir)))
    print(f"Paper Atlas ready: http://127.0.0.1:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="本地论文研究结果工作台")
    parser.add_argument("--runs", type=Path, default=Path("runs"))
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    serve(args.runs, args.port)
