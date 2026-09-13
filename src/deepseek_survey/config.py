from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


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
    sort_by: str = "relevance"
    sort_order: str = "descending"


@dataclass(frozen=True, slots=True)
class ValidationConfig:
    minimum_grounded_evidence: int
    minimum_quote_chars: int
    max_repair_attempts: int
    minimum_results_for_synthesis: int = 28


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    protocol: str
    base_url: str
    api_key_env: str
    max_concurrency: int = 32
    requests_per_minute: int | None = None
    max_retries: int = 3
    timeout_seconds: float = 900


@dataclass(frozen=True, slots=True)
class ModelConfig:
    provider: str
    model: str
    tier: str
    thinking: str = "disabled"
    max_output_tokens: int | None = None
    max_input_tokens: int | None = None
    # Explicit provider-native settings handle model-generation differences.
    # Authentication, model selection, prompts and output caps cannot be overridden.
    request_options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RoutingConfig:
    screening: str = ""
    reader: str = ""
    reader_fallback: str | None = None
    reviewer: str | None = None


@dataclass(frozen=True, slots=True)
class ReviewConfig:
    mode: str = "external"
    name: str = "Codex"
    max_rounds: int = 2


@dataclass(frozen=True, slots=True)
class ExecutionConfig:
    reader_concurrency: int = 32
    max_requests: int = 500
    max_total_tokens: int = 2_000_000
    resume_policy: str = "reuse"


@dataclass(frozen=True, slots=True)
class AppConfig:
    project: ProjectConfig
    deepseek: DeepSeekConfig
    search: SearchConfig
    validation: ValidationConfig
    categories: tuple[str, ...]
    source_path: Path
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    models: dict[str, ModelConfig] = field(default_factory=dict)
    routing: RoutingConfig = field(default_factory=RoutingConfig)
    review: ReviewConfig = field(default_factory=ReviewConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)

    def __post_init__(self) -> None:
        # Preserve callers constructing the original six-field AppConfig.
        if not self.providers and not self.models and not self.routing.screening:
            providers, models, routing = _legacy_routing(self.deepseek)
            object.__setattr__(self, "providers", providers)
            object.__setattr__(self, "models", models)
            object.__setattr__(self, "routing", routing)
        _validate_routing(self)


def _legacy_routing(
    legacy: DeepSeekConfig,
) -> tuple[dict[str, ProviderConfig], dict[str, ModelConfig], RoutingConfig]:
    # A closed migration table: never infer price/capability from name substrings.
    tiers = {"deepseek-v4-flash": "flash", "deepseek-v4-pro": "pro"}
    models: dict[str, ModelConfig] = {}
    for model, thinking in (
        (legacy.screening_model, legacy.thinking),
        (legacy.reader_model, legacy.thinking),
        (legacy.synthesis_model, legacy.synthesis_thinking),
    ):
        if model not in tiers:
            raise ValueError(
                f"旧版 deepseek 配置无法确认模型档位: {model}; "
                "请使用 providers/models/routing 并显式声明 tier"
            )
        models[model] = ModelConfig("deepseek", model, tiers[model], thinking)
    providers = {
        "deepseek": ProviderConfig(
            protocol="deepseek",
            base_url=legacy.base_url,
            api_key_env="DEEPSEEK_API_KEY",
            max_concurrency=legacy.reader_concurrency,
            max_retries=legacy.max_retries,
            timeout_seconds=legacy.request_timeout_seconds,
        )
    }
    return providers, models, RoutingConfig(
        screening=legacy.screening_model,
        reader=legacy.reader_model,
        reviewer=legacy.synthesis_model,
    )


