from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from deepseek_survey.config import (
    ExecutionConfig,
    ModelConfig,
    ProviderConfig,
    ReviewConfig,
    RoutingConfig,
    load_config,
)
from deepseek_survey.providers import (
    BudgetExceededError,
    InputTooLargeError,
    ProviderAPIError,
    RoutedClient,
)


def config_for(protocol="deepseek", **provider_options):
    return replace(
        load_config("config.toml"),
        providers={
            "worker": ProviderConfig(
                protocol, "https://provider.test/v1", "TEST_WORKER_KEY",
                max_retries=0, **provider_options,
            ),
            "review": ProviderConfig("anthropic", "https://review.test/v1", "TEST_REVIEW_KEY"),
        },
        models={
            "fast": ModelConfig("worker", "provider-native-name", "flash", thinking="enabled"),
            "upper": ModelConfig("review", "native-review-name", "pro"),
        },
        routing=RoutingConfig(screening="fast", reader="fast", reviewer="upper"),
        review=ReviewConfig(mode="external"),
    )


def chat_response(content='{"answer": 42}', usage=None):
    return {
        "id": "request-1",
        "model": "provider-native-name-version",
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": usage if usage is not None else {"prompt_tokens": 10, "completion_tokens": 5},
    }


async def complete(client, **kwargs):
    return await client.complete_json(system="JSON system", user="JSON user", max_tokens=100,
                                      model="fast", **kwargs)


@pytest.mark.parametrize("protocol", ["deepseek", "openai_compatible", "gemini", "anthropic"])
async def test_native_protocols_preserve_prefix_auth_and_json(protocol, monkeypatch):
    monkeypatch.setenv("TEST_WORKER_KEY", "test-secret")
    captured = []

    def handler(request):
        captured.append(request)
        if protocol == "gemini":
            envelope = {
                "responseId": "gemini-1", "modelVersion": "version-1",
                "candidates": [{"finishReason": "STOP", "content": {"parts": [
                    {"thought": True, "text": "private reasoning is not JSON"},
                    {"text": '{"answer": 42}'},
                ]}}],
                "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5,
                                  "thoughtsTokenCount": 3, "totalTokenCount": 18},
            }
        elif protocol == "anthropic":
            envelope = {
                "id": "claude-1", "model": "version-1", "stop_reason": "end_turn",
                "content": [{"type": "thinking", "thinking": "private"},
                            {"type": "text", "text": '{"answer": 42}'}],
                "usage": {"input_tokens": 10, "output_tokens": 5,
                          "cache_read_input_tokens": 3},
            }
        else:
            envelope = chat_response()
        return httpx.Response(200, json=envelope)

    async with RoutedClient(config_for(protocol), transport=httpx.MockTransport(handler)) as client:
        parsed, meta = await complete(client)
    assert parsed == {"answer": 42}
    assert meta["provider"] == "worker"
    assert meta["alias"] == "fast"
    assert meta["model"] == "provider-native-name"
    assert meta["usage_known"]
    assert meta["attempt"] == 1
    request = captured[0]
    payload = json.loads(request.content)
    assert str(request.url).startswith("https://provider.test/v1/")
    assert "test-secret" not in str(request.url)
    if protocol == "gemini":
        assert request.url.path == "/v1/models/provider-native-name:generateContent"
        assert request.headers["x-goog-api-key"] == "test-secret"
        assert payload["generationConfig"] == {
            "maxOutputTokens": 100, "responseMimeType": "application/json",
        }
        assert payload["systemInstruction"]["parts"][0]["text"].startswith("JSON system")
        assert meta["usage"]["total_tokens"] == 18
    elif protocol == "anthropic":
        assert request.url.path == "/v1/messages"
        assert request.headers["x-api-key"] == "test-secret"
        assert request.headers["anthropic-version"] == "2023-06-01"
        assert payload["max_tokens"] == 100
        assert "thinking" not in payload
        assert meta["usage"]["total_tokens"] == 18
    else:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-secret"
        assert payload["response_format"] == {"type": "json_object"}
        assert payload["model"] == "provider-native-name"
        if protocol == "deepseek":
            assert payload["thinking"] == {"type": "enabled"}
        else:
            assert "thinking" not in payload
            assert "reasoning_effort" not in payload
            assert meta["thinking_control"] == "provider_default"


