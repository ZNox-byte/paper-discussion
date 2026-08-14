from __future__ import annotations

from typing import Any

import pytest

from deepseek_survey.config import load_config
from deepseek_survey.models import Evidence, Paper, ResearchResult
from deepseek_survey.pipeline import _screen_candidates, _synthesize


class RecordingClient:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = responses
        self.models: list[str] = []

    async def complete_json(
        self, *, system: str, user: str, max_tokens: int, model: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        del system, user, max_tokens
        self.models.append(model)
        return self.responses.pop(0), {"request_id": "test", "requested_model": model}


def _paper(number: int) -> Paper:
    return Paper(
        paper_id=f"paper-{number:02d}",
        title=f"Paper {number:02d}",
        abstract="DeepSeek research abstract.",
        url=f"https://example.test/paper-{number:02d}",
    )


@pytest.mark.asyncio
async def test_screening_uses_flash_and_synthesis_uses_pro(tmp_path) -> None:
    config = load_config("config.toml")
    papers = [_paper(number) for number in range(1, 33)]
    screening_response = {
        "selection_notes": "Balanced selection.",
        "selected": [
            {
                "paper_id": paper.paper_id,
                "relevance_score": 90,
                "rationale": "Relevant to the survey.",
                "reading_focus": "Inspect the supplied evidence.",
                "category_hint": config.categories[0],
            }
            for paper in papers
        ],
    }
    screening_client = RecordingClient([screening_response])
    decision = await _screen_candidates(
        screening_client,  # type: ignore[arg-type]
        config,
        papers,
        tmp_path,
        [],
        lambda _: None,
    )
    assert len(decision.selected) == 32
    assert screening_client.models == ["deepseek-v4-flash"]

    result = ResearchResult(
        task_id="P01",
        paper_id="paper-01",
        title="Paper 01",
        one_sentence_summary="Summary.",
        research_question="Question.",
        methodology="Method.",
        experimental_setup="Experimental setup.",
        main_contributions=["Contribution."],
        key_findings=["Finding."],
        limitations=["Limitation."],
        relation_to_topic="Relationship.",
        categories=[config.categories[0]],
        evidence=[Evidence(claim="Claim.", quote="A sufficiently long exact source quote.")],
        confidence=0.9,
    )
    synthesis_response = {
        "title": "Survey",
        "abstract": "Abstract [P01].",
        "scope_and_method": "Method [P01].",
        "category_syntheses": [
            {
                "category": config.categories[0],
                "overview": "Overview [P01].",
                "paper_ids": ["P01"],
                "trends": ["Trend [P01]."],
            }
        ],
        "cross_paper_findings": ["Finding [P01]."],
        "technical_comparisons": ["Comparison [P01]."],
        "research_gaps": ["Gap [P01]."],
        "conclusion": "Conclusion [P01].",
    }
    synthesis_client = RecordingClient([synthesis_response])
    synthesis = await _synthesize(
        client=synthesis_client,  # type: ignore[arg-type]
        config=config,
        run_dir=tmp_path,
        results=[result],
        usage=[],
    )
    assert synthesis.title == "Survey"
    assert synthesis_client.models == ["deepseek-v4-pro"]
