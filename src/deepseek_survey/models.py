from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Paper(StrictModel):
    paper_id: str
    title: str
    abstract: str
    authors: list[str] = Field(default_factory=list)
    published: str | None = None
    updated: str | None = None
    doi: str | None = None
    url: str
    pdf_url: str | None = None
    primary_category: str | None = None
    categories: list[str] = Field(default_factory=list)
    matched_queries: list[str] = Field(default_factory=list)


class ScreeningItem(StrictModel):
    paper_id: str
    relevance_score: int = Field(ge=0, le=100)
    rationale: str
    reading_focus: str
    category_hint: str


class ScreeningDecision(StrictModel):
    selection_notes: str
    selected: list[ScreeningItem]


class Evidence(StrictModel):
    claim: str
    quote: str
    page: int | None = Field(default=None, ge=1)


class ResearchResult(StrictModel):
    task_id: str
    paper_id: str
    title: str
    one_sentence_summary: str
    research_question: str
    methodology: str
    experimental_setup: str = Field(
        validation_alias=AliasChoices("experimental_setup", "data_and_training")
    )
    main_contributions: list[str] = Field(min_length=1)
    key_findings: list[str] = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)
    relation_to_topic: str = Field(
        validation_alias=AliasChoices("relation_to_topic", "relation_to_deepseek")
    )
    categories: list[str] = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    unanswered_questions: list[str] = Field(default_factory=list)

    @field_validator("categories")
    @classmethod
    def deduplicate_categories(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


RelationType = Literal[
    "foundation",
    "direct_improvement",
    "mechanism_extension",
    "alternative",
    "orthogonal",
    "evaluation",
]


class PrimaryAssignment(StrictModel):
    task_id: str
    category: str
    rationale: str


class PrimaryClassification(StrictModel):
    assignments: list[PrimaryAssignment] = Field(min_length=1)


class EvolutionPlanStep(StrictModel):
    task_id: str
    relation_to_previous: RelationType
    builds_on: list[str] = Field(default_factory=list)
    relationship_rationale: str


class EvolutionPlanThread(StrictModel):
    thread_name: str
    question: str
    ordered_steps: list[EvolutionPlanStep] = Field(min_length=1)


class CategoryPlan(StrictModel):
    category: str
    paper_ids: list[str] = Field(min_length=1)
    evolution_threads: list[EvolutionPlanThread] = Field(min_length=1)


class SynthesisPlan(StrictModel):
    categories: list[CategoryPlan] = Field(min_length=1)


class EvolutionStep(StrictModel):
    task_id: str
    relation_to_previous: RelationType
    builds_on: list[str] = Field(default_factory=list)
    predecessor_problem: str
    contribution_or_improvement: str
    tradeoffs: str
    remaining_gap: str
    relationship_evidence: str


class EvolutionThread(StrictModel):
    thread_name: str
    question: str
    narrative: str
    ordered_steps: list[EvolutionStep] = Field(min_length=1)


class CategorySynthesis(StrictModel):
    category: str
    overview: str
    paper_ids: list[str] = Field(min_length=1)
    evolution_threads: list[EvolutionThread] = Field(min_length=1)
    lateral_connections: list[str] = Field(default_factory=list)
    trends: list[str] = Field(min_length=1)


class SurveySynthesis(StrictModel):
    title: str
    abstract: str
    scope_and_method: str
    category_syntheses: list[CategorySynthesis]
    cross_paper_findings: list[str]
    technical_comparisons: list[str]
    research_gaps: list[str]
    conclusion: str


class SurveyNarrative(StrictModel):
    title: str
    abstract: str
    scope_and_method: str
    cross_paper_findings: list[str]
    technical_comparisons: list[str]
    research_gaps: list[str]
    conclusion: str


class ValidationReport(StrictModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    grounded_evidence_count: int = 0
    total_evidence_count: int = 0
    dropped_evidence_count: int = 0
