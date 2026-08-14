from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .artifacts import read_json, write_json, write_text
from .models import Paper, ResearchResult, SurveySynthesis

PAPER_CARDS_HEADING = "## 逐篇阅读卡片"

CODEX_REVIEW_CHECKLIST = [
    "确认 32 篇（或达到阈值的有效论文）均有且仅有一个主分类。",
    "逐条核对技术演进关系，区分直接改进、机制扩展、横向替代、正交工作和评测。",
    "只有在 Flash 阅读卡片提供依据时，才保留“解决前作问题”或“改进前作”的表述。",
    "检查每条演进链的顺序、前驱引用、性能数字、适用条件、代价和剩余问题。",
    "检查 Pro 是否遗漏论文、重复归类、虚构任务 ID，或把相关性误写成因果继承。",
    "调整分类内叙事，使读者能从基础工作顺序读到后续扩展和开放问题。",
    "保留 Pro 草稿，另行输出审查记录和最终报告，不覆盖阶段性证据。",
]


def build_review_bundle(
    *,
    title: str,
    research_question: str,
    synthesis: SurveySynthesis,
    results: list[ResearchResult],
    papers_by_id: dict[str, Paper],
    pro_report_path: Path,
) -> dict[str, Any]:
    cards = []
    for result in sorted(results, key=lambda item: item.task_id):
        paper = papers_by_id[result.paper_id]
        cards.append(
            {
                "task_id": result.task_id,
                "paper": paper.model_dump(mode="json"),
                "flash_reading_card": result.model_dump(mode="json"),
            }
        )
    return {
        "review_status": "awaiting_codex_review",
        "reviewer": "Codex GPT",
        "research_title": title,
        "research_question": research_question,
        "pro_report_path": str(pro_report_path),
        "required_outputs": [
            "review/codex_review.md",
            "report_final.md",
        ],
        "checklist": CODEX_REVIEW_CHECKLIST,
        "pro_synthesis": synthesis.model_dump(mode="json"),
        "source_cards": cards,
    }


def render_review_instructions(pro_report_path: Path) -> str:
    checklist = "\n".join(f"- {item}" for item in CODEX_REVIEW_CHECKLIST)
    return f"""# Codex 最终审查任务

当前文件夹中的 Pro 结构化草稿位于 `{pro_report_path}`。它不是最终报告。

审查要求：

{checklist}

最终必须生成：

- `review/codex_review.md`：记录发现的问题、核验依据和修订决定。
- `report_final.md`：Codex 审查并修订后的最终综述。

完成审查后，再把 `run.json` 的状态从 `awaiting_codex_review` 更新为 `completed`，并记录
`codex_review` 与 `final_report` 路径。
"""


def finalize_codex_review(run_dir: Path) -> Path:
    """Publish a reviewed main report while preserving the Pro/Flash artifacts."""
    run_dir = run_dir.resolve()
    manifest_path = run_dir / "run.json"
    review_dir = run_dir / "review"
    pro_report_path = run_dir / "report_pro.md"
    codex_main_path = review_dir / "codex_main.md"
    codex_review_path = review_dir / "codex_review.md"
    review_status_path = review_dir / "status.json"
    final_report_path = run_dir / "report_final.md"

    required = [
        manifest_path,
        pro_report_path,
        codex_main_path,
        codex_review_path,
        review_status_path,
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Codex 审查尚不能收尾，缺少文件：" + ", ".join(missing)
        )

    manifest = read_json(manifest_path)
    if manifest.get("pro_synthesis_status") != "completed":
        raise ValueError("Pro 分类汇总尚未完成，不能发布 Codex 最终报告。")

    pro_report = pro_report_path.read_text(encoding="utf-8")
    marker = f"\n{PAPER_CARDS_HEADING}\n"
    if marker not in pro_report:
        raise ValueError(
            f"Pro 草稿中找不到 `{PAPER_CARDS_HEADING}`，无法保留 Flash 阅读卡片。"
        )
    cards_and_references = PAPER_CARDS_HEADING + pro_report.split(marker, 1)[1]
    codex_main = codex_main_path.read_text(encoding="utf-8").rstrip()
    codex_review = codex_review_path.read_text(encoding="utf-8").strip()
    if not codex_main:
        raise ValueError("review/codex_main.md 为空，不能发布最终报告。")
    if not codex_review:
        raise ValueError("review/codex_review.md 为空，不能完成审查。")

    write_text(final_report_path, f"{codex_main}\n\n{cards_and_references.rstrip()}\n")

    completed_at = datetime.now(UTC).isoformat()
    review_status = read_json(review_status_path)
    review_status.update(
        {
            "status": "completed",
            "reviewer": "Codex GPT",
            "completed_at": completed_at,
            "codex_main": str(codex_main_path),
            "codex_review": str(codex_review_path),
            "final_report": str(final_report_path),
        }
    )
    write_json(review_status_path, review_status)

    manifest.update(
        {
            "status": "completed",
            "codex_review_status": "completed",
            "codex_review_completed_at": completed_at,
            "codex_main": str(codex_main_path),
            "codex_review": str(codex_review_path),
            "final_report": str(final_report_path),
        }
    )
    write_json(manifest_path, manifest)
    return final_report_path