async def test_model_options_and_output_caps_override_legacy_stage_settings(monkeypatch):
    monkeypatch.setenv("TEST_WORKER_KEY", "secret")
    config = config_for("anthropic")
    config = replace(config, models={**config.models, "fast": replace(
        config.models["fast"], max_output_tokens=50,
        request_options={"thinking": {"type": "adaptive"}},
    )})
    captured = []

    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"content": [{"type": "text", "text": "{}"}],
                                         "stop_reason": "end_turn"})

    async with RoutedClient(config, transport=httpx.MockTransport(handler)) as client:
        _, meta = await complete(client, thinking="disabled")
    assert captured[0]["max_tokens"] == 50
    assert captured[0]["thinking"] == {"type": "adaptive"}
    assert meta["thinking_control"] == {"type": "adaptive"}


def test_missing_keys_checks_only_active_routes_and_includes_fallback(monkeypatch):
    monkeypatch.delenv("TEST_WORKER_KEY", raising=False)
    monkeypatch.delenv("TEST_REVIEW_KEY", raising=False)
    config = config_for()
    assert RoutedClient(config).check_keys() == ["TEST_WORKER_KEY"]
    monkeypatch.setenv("TEST_WORKER_KEY", "secret")
    assert RoutedClient(config).check_keys() == []
    assert RoutedClient(replace(config, review=ReviewConfig(mode="api"))).check_keys() == [
        "TEST_REVIEW_KEY"
    ]
    config = replace(
        config,
        models={**config.models, "backup": ModelConfig("review", "another-fast", "flash")},
        routing=replace(config.routing, reader_fallback="backup"),
    )
    assert RoutedClient(config).check_keys() == ["TEST_REVIEW_KEY"]


async def test_retry_records_failed_usage_without_leaking_body_or_keys(monkeypatch):
    monkeypatch.setenv("TEST_WORKER_KEY", "private-key")
    config = config_for()
    config = replace(config, providers={**config.providers, "worker": replace(
        config.providers["worker"], max_retries=2,
    )})
    calls = 0

    async def no_sleep(_):
        pass

    monkeypatch.setattr("deepseek_survey.providers.asyncio.sleep", no_sleep)

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, text="private-key confidential body")
        if calls == 2:
            return httpx.Response(200, json=chat_response("not JSON", {"total_tokens": 25}))
        return httpx.Response(200, json=chat_response())

    async with RoutedClient(config, transport=httpx.MockTransport(handler)) as client:
        _, meta = await complete(client)
    assert calls == 3
    assert [event["status"] for event in client.events] == ["failed", "failed", "success"]
    assert client.events[1]["usage"]["total_tokens"] == 25
    assert client.events[0]["usage_known"] is False
    assert meta["attempt"] == 3
    assert client.budget_status["reported_tokens"] == 40
    assert client.budget_status["unknown_usage_requests"] == 1
    assert "private-key" not in json.dumps(client.events)
    assert "confidential" not in json.dumps(client.events)


async def test_nonretryable_errors_hide_response_and_do_not_fallback(monkeypatch):
    monkeypatch.setenv("TEST_WORKER_KEY", "private-key")
    async with RoutedClient(config_for(), transport=httpx.MockTransport(
        lambda request: httpx.Response(401, text="private-key confidential body")
    )) as client:
        with pytest.raises(ProviderAPIError) as error:
            await complete(client)
    assert "http_401" in str(error.value)
    assert "private-key" not in str(error.value)
    assert "confidential" not in str(error.value)
    assert len(client.events) == 1


