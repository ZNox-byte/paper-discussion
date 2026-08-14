from __future__ import annotations

from typing import Any


def sanitize_unicode(value: str) -> str:
    """Replace lone UTF-16 surrogate code points while preserving valid Unicode."""
    return value.encode("utf-8", errors="replace").decode("utf-8")


def sanitize_json_strings(value: Any) -> Any:
    """Recursively make all JSON string values safe for UTF-8 transport and storage."""
    if isinstance(value, str):
        return sanitize_unicode(value)
    if isinstance(value, list):
        return [sanitize_json_strings(item) for item in value]
    if isinstance(value, dict):
        return {
            sanitize_unicode(key) if isinstance(key, str) else key: sanitize_json_strings(item)
            for key, item in value.items()
        }
    return value

