import pytest

from deepseek_survey.artifacts import write_json
from deepseek_survey.config import load_config
from deepseek_survey.pipeline import run_pipeline


def test_default_config_targets_ai_infra_and_allows_partial_synthesis() -> None:
    config = load_config("config.toml")
    assert "vLLM" in config.project.title
    assert config.validation.minimum_results_for_synthesis == 28
    assert config.deepseek.reader_model == "deepseek-v4-flash"
    assert config.deepseek.synthesis_model == "deepseek-v4-pro"
    assert config.deepseek.synthesis_thinking == "disabled"
    assert "all:vLLM" in config.search.queries
    assert "推理服务与请求调度" in config.categories


@pytest.mark.asyncio
async def test_resume_rejects_a_run_from_another_research_topic(tmp_path) -> None:
    config = load_config("config.toml")
    run_dir = tmp_path / "old-topic-run"
    write_json(run_dir / "run.json", {"title": "DeepSeek 论文综述"})

    with pytest.raises(ValueError, match="研究主题与当前 config.toml 不匹配"):
        await run_pipeline(
            config,
            None,  # type: ignore[arg-type]
            resume_dir=run_dir,
            progress=lambda _: None,
        )