async def test_request_budget_stops_retry_before_another_request(monkeypatch):
    monkeypatch.setenv("TEST_WORKER_KEY", "secret")
    config = config_for()
    config = replace(config, execution=ExecutionConfig(max_requests=1), providers={
        **config.providers, "worker": replace(config.providers["worker"], max_retries=2),
    })
    async def no_sleep(_):
        pass
    monkeypatch.setattr("deepseek_survey.providers.asyncio.sleep", no_sleep)
    async with RoutedClient(config, transport=httpx.MockTransport(
        lambda request: httpx.Response(503)
    )) as client:
        with pytest.raises(BudgetExceededError):
            await complete(client)
    assert len(client.events) == 1
    assert client.budget_status["requests"] == 1


async def test_token_budget_reserves_inflight_requests_atomically(monkeypatch):
    monkeypatch.setenv("TEST_WORKER_KEY", "secret")
    config = replace(config_for(), execution=ExecutionConfig(max_total_tokens=800))
    entered = asyncio.Event()
    release = asyncio.Event()

    async def handler(request):
        entered.set()
        await release.wait()
        return httpx.Response(200, json=chat_response(usage={}))

    async with RoutedClient(config, transport=httpx.MockTransport(handler)) as client:
        first = asyncio.create_task(complete(client))
        await entered.wait()
        second = asyncio.create_task(complete(client))
        await asyncio.sleep(0)
        assert not second.done()
        release.set()
        await first
        with pytest.raises(BudgetExceededError):
            await second
    assert len(client.events) == 1
    assert client.budget_status["unknown_usage_requests"] == 1
    assert client.budget_status["charged_tokens"] <= 800
    assert client.budget_status["reported_tokens"] == 0


async def test_per_provider_concurrency_shared_between_model_aliases(monkeypatch):
    monkeypatch.setenv("TEST_WORKER_KEY", "secret")
    config = config_for(max_concurrency=2)
    config = replace(config, models={**config.models, "backup": replace(config.models["fast"])})
    active = 0
    peak = 0

    async def handler(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.005)
        active -= 1
        return httpx.Response(200, json=chat_response())

    async with RoutedClient(config, transport=httpx.MockTransport(handler)) as client:
        await asyncio.gather(*(
            client.complete_json(system="JSON", user="JSON", max_tokens=10,
                                 model="fast" if number % 2 else "backup")
            for number in range(8)
        ))
    assert peak == 2


async def test_rpm_waits_between_provider_request_windows(monkeypatch):
    monkeypatch.setenv("TEST_WORKER_KEY", "secret")
    # Fake only this module's clock/sleep; no wall-clock delay or event-loop clock mutation.
    now = [0.0]
    waits = []
    class FakeClock:
        @staticmethod
        def monotonic():
            return now[0]
    async def advance(delay):
        waits.append(delay)
        now[0] += delay
    monkeypatch.setattr("deepseek_survey.providers.time", FakeClock)
    monkeypatch.setattr("deepseek_survey.providers.asyncio.sleep", advance)
    config = config_for(requests_per_minute=1)
    async with RoutedClient(config, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=chat_response())
    )) as client:
        await complete(client)
        await complete(client)
    assert waits == [60.0]


async def test_input_limit_rejects_before_request(monkeypatch):
    monkeypatch.setenv("TEST_WORKER_KEY", "secret")
    config = config_for()
    config = replace(config, models={**config.models, "fast": replace(
        config.models["fast"], max_input_tokens=20,
    )})
    client = RoutedClient(config)
    with pytest.raises(InputTooLargeError):
        await complete(client)
    assert client.events == []
    assert client.budget_status["requests"] == 0


