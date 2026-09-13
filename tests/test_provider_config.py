from __future__ import annotations

from dataclasses import replace

import pytest

from deepseek_survey.config import AppConfig, ModelConfig, ReviewConfig, load_config

NEW_CONFIG = '''
[project]
title = "Test"
research_question = "Question?"
[taxonomy]
categories = ["Systems"]
[providers.worker]
protocol = "gemini"
base_url = "https://generativelanguage.googleapis.com/v1beta"
api_key_env = "GEMINI_API_KEY"
max_concurrency = 4
requests_per_minute = 20
[models.fast]
provider = "worker"
model = "arbitrary-native-model-name"
tier = "flash"
max_output_tokens = 9000
max_input_tokens = 150000
[models.fast.request_options.generationConfig.thinkingConfig]
thinkingBudget = 0
[routing]
screening = "fast"
reader = "fast"
[review]
mode = "external"
name = "My reviewer"
[execution]
reader_concurrency = 8
max_requests = 100
max_total_tokens = 1000000
resume_policy = "strict"
'''


def test_new_config_without_legacy_deepseek_or_api_reviewer(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(NEW_CONFIG, encoding="utf-8")
    config = load_config(path)
    assert config.routing.screening == "fast"
    assert config.routing.reviewer is None
    assert config.deepseek.reader_model == "fast"
    assert config.deepseek.synthesis_model == ""
    assert config.execution.reader_concurrency == 8
    assert config.deepseek.reader_concurrency == 8
    assert config.providers["worker"].requests_per_minute == 20
    assert config.models["fast"].max_input_tokens == 150000
    assert config.models["fast"].request_options == {
        "generationConfig": {"thinkingConfig": {"thinkingBudget": 0}}
    }
    assert config.review.name == "My reviewer"


def test_generic_limits_override_legacy_stage_limits(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(NEW_CONFIG + '''
[limits]
max_tokens_screening = 500
max_tokens_reader = 600
max_tokens_synthesis = 700
''', encoding="utf-8")
    config = load_config(path)
    assert config.deepseek.max_tokens_screening == 500
    assert config.deepseek.max_tokens_reader == 600
    assert config.deepseek.max_tokens_synthesis == 700


@pytest.mark.parametrize("role", ["screening", "reader", "reader_fallback"])
def test_every_lower_route_rejects_pro(tmp_path, role):
    path = tmp_path / "config.toml"
    source = NEW_CONFIG + '''
[models.upper]
provider = "worker"
model = "innocent-looking-name"
tier = "pro"
'''
    if role == "reader_fallback":
        source = source.replace('[routing]', '[routing]\nreader_fallback = "upper"')
    else:
        source = source.replace(f'{role} = "fast"', f'{role} = "upper"')
    path.write_text(source, encoding="utf-8")
    with pytest.raises(ValueError, match=f"routing.{role}.*flash"):
        load_config(path)


@pytest.mark.parametrize("change,match", [
    ('mode = "external"', "API 审阅"),
    ('provider = "worker"', "provider 未定义"),
])
def test_invalid_routing_fails_before_network(tmp_path, change, match):
    source = NEW_CONFIG.replace(change, 'mode = "api"' if "mode" in change else 'provider = "missing"')
    path = tmp_path / "config.toml"
    path.write_text(source, encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        load_config(path)


def test_legacy_migration_keeps_aliases_and_requires_explicit_unknown_tiers():
    config = load_config("config.toml")
    legacy = replace(config.deepseek, screening_model="deepseek-v4-flash",
                     reader_model="deepseek-v4-flash", synthesis_model="deepseek-v4-pro")
    migrated = AppConfig(config.project, legacy, config.search, config.validation,
                         config.categories, config.source_path)
    assert migrated.models["deepseek-v4-flash"].tier == "flash"
    assert migrated.routing.reviewer == "deepseek-v4-pro"
    assert migrated.review.mode == "external"
    with pytest.raises(ValueError, match="显式声明 tier"):
        AppConfig(config.project, replace(legacy, reader_model="new-name"), config.search,
                  config.validation, config.categories, config.source_path)


def test_reviewer_requires_pro_even_if_model_name_contains_pro(tmp_path):
    path = tmp_path / "config.toml"
    source = NEW_CONFIG.replace('[routing]', '[routing]\nreviewer = "fast"')
    source = source.replace('arbitrary-native-model-name', 'name-containing-pro')
    path.write_text(source, encoding="utf-8")
    with pytest.raises(ValueError, match="routing.reviewer.*pro"):
        load_config(path)


@pytest.mark.parametrize("options", [
    {"model": "expensive-model"},
    {"max_tokens": 999999},
    {"generationConfig": {"maxOutputTokens": 999999}},
    {"messages": []},
    {"api_key": "secret"},
])
def test_request_options_cannot_bypass_routing_or_output_budgets(options):
    config = load_config("config.toml")
    alias = config.routing.reader
    with pytest.raises(ValueError, match="不能覆盖"):
        replace(config, models={**config.models, alias: replace(
            config.models[alias], request_options=options,
        )})


def test_model_identity_uses_explicit_tier_without_substring_guessing():
    config = load_config("config.toml")
    alias = config.routing.reader
    updated = replace(config, models={**config.models, alias: ModelConfig(
        config.models[alias].provider, "user-assigned-model-with-pro-in-name", "flash",
    )}, review=ReviewConfig())
    assert updated.models[alias].tier == "flash"
