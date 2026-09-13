from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .models import Paper, ResearchResult, SurveySynthesis
from .papers import PaperContent


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- 无"


RELATION_LABELS = {
    "foundation": "基础工作",
    "direct_improvement": "直接改进",
    "mechanism_extension": "机制扩展",
    "alternative": "横向替代",
    "orthogonal": "正交工作",
    "evaluation": "评测与验证",
}


def render_report(
    synthesis: SurveySynthesis,
    results: list[ResearchResult],
    papers_by_id: dict[str, Paper],
    *,
    round_number: int = 1,
    cumulative_paper_count: int | None = None,
    planned_paper_count: int | None = None,
    failed_task_count: int = 0,
    reviewer: str = "上层模型",
    provenance: dict[str, Any] | None = None,
    contents: dict[str, PaperContent] | None = None,
) -> str:
    cumulative_paper_count = cumulative_paper_count or len(results)
    planned_paper_count = planned_paper_count or len(results)
    results_by_task = {result.task_id: result for result in results}
    lines = [
        f"# {synthesis.title}",
        "",
        f"> 阶段产物：上层模型结构化草稿；尚待 {reviewer} 最终审查。",
        "",
        (
            f"> 研究轮次：第 {round_number} 轮；本轮论文：{len(results)} 篇；"
            f"累计论文：{cumulative_paper_count} 篇；"
            f"生成时间：{datetime.now(UTC).isoformat()}。"
        ),
        "",
        "## 摘要",
        "",
        synthesis.abstract,
        "",
        "## 范围与方法",
        "",
        synthesis.scope_and_method,
        "",
        "## 分类综述",
        "",
    ]
    if failed_task_count:
        lines[4:4] = [
            (
                f"> 质量说明：计划 {planned_paper_count} 篇，{len(results)} 篇通过验证，"
                f"{failed_task_count} 篇被排除；以下综合仅依据已验证结果。"
            ),
            "",
        ]
    for section in synthesis.category_syntheses:
        lines.extend(
            [
                f"### {section.category}",
                "",
                section.overview,
                "",
                f"主分类论文：{', '.join(f'[{task_id}]' for task_id in section.paper_ids)}",
                "",
            ]
        )
        for thread in section.evolution_threads:
            lines.extend(
                [
                    f"#### 技术演进主线：{thread.thread_name}",
                    "",
                    f"**主线问题：** {thread.question}",
                    "",
                    thread.narrative,
                    "",
                ]
            )
            for number, step in enumerate(thread.ordered_steps, start=1):
                result = results_by_task[step.task_id]
                predecessors = (
                    ", ".join(f"[{task_id}]" for task_id in step.builds_on)
                    if step.builds_on
                    else "无（本主线起点）"
                )
                lines.extend(
                    [
                        f"##### {number}. [{step.task_id}] {result.title}",
                        "",
                        f"- 关系类型：{RELATION_LABELS[step.relation_to_previous]}",
                        f"- 承接论文：{predecessors}",
                        f"- 前作问题：{step.predecessor_problem}",
                        f"- 本作贡献或改进：{step.contribution_or_improvement}",
                        f"- 代价与权衡：{step.tradeoffs}",
                        f"- 剩余问题：{step.remaining_gap}",
                        f"- 关系依据：{step.relationship_evidence}",
                        "",
                    ]
                )
        if section.lateral_connections:
            lines.extend(
                [
                    "#### 横向与跨主线联系",
                    "",
                    _bullets(section.lateral_connections),
                    "",
                ]
            )
        lines.extend(["#### 分类趋势", "", _bullets(section.trends), ""])

    lines.extend(
        [
            "## 跨论文发现",
            "",
            _bullets(synthesis.cross_paper_findings),
            "",
            "## 技术比较",
            "",
            _bullets(synthesis.technical_comparisons),
            "",
            "## 研究空白",
            "",
            _bullets(synthesis.research_gaps),
            "",
            "## 结论",
            "",
            synthesis.conclusion,
            "",
        ]
    )
    lines.append(render_reading_cards(results, papers_by_id, contents=contents, provenance=provenance))
    return "\n".join(lines).rstrip() + "\n"


def render_reading_cards(
    results: list[ResearchResult],
    papers_by_id: dict[str, Paper],
    *,
    contents: dict[str, PaperContent] | None = None,
    provenance: dict[str, Any] | None = None,
) -> str:
    """Render the evidence appendix independently of an upper-model draft."""
    lines = ["## 逐篇阅读卡片", ""]
    for result in sorted(results, key=lambda item: item.task_id):
        paper = papers_by_id[result.paper_id]
        lines.extend(
            [
                f"### {result.task_id} · {paper.title}",
                "",
                result.one_sentence_summary,
                "",
                f"- 分类：{', '.join(result.categories)}",
                f"- 研究问题：{result.research_question}",
                f"- 方法：{result.methodology}",
                f"- 实验设置：{result.experimental_setup}",
                f"- 与综述主题的关系：{result.relation_to_topic}",
                f"- 置信度：{result.confidence:.2f}",
                "",
                "主要贡献：",
                "",
                _bullets(result.main_contributions),
                "",
                "主要发现：",
                "",
                _bullets(result.key_findings),
                "",
                "局限：",
                "",
                _bullets(result.limitations),
                "",
                "证据：",
                "",
            ]
        )
        for evidence in result.evidence:
            page = f"，p. {evidence.page}" if evidence.page else ""
            lines.append(f'- {evidence.claim} — “{evidence.quote}”{page}')
        lines.append("")
        content = (contents or {}).get(result.paper_id)
        if content is not None:
            lines.extend([f"- 原文来源：{content.source}", f"- 原文快照：sources/{result.task_id}.json"])
            if content.warning:
                lines.append(f"- 来源限制：{content.warning}")
            if "CONTENT OMITTED" in content.text:
                lines.append("- 来源限制：阅读文本经过截断，未覆盖完整论文。")
        elif contents is not None:
            lines.append("- 来源限制：原文快照缺失，引用尚需回查。")
        trace = (provenance or {}).get(result.task_id)
        if trace:
            producer = trace.get("producer", trace) if isinstance(trace, dict) else {}
            model = producer.get("model") or "未记录"
            provider = producer.get("provider")
            identity = f"{provider} / {model}" if provider else model
            lines.extend([
                "", f"- 实际阅读模型：{identity}",
                f"- 阅读记录：[provenance/{result.task_id}.json](provenance/{result.task_id}.json)",
            ])
        if result.unanswered_questions:
            lines.extend(["", "尚未确认：", "", _bullets(result.unanswered_questions)])
        lines.append("")

    lines.extend(["## 参考文献", ""])
    for result in sorted(results, key=lambda item: item.task_id):
        paper = papers_by_id[result.paper_id]
        authors = ", ".join(paper.authors) or "Unknown authors"
        year = (paper.published or "n.d.")[:4]
        identifier = f" doi:{paper.doi}." if paper.doi else f" arXiv:{paper.paper_id}."
        lines.append(
            f"- [{result.task_id}] {authors} ({year}). *{paper.title}*.{identifier} {paper.url}"
        )
    return "\n".join(lines).rstrip() + "\n"