async def test_restored_budget_keeps_spent_requests_and_tokens(monkeypatch):
    monkeypatch.setenv("TEST_WORKER_KEY", "secret")
    config = replace(config_for(), execution=ExecutionConfig(max_requests=2))
    snapshot = {"requests": 1, "charged_tokens": 1200, "reported_tokens": 100,
                "unknown_usage_requests": 1, "in_flight_requests": 0,
                "max_requests": 999999}
    async with RoutedClient(config, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=chat_response())
    )) as client:
        client.restore_budget(snapshot)
        assert client.budget_status["charged_tokens"] == 1200
        await complete(client)
        with pytest.raises(BudgetExceededError):
            await complete(client)
        with pytest.raises(ValueError, match="恢复一次"):
            client.restore_budget(snapshot)
    assert client.budget_status["requests"] == 2
    assert client.budget_status["charged_tokens"] == 1215
    assert client.budget_status["unknown_usage_requests"] == 1
    assert len(client.events) == 1


async def test_restored_tokens_exhaust_current_budget_without_sending(monkeypatch):
    monkeypatch.setenv("TEST_WORKER_KEY", "secret")
    config = replace(config_for(), execution=ExecutionConfig(max_total_tokens=1000))
    async with RoutedClient(config) as client:
        client.restore_budget({"requests": 2, "charged_tokens": 999, "reported_tokens": 999,
                               "unknown_usage_requests": 0})
        with pytest.raises(BudgetExceededError):
            await complete(client)
    assert client.events == []


@pytest.mark.parametrize("override", [
    {"requests": -1}, {"charged_tokens": 0.5}, {"reported_tokens": True},
    {"unknown_usage_requests": "0"}, {"in_flight_requests": 1},
    {"requests": 0}, {"reported_tokens": 999}, {"unknown_usage_requests": 3},
])
def test_restore_rejects_invalid_or_active_snapshot(override):
    snapshot = {"requests": 1, "charged_tokens": 200, "reported_tokens": 200,
                "unknown_usage_requests": 0, "in_flight_requests": 0, **override}
    client = RoutedClient(config_for())
    with pytest.raises(ValueError, match="预算快照"):
        client.restore_budget(snapshot)
    assert client.budget_status["requests"] == 0


async def test_temporary_token_reservation_pressure_waits_then_succeeds(monkeypatch):
    monkeypatch.setenv("TEST_WORKER_KEY", "secret")
    config = replace(config_for(), execution=ExecutionConfig(max_total_tokens=800))
    entered = asyncio.Event()
    release = asyncio.Event()

    async def handler(request):
        entered.set()
        await release.wait()
        return httpx.Response(200, json=chat_response())

    async with RoutedClient(config, transport=httpx.MockTransport(handler)) as client:
        first = asyncio.create_task(complete(client))
        await entered.wait()
        second = asyncio.create_task(complete(client))
        await asyncio.sleep(0)
        assert not second.done()
        release.set()
        await asyncio.gather(first, second)
    assert client.budget_status["requests"] == 2
    assert client.budget_status["charged_tokens"] == 30
    assert client.budget_status["in_flight_requests"] == 0


@pytest.mark.parametrize("envelope", [
    {"choices": ["bad block"]},
    {"choices": [{"message": [], "finish_reason": "stop"}]},
    {"choices": []},
])
async def test_malformed_envelopes_raise_sanitized_api_error(envelope, monkeypatch):
    monkeypatch.setenv("TEST_WORKER_KEY", "secret")
    async with RoutedClient(config_for(), transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=envelope)
    )) as client:
        with pytest.raises(ProviderAPIError, match="invalid_json_response"):
            await complete(client)


@pytest.mark.parametrize("protocol, envelope", [
    ("deepseek", {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}),
    ("gemini", {"candidates": [{"finishReason": "MAX_TOKENS"}]}),
    ("anthropic", {"stop_reason": "max_tokens", "content": []}),
])
async def test_truncated_output_never_accepted(protocol, envelope, monkeypatch):
    monkeypatch.setenv("TEST_WORKER_KEY", "secret")
    async with RoutedClient(config_for(protocol), transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=envelope)
    )) as client:
        with pytest.raises(ProviderAPIError, match="output_truncated"):
            await complete(client)
