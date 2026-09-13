"""Role routing and bounded, provider-native JSON requests.

Model tiers are explicit configuration, never inferred from model names. This client
does not choose fallback models: validation and fallback belong to the reading task.
Only DeepSeek has a universal thinking switch. Other protocols use request_options
for generation-specific thinking controls; their defaults are recorded honestly.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import random
import time
from collections import deque
from typing import Any, Self
from urllib.parse import quote

import httpx

from .config import AppConfig, ModelConfig, ProviderConfig
from .deepseek import DeepSeekAPIError
from .text import sanitize_json_strings, sanitize_unicode


class ProviderAPIError(DeepSeekAPIError):
    """A sanitized failure; never includes response bodies or credentials."""


class BudgetExceededError(ProviderAPIError):
    pass


class InputTooLargeError(ProviderAPIError):
    pass


class _ResponseError(Exception):
    def __init__(self, code: str, *, retryable: bool = True) -> None:
        self.code = code
        self.retryable = retryable


class _ProviderGate:
    def __init__(self, config: ProviderConfig) -> None:
        self.semaphore = asyncio.Semaphore(config.max_concurrency)
        self.rpm = config.requests_per_minute
        self.starts: deque[float] = deque()
        self.rate_lock = asyncio.Lock()

    async def wait_rate(self) -> None:
        if self.rpm is None:
            return
        while True:
            async with self.rate_lock:
                now = time.monotonic()
                while self.starts and now - self.starts[0] >= 60:
                    self.starts.popleft()
                if len(self.starts) < self.rpm:
                    self.starts.append(now)
                    return
                delay = max(0.001, 60 - (now - self.starts[0]))
            await asyncio.sleep(delay)


class RoutedClient:
    def __init__(
        self,
        config: AppConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self.events: list[dict[str, Any]] = []
        self._clients: dict[str, httpx.AsyncClient] = {}
        self._gates = {name: _ProviderGate(value) for name, value in config.providers.items()}
        self._transport = transport
        self._budget_condition = asyncio.Condition()
        self._request_count = 0
        self._charged_tokens = 0
        self._unknown_usage_requests = 0
        self._reported_tokens = 0
        self._in_flight = 0
        self._budget_restored = False

    async def __aenter__(self) -> Self:
        missing = self.check_keys()
        if missing:
            raise ValueError("缺少 API 密钥环境变量: " + ", ".join(missing))
        return self

    async def __aexit__(self, *_: object) -> None:
        await asyncio.gather(*(client.aclose() for client in self._clients.values()))

    def check_keys(self) -> list[str]:
        """Return missing env *names* for all active routes, including fallback."""
        aliases = {
            self.config.routing.screening,
            self.config.routing.reader,
            self.config.routing.reader_fallback,
        }
        if self.config.review.mode == "api":
            aliases.add(self.config.routing.reviewer)
        required = {
            self.config.providers[self.config.models[alias].provider].api_key_env
            for alias in aliases
            if alias
        }
        return sorted(name for name in required if not os.environ.get(name, "").strip())

    def model_identity(self, alias: str) -> dict[str, Any]:
        model = self._resolve(alias)
        provider = self.config.providers[model.provider]
        return {
            "alias": alias,
            "provider": model.provider,
            "protocol": provider.protocol,
            "base_url": provider.base_url,
            "model": model.model,
            "tier": model.tier,
            "thinking": model.thinking,
            "max_output_tokens": model.max_output_tokens,
            "max_input_tokens": model.max_input_tokens,
            "request_options": copy.deepcopy(model.request_options),
        }

    @property
    def budget_status(self) -> dict[str, Any]:
        return {
            "requests": self._request_count,
            "max_requests": self.config.execution.max_requests,
            "reported_tokens": self._reported_tokens,
            "charged_tokens": self._charged_tokens,
            "max_total_tokens": self.config.execution.max_total_tokens,
            "unknown_usage_requests": self._unknown_usage_requests,
            "in_flight_requests": self._in_flight,
            "accounting": "reported usage or conservative input bytes + output reservation",
        }

    def restore_budget(self, snapshot: dict[str, Any]) -> None:
        """Restore settled accounting once, before starting a resumed run's requests.

        Current configuration supplies the limits. Prior unknown usage remains charged;
        changing a model or restarting the process does not erase spent tokens.
        """
        if self._budget_restored or self._request_count or self._in_flight or self.events:
            raise ValueError("预算只能在本客户端首次请求之前恢复一次")
        if not isinstance(snapshot, dict):
            raise TypeError("预算快照必须是对象")
        required = ("requests", "charged_tokens", "reported_tokens", "unknown_usage_requests")
        if any(_number(snapshot.get(name)) is None for name in required):
            raise ValueError("预算快照计数必须是非负整数")
        if _number(snapshot.get("in_flight_requests", 0)) != 0:
            raise ValueError("不能恢复包含未结算请求的预算快照")
        if (
            snapshot["reported_tokens"] > snapshot["charged_tokens"]
            or snapshot["unknown_usage_requests"] > snapshot["requests"]
            or (not snapshot["requests"] and snapshot["charged_tokens"])
        ):
            raise ValueError("预算快照计数不一致")
        self._request_count = snapshot["requests"]
        self._charged_tokens = snapshot["charged_tokens"]
        self._reported_tokens = snapshot["reported_tokens"]
        self._unknown_usage_requests = snapshot["unknown_usage_requests"]
        self._budget_restored = True

    def _resolve(self, alias: str) -> ModelConfig:
        try:
            return self.config.models[alias]
        except KeyError:
            raise ValueError(f"模型别名未配置: {alias}") from None

    def _http_client(self, name: str) -> httpx.AsyncClient:
        if name not in self._clients:
            provider = self.config.providers[name]
            key = os.environ.get(provider.api_key_env, "").strip()
            if not key:
                raise ValueError(f"缺少 API 密钥环境变量: {provider.api_key_env}")
            headers = {"Content-Type": "application/json"}
            if provider.protocol == "gemini":
                headers["x-goog-api-key"] = key
            elif provider.protocol == "anthropic":
                headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
            else:
                headers["Authorization"] = f"Bearer {key}"
            self._clients[name] = httpx.AsyncClient(
                base_url=provider.base_url.rstrip("/") + "/",
                headers=headers,
                timeout=httpx.Timeout(provider.timeout_seconds),
                transport=self._transport,
            )
        return self._clients[name]

    async def _reserve(self, tokens: int) -> int:
        async with self._budget_condition:
            execution = self.config.execution
            while True:
                if self._request_count >= execution.max_requests:
                    raise BudgetExceededError("已达到 execution.max_requests，请求未发送")
                if self._charged_tokens + tokens <= execution.max_total_tokens:
                    break
                if not self._in_flight or tokens > execution.max_total_tokens:
                    raise BudgetExceededError("剩余 token 预算不足以预留本次请求，请求未发送")
                # Concurrent reservations can exceed actual usage substantially.
                # Wait for settlement instead of failing otherwise affordable work.
                await self._budget_condition.wait()
            self._request_count += 1
            self._charged_tokens += tokens
            self._unknown_usage_requests += 1
            self._in_flight += 1
            return self._request_count

    async def _settle(self, reserved: int, usage: dict[str, int]) -> int:
        total = usage.get("total_tokens")
        async with self._budget_condition:
            if total is not None:
                self._charged_tokens += total - reserved
                self._reported_tokens += total
                self._unknown_usage_requests -= 1
            self._in_flight -= 1
            self._budget_condition.notify_all()
        return total if total is not None else reserved

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int,
        model: str,
        thinking: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        configured = self._resolve(model)
        provider = self.config.providers[configured.provider]
        thinking_mode = thinking or configured.thinking
        if thinking_mode not in {"enabled", "disabled"}:
            raise ValueError("thinking must be enabled or disabled")
        if max_tokens < 1:
            raise ValueError("max_tokens must be positive")
        cap = min(max_tokens, configured.max_output_tokens or max_tokens)
        system = sanitize_unicode(system) + "\nReturn one JSON object only, without Markdown fences."
        user = sanitize_unicode(user)
        path, payload, control = _request(
            provider.protocol, configured, system, user, cap, thinking_mode
        )
        # This is deliberately labelled a conservative estimate, not a tokenizer.
        # Include native options/tool schemas as well as the prompts. Counting JSON
        # keys over-reserves most inputs; 256 additionally covers protocol framing.
        estimated_input = len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) + 256
        if configured.max_input_tokens is not None and estimated_input > configured.max_input_tokens:
            raise InputTooLargeError(
                "输入的保守 token 估计超过模型 max_input_tokens，请分段阅读；请求未发送"
            )
        http_client = self._http_client(configured.provider)
        gate = self._gates[configured.provider]
        last_code = "request_failed"
        for attempt in range(1, provider.max_retries + 2):
            usage: dict[str, int] = {}
            status_code: int | None = None
            event: dict[str, Any] | None = None
            retryable = True
            async with gate.semaphore:
                reserved = estimated_input + cap
                request_number = await self._reserve(reserved)
                event = {
                    "provider": configured.provider,
                    "protocol": provider.protocol,
                    "alias": model,
                    "requested_model": model,
                    "model": configured.model,
                    "tier": configured.tier,
                    "thinking": thinking_mode,
                    "thinking_control": control,
                    "attempt": attempt,
                    "request_number": request_number,
                    "estimated_input_tokens": estimated_input,
                    "input_estimate_method": "utf8_payload_bytes_plus_256",
                    "max_output_tokens": cap,
                    "status": "failed",
                }
                sent = False
                try:
                    # Rate windows must be acquired after any budget-capacity wait.
                    await gate.wait_rate()
                    sent = True
                    response = await http_client.post(path, json=payload)
                    status_code = response.status_code
                    if status_code >= 400:
                        raise _ResponseError(
                            f"http_{status_code}",
                            retryable=status_code in {408, 409, 429, 500, 502, 503, 504, 529},
                        )
                    envelope = response.json()
                    if not isinstance(envelope, dict):
                        raise _ResponseError("invalid_response_envelope")
                    usage = _usage(provider.protocol, envelope)
                    content, response_meta = _response(provider.protocol, envelope)
                    parsed = sanitize_json_strings(json.loads(content))
                    if not isinstance(parsed, dict):
                        raise _ResponseError("json_root_not_object")
                    event.update(response_meta)
                    event["status"] = "success"
                except _ResponseError as exc:
                    last_code = exc.code
                    retryable = exc.retryable
                except httpx.RequestError:
                    last_code = "transport_error"
                except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                    last_code = "invalid_json_response"
                except asyncio.CancelledError:
                    last_code = "cancelled"
                    event["error_type"] = last_code
                    raise
                finally:
                    if not sent:
                        usage = {"total_tokens": 0}
                    charged = await self._settle(reserved, usage)
                    event.update({
                        "request_sent": sent,
                        "http_status": status_code,
                        "usage": usage,
                        "usage_known": "total_tokens" in usage,
                        "budget_counted_tokens": charged,
                    })
                    if event["status"] != "success":
                        event["error_type"] = last_code
                    self.events.append(event)
            if event["status"] == "success":
                return parsed, dict(event)
            if not retryable or attempt > provider.max_retries:
                break
            await asyncio.sleep(min(30.0, 2 ** (attempt - 1) + random.random()))
        raise ProviderAPIError(
            f"模型请求失败: provider={configured.provider}, alias={model}, "
            f"attempts={attempt}, reason={last_code}"
        ) from None


def _request(
    protocol: str,
    model: ModelConfig,
    system: str,
    user: str,
    cap: int,
    thinking: str,
) -> tuple[str, dict[str, Any], Any]:
    options = copy.deepcopy(model.request_options)
    # Multiple candidates multiply output costs but are not used by this workflow.
    if options.get("n", 1) != 1:
        raise ValueError("request_options.n 必须为 1")
    control: Any = "provider_default"
    if protocol in {"deepseek", "openai_compatible"}:
        payload = {
            "model": model.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": cap,
            "stream": False,
        }
        if protocol == "deepseek":
            payload["thinking"] = {"type": thinking}
        payload.update(options)
        if "thinking" in payload:
            control = payload["thinking"]
        elif "reasoning_effort" in payload:
            control = {"reasoning_effort": payload["reasoning_effort"]}
        return "chat/completions", payload, control
    if protocol == "gemini":
        generation = options.pop("generationConfig", {})
        if generation.get("candidateCount", 1) != 1:
            raise ValueError("request_options.generationConfig.candidateCount 必须为 1")
        generation.update({"maxOutputTokens": cap, "responseMimeType": "application/json"})
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": generation,
            **options,
        }
        control = generation.get("thinkingConfig", "provider_default")
        native_name = model.model.removeprefix("models/")
        return f"models/{quote(native_name, safe='')}:generateContent", payload, control
    if protocol == "anthropic":
        payload = {
            "model": model.model,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "max_tokens": cap,
            "stream": False,
            **options,
        }
        control = payload.get("thinking", "provider_default")
        return "messages", payload, control
    raise ValueError("unsupported protocol")


def _number(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _usage(protocol: str, envelope: dict[str, Any]) -> dict[str, int]:
    raw = envelope.get("usageMetadata" if protocol == "gemini" else "usage")
    if not isinstance(raw, dict):
        return {}
    result: dict[str, int] = {}
    names = {
        "prompt_tokens": "prompt_tokens",
        "completion_tokens": "completion_tokens",
        "total_tokens": "total_tokens",
        "prompt_cache_hit_tokens": "prompt_cache_hit_tokens",
        "prompt_cache_miss_tokens": "prompt_cache_miss_tokens",
    }
    if protocol == "gemini":
        names = {
            "promptTokenCount": "prompt_tokens",
            "candidatesTokenCount": "completion_tokens",
            "totalTokenCount": "total_tokens",
            "thoughtsTokenCount": "reasoning_tokens",
            "cachedContentTokenCount": "cached_tokens",
            "toolUsePromptTokenCount": "tool_prompt_tokens",
        }
    elif protocol == "anthropic":
        names = {
            "input_tokens": "prompt_tokens",
            "output_tokens": "completion_tokens",
            "cache_creation_input_tokens": "cache_creation_input_tokens",
            "cache_read_input_tokens": "cache_read_input_tokens",
        }
    for source, destination in names.items():
        value = _number(raw.get(source))
        if value is not None:
            result[destination] = value
    if "total_tokens" not in result and {"prompt_tokens", "completion_tokens"} <= result.keys():
        result["total_tokens"] = result["prompt_tokens"] + result["completion_tokens"]
        if protocol == "anthropic":
            result["total_tokens"] += result.get("cache_creation_input_tokens", 0)
            result["total_tokens"] += result.get("cache_read_input_tokens", 0)
        elif protocol == "gemini":
            result["total_tokens"] += result.get("reasoning_tokens", 0)
            result["total_tokens"] += result.get("tool_prompt_tokens", 0)
    return result


def _response(protocol: str, envelope: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if protocol in {"deepseek", "openai_compatible"}:
        choice = envelope["choices"][0]
        finish = choice.get("finish_reason")
        if finish == "length":
            raise _ResponseError("output_truncated")
        if finish in {"content_filter", "tool_calls", "function_call"}:
            raise _ResponseError("response_not_text", retryable=False)
        content = choice["message"].get("content")
        response_id, response_model = envelope.get("id"), envelope.get("model")
    elif protocol == "gemini":
        candidate = envelope["candidates"][0]
        finish = candidate.get("finishReason")
        if finish == "MAX_TOKENS":
            raise _ResponseError("output_truncated")
        if finish not in {None, "STOP"}:
            raise _ResponseError("response_not_text", retryable=False)
        content = "".join(
            part.get("text", "")
            for part in candidate["content"]["parts"]
            if not part.get("thought")
        )
        response_id, response_model = envelope.get("responseId"), envelope.get("modelVersion")
    else:
        finish = envelope.get("stop_reason")
        if finish == "max_tokens":
            raise _ResponseError("output_truncated")
        if finish in {"refusal", "tool_use", "pause_turn"}:
            raise _ResponseError("response_not_text", retryable=False)
        content = "".join(
            block.get("text", "") for block in envelope["content"] if block.get("type") == "text"
        )
        response_id, response_model = envelope.get("id"), envelope.get("model")
    if not isinstance(content, str) or not content.strip():
        raise _ResponseError("empty_json_content")
    return content, {
        "request_id": response_id,
        "response_model": response_model,
        "finish_reason": finish,
    }
