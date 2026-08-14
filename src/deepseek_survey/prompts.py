from __future__ import annotations

import json

from .models import Paper, ResearchResult, ScreeningItem
from .papers import PaperContent

SCREENING_SYSTEM = """You are the senior editor of a rigorous AI infrastructure systems literature survey.
Select real papers only from the supplied candidate metadata. Return one JSON object, without
Markdown. Do not invent IDs. Balance foundational systems papers with high-relevance work on
serving, scheduling, memory management, distributed execution, training infrastructure,
low-precision computation, kernels, reliability, and performance evaluation. Prefer primary
systems research, coverage diversity, and papers whose abstract provides enough evidence."""


def screening_prompt(
    papers: list[Paper],
    *,
    target: int,
    research_question: str,
    categories: tuple[str, ...],
) -> str:
    candidates = [
        {
            "paper_id": paper.paper_id,
            "title": paper.title,
            "authors": paper.authors,
            "published": paper.published,
            "abstract": paper.abstract,
            "categories": paper.categories,
            "matched_queries": paper.matched_queries,
        }
        for paper in papers
    ]
    example = {
        "selection_notes": "Brief description of selection strategy.",
        "selected": [
            {
                "paper_id": "ID_FROM_CANDIDATES",
                "relevance_score": 95,
                "rationale": "Why this paper belongs in the survey.",
                "reading_focus": "A paper-specific question for the reader.",
                "category_hint": categories[0],
            }
        ],
    }
    return f"""Research question: {research_question}

Select exactly {target} distinct papers. The JSON `selected` array MUST contain exactly {target}
items. Use only category_hint values from: {json.dumps(categories, ensure_ascii=False)}.

Required JSON shape example (the actual array must have {target} items):
{json.dumps(example, ensure_ascii=False, indent=2)}

Candidate metadata JSON:
{json.dumps(candidates, ensure_ascii=False)}"""


READER_SYSTEM = """You are one of 32 parallel scholarly systems-paper readers. Analyze only the supplied
paper text. Return a single JSON object without Markdown. Never rely on memory to fill missing
details. Distinguish claims stated by the paper from your interpretation. Evidence quotes must be
short, exact, verbatim substrings from the supplied text; include the visible [PAGE N] number when
available. If only an abstract is supplied, keep the analysis appropriately cautious and set page
to null. Write the analysis in the requested language while keeping quotes in the source language."""


def reader_prompt(
    *,
    task_id: str,
    paper: Paper,
    screening: ScreeningItem,
    content: PaperContent,
    research_question: str,
    language: str,
    categories: tuple[str, ...],
    correction_errors: list[str] | None = None,
) -> str:
    schema = ResearchResult.model_json_schema()
    correction = ""
    if correction_errors:
        correction = (
            "\nYour previous answer failed validation. Correct all these errors:\n- "
            + "\n- ".join(correction_errors)
            + "\n"
        )
    return f"""Task ID: {task_id}
Survey research question: {research_question}
Paper ID: {paper.paper_id}
Title: {paper.title}
Authors: {', '.join(paper.authors)}
Published: {paper.published}
Reader focus: {screening.reading_focus}
Selection rationale: {screening.rationale}
Available content source: {content.source}
Source warning: {content.warning or 'none'}
Output language: {language}
Allowed categories: {json.dumps(categories, ensure_ascii=False)}

Requirements:
1. task_id, paper_id, and title must exactly match the values above.
2. categories must contain only allowed category strings.
3. Include exactly two strong evidence items. Each quote must be copied character-for-character
   from the supplied text; do not paraphrase inside quote. For PDF text, copy the visible page
   number belonging to that quote.
4. Never claim experiments, data, numbers, or limitations absent from the supplied text.
5. Output valid JSON matching this JSON Schema:
{json.dumps(schema, ensure_ascii=False)}
{correction}
SUPPLIED PAPER TEXT START
{content.text}
SUPPLIED PAPER TEXT END"""


SYNTHESIS_SYSTEM = """You are the chief editor synthesizing the supplied independently validated
paper reports into a rigorous literature survey. Use only supplied reports. Return one JSON object
without Markdown. Every paper-specific or comparative claim must cite one or more supplied task
IDs in square brackets, for example [P03] or [P03, P17]. Do not create citations or facts."""


def synthesis_prompt(
    *,
    title: str,
    research_question: str,
    language: str,
    categories: tuple[str, ...],
    results: list[ResearchResult],
    planned_total: int,
) -> str:
    compact_results = [result.model_dump(mode="json") for result in results]
    from .models import SurveySynthesis

    return f"""Survey title: {title}
Research question: {research_question}
Output language: {language}
Taxonomy: {json.dumps(categories, ensure_ascii=False)}

Synthesize all {len(results)} validated reports from a planned set of {planned_total}. Explicitly
state the coverage gap when fewer than {planned_total} reports are supplied. Represent every
taxonomy category that has relevant papers, compare systems and methods instead of merely listing
summaries, identify evidence-backed gaps, and retain task-ID citations. Never infer findings from
missing or failed reports. The output must match this JSON Schema:
{json.dumps(SurveySynthesis.model_json_schema(), ensure_ascii=False)}

VALIDATED RESEARCH REPORTS JSON:
{json.dumps(compact_results, ensure_ascii=False)}"""
