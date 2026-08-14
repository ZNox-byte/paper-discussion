from deepseek_survey.validation import validate_synthesis


def test_synthesis_rejects_unknown_and_missing_ids() -> None:
    raw = {
        "title": "Survey",
        "abstract": "Finding [P01].",
        "scope_and_method": "Method [P01].",
        "category_syntheses": [
            {
                "category": "基础模型与架构",
                "overview": "Overview [P99].",
                "paper_ids": ["P01", "P99"],
                "trends": ["Trend [P01]."],
            }
        ],
        "cross_paper_findings": ["Finding [P01]."],
        "technical_comparisons": ["Comparison [P01]."],
        "research_gaps": ["Gap [P01]."],
        "conclusion": "Conclusion [P01].",
    }
    _, errors = validate_synthesis(
        raw,
        task_ids={"P01", "P02"},
        allowed_categories=("基础模型与架构",),
    )
    assert any("unknown" in error or "invented" in error for error in errors)
    assert any("omits" in error for error in errors)

