from deepseek_survey.config import ValidationConfig
from deepseek_survey.models import Paper
from deepseek_survey.papers import PaperContent, truncate_paper
from deepseek_survey.validation import validate_research_result

CATEGORIES = ("基础模型与架构", "推理与强化学习")


def _paper() -> Paper:
    return Paper(
        paper_id="2501.00001",
        title="A DeepSeek Test Paper",
        abstract="abstract",
        url="https://arxiv.org/abs/2501.00001",
    )


def _raw() -> dict:
    return {
        "task_id": "P01",
        "paper_id": "2501.00001",
        "title": "A DeepSeek Test Paper",
        "one_sentence_summary": "总结。",
        "research_question": "研究什么？",
        "methodology": "方法。",
        "data_and_training": "训练。",
        "main_contributions": ["贡献。"],
        "key_findings": ["发现。"],
        "limitations": ["局限。"],
        "relation_to_deepseek": "关系。",
        "categories": ["基础模型与架构"],
        "evidence": [
            {
                "claim": "claim one",
                "quote": "This is an exact and sufficiently long quotation from page one.",
                "page": 1,
            },
            {
                "claim": "claim two",
                "quote": "Another exact and sufficiently long quotation from page two.",
                "page": 2,
            },
        ],
        "confidence": 0.9,
        "unanswered_questions": [],
    }


def test_evidence_and_page_validation() -> None:
    content = PaperContent(
        paper_id="2501.00001",
        source="pdf",
        page_count=2,
        text=(
            "[PAGE 1]\nThis is an exact and sufficiently long quotation from page one.\n"
            "[PAGE 2]\nAnother exact and sufficiently long quotation from page two."
        ),
    )
    result, report = validate_research_result(
        _raw(),
        task_id="P01",
        paper=_paper(),
        content=content,
        allowed_categories=CATEGORIES,
        config=ValidationConfig(2, 20, 1),
    )
    assert result is not None
    assert result.experimental_setup == "训练。"
    assert result.relation_to_topic == "关系。"
    assert report.valid
    assert report.grounded_evidence_count == 2


def test_wrong_page_is_rejected() -> None:
    raw = _raw()
    raw["evidence"][0]["page"] = 2
    content = PaperContent(
        paper_id="2501.00001",
        source="pdf",
        page_count=2,
        text=(
            "[PAGE 1]\nThis is an exact and sufficiently long quotation from page one.\n"
            "[PAGE 2]\nAnother exact and sufficiently long quotation from page two."
        ),
    )
    _, report = validate_research_result(
        raw,
        task_id="P01",
        paper=_paper(),
        content=content,
        allowed_categories=CATEGORIES,
        config=ValidationConfig(2, 20, 1),
    )
    assert not report.valid
    assert any("claimed page" in error for error in report.errors)


def test_invalid_extra_evidence_is_dropped_when_two_are_grounded() -> None:
    raw = _raw()
    raw["evidence"].append(
        {
            "claim": "unsupported extra",
            "quote": "This quotation does not occur anywhere in the supplied paper text.",
            "page": 1,
        }
    )
    content = PaperContent(
        paper_id="2501.00001",
        source="pdf",
        page_count=2,
        text=(
            "[PAGE 1]\nThis is an exact and sufficiently long quotation from page one.\n"
            "[PAGE 2]\nAnother exact and sufficiently long quotation from page two."
        ),
    )
    result, report = validate_research_result(
        raw,
        task_id="P01",
        paper=_paper(),
        content=content,
        allowed_categories=CATEGORIES,
        config=ValidationConfig(2, 20, 1),
    )
    assert result is not None
    assert report.valid
    assert len(result.evidence) == 2
    assert report.total_evidence_count == 3
    assert report.dropped_evidence_count == 1
    assert report.warnings == ["evidence[3] quote is not verbatim in supplied text"]


def test_truncation_keeps_multiple_regions() -> None:
    text = "A" * 1000 + "B" * 1000 + "C" * 1000
    truncated = truncate_paper(text, 1000)
    assert truncated.startswith("A")
    assert "B" in truncated
    assert truncated.endswith("C" * 200)
