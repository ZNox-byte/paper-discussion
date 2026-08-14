from __future__ import annotations

import asyncio
import re
from typing import Any

import pytest

from deepseek_survey.config import (
    AppConfig,
    DeepSeekConfig,
    ProjectConfig,
    SearchConfig,
    ValidationConfig,
)
from deepseek_survey.models import Paper, ScreeningItem
from deepseek_survey.papers import PaperContent
from deepseek_survey.pipeline import _run_readers


class FakeDeepSeekClient:
    def __init__(self, invalid_task_ids: set[str] | None = None) -> None:
        self.active = 0
        self.max_active = 0
        self.requested_models: list[str] = []
        self.invalid_task_ids = invalid_task_ids or set()

    async def complete_json(
        self, *, system: str, user: str, max_tokens: int, model: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        del system, max_tokens
        self.requested_models.append(model)
        task_id = re.search(r"Task ID: (P\d{2})", user).group(1)  # type: ignore[union-attr]
        paper_id = re.search(r"Paper ID: (paper-\d{2})", user).group(1)  # type: ignore[union-attr]
        title = re.search(r"Title: (Paper \d{2})", user).group(1)  # type: ignore[union-attr]
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.02)
        self.active -= 1
        first_quote = (
            "A fabricated quotation that is absent from the supplied paper."
            if task_id in self.invalid_task_ids
            else "First exact quotation long enough for validation."
        )
        second_quote = (
            "Another fabricated quotation that is also absent from the paper."
            if task_id in self.invalid_task_ids
            else "Second exact quotation long enough for validation."
        )
        return (
            {
                "task_id": task_id,
                "paper_id": paper_id,
                "title": title,
                "one_sentence_summary": "总结。",
                "research_question": "研究问题。",
                "methodology": "研究方法。",
                "experimental_setup": "实验设置。",
                "main_contributions": ["主要贡献。"],
                "key_findings": ["关键发现。"],
                "limitations": ["研究局限。"],
                "relation_to_topic": "与 AI Infra 主题相关。",
                "categories": ["基础模型与架构"],
                "evidence": [
                    {
                        "claim": "证据一",
                        "quote": first_quote,
                        "page": None,
                    },
                    {
                        "claim": "证据二",
                        "quote": second_quote,
                        "page": None,
                    },
                ],
                "confidence": 0.9,
                "unanswered_questions": [],
            },
            {"request_id": task_id, "usage": {}},
        )


def _config(tmp_path) -> AppConfig:
    return AppConfig(
        project=ProjectConfig(
            title="Test",
            research_question="Question?",
            language="zh-CN",
            target_papers=32,
            output_dir=tmp_path,
            max_paper_chars=10_000,
        ),
        deepseek=DeepSeekConfig(
            base_url="https://api.deepseek.com",
            screening_model="deepseek-v4-flash",
            reader_model="deepseek-v4-flash",
            synthesis_model="deepseek-v4-pro",
            thinking="enabled",
            reader_concurrency=32,
            max_tokens_screening=100,
            max_tokens_reader=100,
            max_tokens_synthesis=100,
            request_timeout_seconds=10,
            max_retries=0,
        ),
        search=SearchConfig("endpoint", 50, 8, 10, ("query",)),
        validation=ValidationConfig(2, 20, 0),
        categories=("基础模型与架构",),
        source_path=tmp_path / "config.toml",
    )


def _tasks_and_contents() -> tuple[
    list[tuple[str, Paper, ScreeningItem]], dict[str, PaperContent]
]:
    task_specs = []
    contents = {}
    for number in range(1, 33):
        task_id = f"P{number:02d}"
        paper_id = f"paper-{number:02d}"
        paper = Paper(
            paper_id=paper_id,
            title=f"Paper {number:02d}",
            abstract="Abstract",
            url=f"https://example.test/{paper_id}",
        )
        screening = ScreeningItem(
            paper_id=paper_id,
            relevance_score=90,
            rationale="Relevant.",
            reading_focus="Focus.",
            category_hint="基础模型与架构",
        )
        task_specs.append((task_id, paper, screening))
        contents[paper_id] = PaperContent(
            paper_id=paper_id,
            source="abstract",
            page_count=None,
            text=(
                "First exact quotation long enough for validation. "
                "Second exact quotation long enough for validation."
            ),
        )
    return task_specs, contents


@pytest.mark.asyncio
async def test_all_32_readers_can_enter_api_stage_together(tmp_path) -> None:
    client = FakeDeepSeekClient()
    task_specs, contents = _tasks_and_contents()

    results = await _run_readers(
        client=client,  # type: ignore[arg-type]
        config=_config(tmp_path),
        run_dir=tmp_path,
        task_specs=task_specs,
        contents=contents,
        usage=[],
        progress=lambda _: None,
    )

    assert len(results) == 32
    assert client.max_active == 32
    assert client.requested_models == ["deepseek-v4-flash"] * 32


@pytest.mark.asyncio
async def test_reader_batch_returns_valid_subset_when_some_tasks_fail(tmp_path) -> None:
    client = FakeDeepSeekClient({"P17", "P32"})
    task_specs, contents = _tasks_and_contents()

    results = await _run_readers(
        client=client,  # type: ignore[arg-type]
        config=_config(tmp_path),
        run_dir=tmp_path,
        task_specs=task_specs,
        contents=contents,
        usage=[],
        progress=lambda _: None,
    )

    assert len(results) == 30
    assert {result.task_id for result in results}.isdisjoint({"P17", "P32"})
    failures = (tmp_path / "failures.json").read_text(encoding="utf-8")
    assert "P17 failed evidence/schema validation" in failures
    assert "P32 failed evidence/schema validation" in failures
