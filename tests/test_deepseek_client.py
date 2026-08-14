import json

import httpx
import pytest

from deepseek_survey.config import DeepSeekConfig
from deepseek_survey.deepseek import DeepSeekClient


@pytest.mark.asyncio
async def test_official_chat_payload_uses_json_output_and_thinking() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "request-1",
                "model": "deepseek-v4-pro",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"answer":"ok"}'},
                    }
                ],
                "usage": {"total_tokens": 10},
            },
        )

    config = DeepSeekConfig(
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
    )
    client = DeepSeekClient(config, "test-key")
    await client._client.aclose()
    client._client = httpx.AsyncClient(
        base_url=config.base_url,
        transport=httpx.MockTransport(handler),
    )
    try:
        body, metadata = await client.complete_json(
            system="Return JSON.",
            user="Test",
            max_tokens=100,
            model=config.reader_model,
        )
    finally:
        await client._client.aclose()

    assert body == {"answer": "ok"}
    assert metadata["request_id"] == "request-1"
    assert captured["model"] == "deepseek-v4-flash"
    assert metadata["requested_model"] == "deepseek-v4-flash"
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["thinking"] == {"type": "enabled"}
    assert captured["stream"] is False
