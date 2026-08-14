from __future__ import annotations

import asyncio
import json
import random
from typing import Any, Self

import httpx

from .config import DeepSeekConfig
from .text import sanitize_json_strings, sanitize_unicode


class DeepSeekAPIError(RuntimeError):
    pass


class DeepSeekClient:
    def __init__(self, config: DeepSeekConfig, api_key: str) -> None:
        if not api_key.strip():
            raise ValueError("DEEPSEEK_API_KEY 未设置")
        self.config = config
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(config.request_timeout_seconds),
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._client.aclose()

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int,
        model: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": sanitize_unicode(system)},
                {"role": "user", "content": sanitize_unicode(user)},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": max_tokens,
            "stream": False,
            "thinking": {"type": self.config.thinking},
        }
        retryable = {429, 500, 503}
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                response = await self._client.post("/chat/completions", json=payload)
                if response.status_code in retryable:
                    raise DeepSeekAPIError(
                        f"DeepSeek temporary error {response.status_code}: {response.text[:300]}"
                    )
                response.raise_for_status()
                envelope = response.json()
                choice = envelope["choices"][0]
                finish_reason = choice.get("finish_reason")
                if finish_reason == "length":
                    raise DeepSeekAPIError("DeepSeek output was truncated (finish_reason=length)")
                content = choice["message"].get("content")
                if not content or not content.strip():
                    raise DeepSeekAPIError("DeepSeek returned empty JSON content")
                parsed = sanitize_json_strings(json.loads(content))
                if not isinstance(parsed, dict):
                    raise DeepSeekAPIError("DeepSeek JSON root must be an object")
                metadata = {
                    "request_id": envelope.get("id"),
                    "requested_model": model,
                    "model": envelope.get("model"),
                    "finish_reason": finish_reason,
                    "usage": envelope.get("usage", {}),
                }
                return parsed, metadata
            except (
                httpx.TimeoutException,
                httpx.NetworkError,
                json.JSONDecodeError,
                KeyError,
                IndexError,
                DeepSeekAPIError,
            ) as exc:
                last_error = exc
                if attempt >= self.config.max_retries:
                    break
                delay = min(30.0, (2**attempt) + random.random())
                await asyncio.sleep(delay)
            except httpx.HTTPStatusError as exc:
                raise DeepSeekAPIError(
                    f"DeepSeek request failed with {exc.response.status_code}: "
                    f"{exc.response.text[:500]}"
                ) from exc
        raise DeepSeekAPIError(
            f"DeepSeek request failed after {self.config.max_retries + 1} attempts: {last_error}"
        )
