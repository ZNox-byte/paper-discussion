"""Fingerprints keep cached reading cards tied to their real inputs and producer."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from .config import AppConfig


def fingerprint(value: Any) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def model_identity(config: AppConfig, alias: str) -> dict[str, Any]:
    models = getattr(config, "models", {})
    if alias in models:
        model = models[alias]
        provider = config.providers[model.provider]
        return {
            "alias": alias,
            **asdict(model),
            "protocol": provider.protocol,
            "base_url": provider.base_url,
        }
    return {"alias": alias, "model": alias, "provider": "deepseek",
            "base_url": config.deepseek.base_url}


def reader_alias(config: AppConfig) -> str:
    routing = getattr(config, "routing", None)
    return routing.reader if routing else config.deepseek.reader_model


def screening_alias(config: AppConfig) -> str:
    routing = getattr(config, "routing", None)
    return routing.screening if routing else config.deepseek.screening_model


def reviewer_alias(config: AppConfig) -> str:
    routing = getattr(config, "routing", None)
    return (routing.reviewer if routing else None) or config.deepseek.synthesis_model


def reader_identity(config: AppConfig) -> dict[str, Any]:
    routing = getattr(config, "routing", None)
    fallback = routing.reader_fallback if routing else None
    return {
        "primary": model_identity(config, reader_alias(config)),
        "fallback": model_identity(config, fallback) if fallback else None,
        "max_tokens_reader": config.deepseek.max_tokens_reader,
    }
