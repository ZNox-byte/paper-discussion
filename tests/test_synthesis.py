from deepseek_survey.validation import validate_synthesis

CATEGORY = "基础模型与架构"


def _step(
    task_id: str,
    *,
    relation: str = "foundation",
    builds_on: list[str] | None = None,
) -> dict:
    predecessors = builds_on or []
    cited = [task_id, *predecessors]
    citations = ", ".join(f"[{item}]" for item in cited)
    return {
        "task_id": task_id,
        "relation_to_previous": relation,
        "builds_on": predecessors,
        "predecessor_problem": f"Predecessor problem {citations}.",
        "contribution_or_improvement": f"Contribution {citations}.",
        "tradeoffs": f"Tradeoff {citations}.",
        "remaining_gap": f"Remaining gap {citations}.",
        "relationship_evidence": f"Relationship evidence {citations}.",
    }


def _raw(
    paper_ids: list[str],
    steps: list[dict],
    *,
    overview: str = "Overview [P01].",
) -> dict:
    return {
        "title": "Survey",
        "abstract": "Finding [P01].",
        "scope_and_method": "Method [P01].",
        "category_syntheses": [
            {
                "category": CATEGORY,
                "overview": overview,
                "paper_ids": paper_ids,
                "evolution_threads": [
                    {
                        "thread_name": "Thread",
                        "question": "How did the systems evolve?",
                        "narrative": "Evolution narrative [P01].",
                        "ordered_steps": steps,
                    }
                ],
                "lateral_connections": ["Lateral connection [P01]."],
                "trends": ["Trend [P01]."],
            }
        ],
        "cross_paper_findings": ["Finding [P01]."],
        "technical_comparisons": ["Comparison [P01]."],
        "research_gaps": ["Gap [P01]."],
        "conclusion": "Conclusion [P01].",
    }


def test_synthesis_rejects_unknown_and_missing_ids() -> None:
    raw = _raw(
        ["P01", "P99"],
        [
            _step("P01"),
            _step("P99", relation="direct_improvement", builds_on=["P01"]),
        ],
        overview="Overview [P99].",
    )

    _, errors = validate_synthesis(
        raw,
        task_ids={"P01", "P02"},
        allowed_categories=(CATEGORY,),
    )

    assert any("unknown" in error or "invented" in error for error in errors)
    assert any("omits" in error for error in errors)


def test_unbracketed_gap_ids_and_p99_metric_are_not_citations() -> None:
    raw = _raw(["P01"], [_step("P01")])
    raw["abstract"] = "The p99 latency improved; reports P05 and P25 were missing [P01]."
    raw["technical_comparisons"] = ["Comparison reports P99 latency [P01]."]
    raw["research_gaps"] = ["Reports P05 and P25 were unavailable [P01]."]

    _, errors = validate_synthesis(
        raw,
        task_ids={"P01"},
        allowed_categories=(CATEGORY,),
    )

    assert errors == []


def test_category_and_step_task_id_formatting_is_normalized() -> None:
    raw = _raw(["17", "p17"], [_step("17")], overview="Overview [P17].")
    raw["abstract"] = "Finding [P17]."
    raw["scope_and_method"] = "Method [P17]."
    raw["category_syntheses"][0]["evolution_threads"][0]["narrative"] = (
        "Narrative [P17]."
    )
    raw["category_syntheses"][0]["lateral_connections"] = ["Connection [P17]."]
    raw["category_syntheses"][0]["trends"] = ["Trend [P17]."]
    raw["cross_paper_findings"] = ["Finding [P17]."]
    raw["technical_comparisons"] = ["Comparison [P17]."]
    raw["research_gaps"] = ["Gap [P17]."]
    raw["conclusion"] = "Conclusion [P17]."
    raw["category_syntheses"][0]["evolution_threads"][0]["ordered_steps"][0][
        "relationship_evidence"
    ] = "Evidence [P17]."

    synthesis, errors = validate_synthesis(
        raw,
        task_ids={"P17"},
        allowed_categories=(CATEGORY,),
    )

    assert errors == []
    assert synthesis is not None
    assert synthesis.category_syntheses[0].paper_ids == ["P17"]
    assert (
        synthesis.category_syntheses[0].evolution_threads[0].ordered_steps[0].task_id
        == "P17"
    )


def test_evolution_thread_requires_predecessors_to_appear_earlier() -> None:
    raw = _raw(
        ["P01", "P02"],
        [
            _step("P01"),
            _step("P02", relation="direct_improvement", builds_on=["P03"]),
        ],
    )

    _, errors = validate_synthesis(
        raw,
        task_ids={"P01", "P02", "P03"},
        allowed_categories=(CATEGORY,),
    )

    assert any("must appear earlier" in error for error in errors)