def _validate_routing(config: AppConfig) -> None:
    for alias, provider in config.providers.items():
        if not alias.strip():
            raise ValueError("providers 别名不能为空")
        if provider.protocol not in {"deepseek", "openai_compatible", "gemini", "anthropic"}:
            raise ValueError(f"providers.{alias}.protocol 不受支持")
        parsed = urlsplit(provider.base_url)
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(f"providers.{alias}.base_url 必须是无凭据及查询参数的 HTTP(S) 地址")
        if not provider.api_key_env.strip() or not provider.api_key_env.replace("_", "").isalnum():
            raise ValueError(f"providers.{alias}.api_key_env 必须是环境变量名")
        if (
            provider.max_concurrency < 1
            or provider.timeout_seconds <= 0
            or not math.isfinite(provider.timeout_seconds)
        ):
            raise ValueError(f"providers.{alias} 并发数和超时必须为正数")
        if provider.max_retries < 0 or (
            provider.requests_per_minute is not None and provider.requests_per_minute < 1
        ):
            raise ValueError(f"providers.{alias} 重试次数不能为负，RPM 必须为正数")
    reserved = {
        "model", "messages", "system", "systemInstruction", "contents", "max_tokens",
        "max_completion_tokens", "maxOutputTokens", "stream", "api_key", "headers",
        "base_url", "url", "response_format", "responseMimeType", "generation_config",
        "max_output_tokens", "system_instruction",
    }
    for alias, model in config.models.items():
        if not alias.strip() or not model.model.strip():
            raise ValueError("models 别名和模型名称不能为空")
        if model.provider not in config.providers:
            raise ValueError(f"models.{alias}.provider 未定义")
        if model.tier not in {"flash", "pro"}:
            raise ValueError(f"models.{alias}.tier 只能是 flash 或 pro")
        if model.thinking not in {"enabled", "disabled"}:
            raise ValueError(f"models.{alias}.thinking 只能是 enabled 或 disabled")
        for name, value in (
            ("max_output_tokens", model.max_output_tokens),
            ("max_input_tokens", model.max_input_tokens),
        ):
            if value is not None and value < 1:
                raise ValueError(f"models.{alias}.{name} 必须为正数")
        if not isinstance(model.request_options, dict) or reserved & model.request_options.keys():
            raise ValueError(f"models.{alias}.request_options 不能覆盖身份、输入或输出上限")
        generation = model.request_options.get("generationConfig", {})
        if not isinstance(generation, dict) or {
            "maxOutputTokens", "responseMimeType", "max_output_tokens", "response_mime_type",
            "candidate_count",
        } & generation.keys():
            raise ValueError(f"models.{alias}.request_options 不能覆盖 Gemini 输出格式或上限")
    for role in ("screening", "reader", "reader_fallback", "reviewer"):
        alias = getattr(config.routing, role)
        if alias is None and role in {"reader_fallback", "reviewer"}:
            continue
        if alias not in config.models:
            raise ValueError(f"routing.{role} 必须引用已定义的 models 别名")
        expected = "pro" if role == "reviewer" else "flash"
        if config.models[alias].tier != expected:
            raise ValueError(f"routing.{role} 必须使用 {expected} 档模型")
    if config.review.mode not in {"external", "api"}:
        raise ValueError("review.mode 只能是 external 或 api")
    if config.review.mode == "api" and not config.routing.reviewer:
        raise ValueError("API 审阅需要配置 routing.reviewer")
    if not config.review.name.strip() or config.review.max_rounds < 1:
        raise ValueError("review.name 不能为空，max_rounds 必须为正数")
    if not 1 <= config.execution.reader_concurrency <= 32:
        raise ValueError("execution.reader_concurrency 必须在 1..32")
    if config.execution.max_requests < 1 or config.execution.max_total_tokens < 1:
        raise ValueError("execution 请求和 token 预算必须为正数")
    if config.execution.resume_policy not in {"reuse", "strict"}:
        raise ValueError("execution.resume_policy 只能是 reuse 或 strict")


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
    limits = raw.get("limits", {})
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
        max_tokens_screening=int(
            limits.get("max_tokens_screening", deepseek.get("max_tokens_screening", 12_000))
        ),
        max_tokens_reader=int(
            limits.get("max_tokens_reader", deepseek.get("max_tokens_reader", 8_000))
        ),
        max_tokens_synthesis=int(
            limits.get("max_tokens_synthesis", deepseek.get("max_tokens_synthesis", 16_000))
        ),
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
        sort_by=str(search.get("sort_by", "relevance")),
        sort_order=str(search.get("sort_order", "descending")),
    )
    validation_config = ValidationConfig(
        minimum_grounded_evidence=int(validation.get("minimum_grounded_evidence", 2)),
        minimum_quote_chars=int(validation.get("minimum_quote_chars", 20)),
        max_repair_attempts=int(validation.get("max_repair_attempts", 1)),
        minimum_results_for_synthesis=int(
            validation.get("minimum_results_for_synthesis", 28)
        ),
    )

    review_raw = raw.get("review", {})
    review_config = ReviewConfig(
        mode=str(review_raw.get("mode", "external")),
        name=str(review_raw.get("name", "Codex")),
        max_rounds=int(review_raw.get("max_rounds", 2)),
    )
    execution_raw = raw.get("execution", {})
    execution_config = ExecutionConfig(
        reader_concurrency=int(
            execution_raw.get("reader_concurrency", deepseek_config.reader_concurrency)
        ),
        max_requests=int(execution_raw.get("max_requests", 500)),
        max_total_tokens=int(execution_raw.get("max_total_tokens", 2_000_000)),
        resume_policy=str(execution_raw.get("resume_policy", "reuse")),
    )
    providers: dict[str, ProviderConfig] = {}
    models: dict[str, ModelConfig] = {}
    routing_config = RoutingConfig()
    if any(name in raw for name in ("providers", "models", "routing")):
        for alias, entry in raw.get("providers", {}).items():
            providers[alias] = ProviderConfig(
                protocol=str(_require(entry, "protocol")),
                base_url=str(_require(entry, "base_url")).rstrip("/"),
                api_key_env=str(_require(entry, "api_key_env")),
                max_concurrency=int(entry.get("max_concurrency", 32)),
                requests_per_minute=(
                    int(entry["requests_per_minute"]) if "requests_per_minute" in entry else None
                ),
                max_retries=int(entry.get("max_retries", 3)),
                timeout_seconds=float(entry.get("timeout_seconds", 900)),
            )
        for alias, entry in raw.get("models", {}).items():
            models[alias] = ModelConfig(
                provider=str(_require(entry, "provider")),
                model=str(_require(entry, "model")),
                tier=str(_require(entry, "tier")),
                thinking=str(entry.get("thinking", "disabled")),
                max_output_tokens=(
                    int(entry["max_output_tokens"]) if "max_output_tokens" in entry else None
                ),
                max_input_tokens=(
                    int(entry["max_input_tokens"]) if "max_input_tokens" in entry else None
                ),
                request_options=entry.get("request_options", {}),
            )
        routing_raw = raw.get("routing", {})
        routing_config = RoutingConfig(
            screening=str(_require(routing_raw, "screening")),
            reader=str(_require(routing_raw, "reader")),
            reader_fallback=routing_raw.get("reader_fallback"),
            reviewer=routing_raw.get("reviewer"),
        )
        if not providers or not models:
            raise ValueError("providers、models 和 routing 必须一起配置")
        # Keep old pipeline-facing fields as aliases during migration.
        reader = models.get(routing_config.reader)
        reviewer = models.get(routing_config.reviewer or "")
        provider = providers.get(reader.provider) if reader else None
        deepseek_config = replace(
            deepseek_config,
            base_url=provider.base_url if provider else deepseek_config.base_url,
            screening_model=routing_config.screening,
            reader_model=routing_config.reader,
            synthesis_model=routing_config.reviewer or "",
            thinking=reader.thinking if reader else "disabled",
            synthesis_thinking=reviewer.thinking if reviewer else "disabled",
            reader_concurrency=execution_config.reader_concurrency,
            request_timeout_seconds=(
                provider.timeout_seconds if provider else deepseek_config.request_timeout_seconds
            ),
            max_retries=provider.max_retries if provider else deepseek_config.max_retries,
        )

    if not 1 <= project_config.target_papers <= 32:
        raise ValueError("project.target_papers 必须在 1..32 范围内")
    if search_config.sort_by not in {"relevance", "submittedDate", "lastUpdatedDate"}:
        raise ValueError("search.sort_by 不受支持")
    if search_config.sort_order not in {"ascending", "descending"}:
        raise ValueError("search.sort_order 不受支持")
    if not 1 <= deepseek_config.reader_concurrency <= 32:
        raise ValueError("deepseek.reader_concurrency 必须在 1..32；设为 32 才会满并发运行")
    if not categories:
        raise ValueError("taxonomy.categories 不能为空")
    if min(
        deepseek_config.max_tokens_screening,
        deepseek_config.max_tokens_reader,
        deepseek_config.max_tokens_synthesis,
    ) < 1:
        raise ValueError("limits 各阶段输出 token 上限必须为正数")
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
        providers=providers,
        models=models,
        routing=routing_config,
        review=review_config,
        execution=execution_config,
    )
