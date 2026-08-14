from __future__ import annotations

from datetime import UTC, datetime

from .models import Paper, ResearchResult, SurveySynthesis


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- 无"


def render_report(
    synthesis: SurveySynthesis,
    results: list[ResearchResult],
    papers_by_id: dict[str, Paper],
    *,
    round_number: int = 1,
    cumulative_paper_count: int | None = None,
    planned_paper_count: int | None = None,
    failed_task_count: int = 0,
) -> str:
    cumulative_paper_count = cumulative_paper_count or len(results)
    planned_paper_count = planned_paper_count or len(results)
    lines = [
        f"# {synthesis.title}",
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
        lines[2:2] = [
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
                f"覆盖任务：{', '.join(f'[{task_id}]' for task_id in section.paper_ids)}",
                "",
                _bullets(section.trends),
                "",
            ]
        )

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
            "## 逐篇阅读卡片",
            "",
        ]
    )
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
