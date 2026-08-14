from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    title: str
    research_question: str
    language: str
    target_papers: int
    output_dir: Path
    max_paper_chars: int


@dataclass(frozen=True, slots=True)
class DeepSeekConfig:
    base_url: str
    screening_model: str
    reader_model: str
    synthesis_model: str
    thinking: str
    reader_concurrency: int
    max_tokens_screening: int
    max_tokens_reader: int
    max_tokens_synthesis: int
    request_timeout_seconds: float
    max_retries: int
    synthesis_thinking: str = "disabled"


@dataclass(frozen=True, slots=True)
class SearchConfig:
    endpoint: str
    max_results_per_query: int
    download_concurrency: int
    request_timeout_seconds: float
    queries: tuple[str, ...]
    max_retries: int = 3
    request_delay_seconds: float = 3.0


@dataclass(frozen=True, slots=True)
class ValidationConfig:
    minimum_grounded_evidence: int
    minimum_quote_chars: int
    max_repair_attempts: int
    minimum_results_for_synthesis: int = 28


@dataclass(frozen=True, slots=True)
class AppConfig:
    project: ProjectConfig
    deepseek: DeepSeekConfig
    search: SearchConfig
    validation: ValidationConfig
    categories: tuple[str, ...]
    source_path: Path


def _require(section: dict[str, Any], key: str) -> Any:
    if key not in section:
        raise ValueError(f"配置缺少字段: {key}")
    return section[key]


def load_config(path: str | Path) -> AppConfig:
    source_path = Path(path).resolve()
    with source_path.open("rb") as handle:
        raw = tomllib.load(handle)

    project = raw.get("project", {})
    deepseek = raw.get("deepseek", {})
    search = raw.get("search", {})
    validation = raw.get("validation", {})
    categories = tuple(raw.get("taxonomy", {}).get("categories", ()))

    project_config = ProjectConfig(
        title=str(_require(project, "title")),
        research_question=str(_require(project, "research_question")),
        language=str(project.get("language", "zh-CN")),
        target_papers=int(project.get("target_papers", 32)),
        output_dir=(source_path.parent / str(project.get("output_dir", "runs"))).resolve(),
        max_paper_chars=int(project.get("max_paper_chars", 180_000)),
    )
    deepseek_config = DeepSeekConfig(
        base_url=str(deepseek.get("base_url", "https://api.deepseek.com")).rstrip("/"),
        screening_model=str(deepseek.get("screening_model", "deepseek-v4-flash")),
        reader_model=str(deepseek.get("reader_model", "deepseek-v4-flash")),
        synthesis_model=str(deepseek.get("synthesis_model", "deepseek-v4-pro")),
        thinking=str(deepseek.get("thinking", "enabled")),
        reader_concurrency=int(deepseek.get("reader_concurrency", 32)),
        max_tokens_screening=int(deepseek.get("max_tokens_screening", 12_000)),
        max_tokens_reader=int(deepseek.get("max_tokens_reader", 8_000)),
        max_tokens_synthesis=int(deepseek.get("max_tokens_synthesis", 16_000)),
        request_timeout_seconds=float(deepseek.get("request_timeout_seconds", 900)),
        max_retries=int(deepseek.get("max_retries", 5)),
        synthesis_thinking=str(deepseek.get("synthesis_thinking", "disabled")),
    )
    search_config = SearchConfig(
        endpoint=str(search.get("endpoint", "https://export.arxiv.org/api/query")),
        max_results_per_query=int(search.get("max_results_per_query", 50)),
        download_concurrency=int(search.get("download_concurrency", 8)),
        request_timeout_seconds=float(search.get("request_timeout_seconds", 90)),
        queries=tuple(search.get("queries", ("all:vLLM",))),
        max_retries=int(search.get("max_retries", 3)),
        request_delay_seconds=float(search.get("request_delay_seconds", 3)),
    )
    validation_config = ValidationConfig(
        minimum_grounded_evidence=int(validation.get("minimum_grounded_evidence", 2)),
        minimum_quote_chars=int(validation.get("minimum_quote_chars", 20)),
        max_repair_attempts=int(validation.get("max_repair_attempts", 1)),
        minimum_results_for_synthesis=int(
            validation.get("minimum_results_for_synthesis", 28)
        ),
    )

    if project_config.target_papers != 32:
        raise ValueError("本项目固定调度 32 个阅读任务，请将 project.target_papers 设为 32")
    if not 1 <= deepseek_config.reader_concurrency <= 32:
        raise ValueError("deepseek.reader_concurrency 必须在 1..32；设为 32 才会满并发运行")
    if not categories:
        raise ValueError("taxonomy.categories 不能为空")
    if not 1 <= validation_config.minimum_results_for_synthesis <= project_config.target_papers:
        raise ValueError(
            "validation.minimum_results_for_synthesis 必须在 1..target_papers 范围内"
        )
    if deepseek_config.thinking not in {"enabled", "disabled"}:
        raise ValueError("deepseek.thinking 只能是 enabled 或 disabled")
    if deepseek_config.synthesis_thinking not in {"enabled", "disabled"}:
        raise ValueError("deepseek.synthesis_thinking 只能是 enabled 或 disabled")
    for field_name, model in (
        ("screening_model", deepseek_config.screening_model),
        ("reader_model", deepseek_config.reader_model),
        ("synthesis_model", deepseek_config.synthesis_model),
    ):
        if not model.strip():
            raise ValueError(f"deepseek.{field_name} 不能为空")

    return AppConfig(
        project=project_config,
        deepseek=deepseek_config,
        search=search_config,
        validation=validation_config,
        categories=categories,
        source_path=source_path,
    )
