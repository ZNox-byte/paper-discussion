from __future__ import annotations

from deepseek_survey.artifacts import write_json
from deepseek_survey.models import Paper
from deepseek_survey.rounds import filter_previously_selected, load_next_round_context


def _paper(number: int, *, paper_id: str | None = None, title: str | None = None) -> Paper:
    return Paper(
        paper_id=paper_id or f"paper-{number:02d}",
        title=title or f"Paper {number:02d}",
        abstract="Abstract.",
        doi=f"10.1000/{number:02d}",
        url=f"https://example.test/paper-{number:02d}",
    )


def _write_round(run_dir, papers: list[Paper], selected: list[Paper], **manifest) -> None:
    write_json(run_dir / "candidates.json", [paper.model_dump(mode="json") for paper in papers])
    write_json(
        run_dir / "screening" / "selection.json",
        {
            "selection_notes": "test",
            "selected": [
                {
                    "paper_id": paper.paper_id,
                    "relevance_score": 90,
                    "rationale": "Relevant.",
                    "reading_focus": "Focus.",
                    "category_hint": "基础模型与架构",
                }
                for paper in selected
            ],
        },
    )
    write_json(run_dir / "run.json", {"title": "Test", **manifest})


def test_next_round_excludes_entire_parent_chain_by_id_doi_and_title(tmp_path) -> None:
    papers = [_paper(number) for number in range(1, 97)]
    round_one = tmp_path / "round-one"
    _write_round(round_one, papers, papers[:32], round_number=1, parent_run=None)

    first_context = load_next_round_context(round_one)
    eligible, excluded = filter_previously_selected(papers, first_context)
    assert first_context.round_number == 2
    assert len(first_context.previous_papers) == 32
    assert [paper.paper_id for paper in excluded] == [paper.paper_id for paper in papers[:32]]
    assert [paper.paper_id for paper in eligible] == [paper.paper_id for paper in papers[32:]]

    round_two = tmp_path / "round-two"
    _write_round(
        round_two,
        papers,
        papers[32:64],
        round_number=2,
        parent_run=str(round_one.resolve()),
    )
    second_context = load_next_round_context(round_two)
    eligible, excluded = filter_previously_selected(papers, second_context)
    assert second_context.round_number == 3
    assert len(second_context.previous_papers) == 64
    assert len(excluded) == 64
    assert [paper.paper_id for paper in eligible] == [paper.paper_id for paper in papers[64:]]

    same_title_new_id = _paper(99, paper_id="alternate-id", title="Paper 01")
    same_doi_new_title = Paper(
        paper_id="another-id",
        title="A renamed paper",
        abstract="Abstract.",
        doi="10.1000/02",
        url="https://example.test/another-id",
    )
    eligible, excluded = filter_previously_selected(
        [same_title_new_id, same_doi_new_title], second_context
    )
    assert not eligible
    assert len(excluded) == 2


def test_next_round_rejects_a_different_research_series(tmp_path) -> None:
    papers = [_paper(number) for number in range(1, 33)]
    round_one = tmp_path / "round-one"
    _write_round(round_one, papers, papers, round_number=1, parent_run=None)

    try:
        load_next_round_context(round_one, expected_title="Another Survey")
    except ValueError as exc:
        assert "研究主题不匹配" in str(exc)
    else:
        raise AssertionError("A different research series should be rejected")
