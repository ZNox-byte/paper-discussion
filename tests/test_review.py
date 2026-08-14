from __future__ import annotations

import json
from pathlib import Path

import pytest

from deepseek_survey.review import finalize_codex_review


def _write_json(path: Path, value: dict[str, str]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def test_finalize_codex_review_preserves_flash_cards_and_updates_status(
    tmp_path: Path,
) -> None:
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    _write_json(
        tmp_path / "run.json",
        {"status": "awaiting_codex_review", "pro_synthesis_status": "completed"},
    )
    _write_json(review_dir / "status.json", {"status": "awaiting_codex_review"})
    (tmp_path / "report_pro.md").write_text(
        "# Pro draft\n\n## 逐篇阅读卡片\n\n### P01\nFlash evidence.\n",
        encoding="utf-8",
    )
    (review_dir / "codex_main.md").write_text(
        "# Reviewed survey\n\nReviewed synthesis.\n", encoding="utf-8"
    )
    (review_dir / "codex_review.md").write_text(
        "# Review record\n\nApproved with revisions.\n", encoding="utf-8"
    )

    final_path = finalize_codex_review(tmp_path)

    final_text = final_path.read_text(encoding="utf-8")
    assert final_text.startswith("# Reviewed survey")
    assert "# Pro draft" not in final_text
    assert "## 逐篇阅读卡片" in final_text
    assert "Flash evidence." in final_text
    manifest = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    review_status = json.loads(
        (review_dir / "status.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "completed"
    assert manifest["final_report"] == str(final_path)
    assert review_status["status"] == "completed"


def test_finalize_codex_review_requires_pro_synthesis(tmp_path: Path) -> None:
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    _write_json(tmp_path / "run.json", {"pro_synthesis_status": "pending"})
    _write_json(review_dir / "status.json", {"status": "pending"})
    (tmp_path / "report_pro.md").write_text(
        "# Draft\n\n## 逐篇阅读卡片\n", encoding="utf-8"
    )
    (review_dir / "codex_main.md").write_text("body", encoding="utf-8")
    (review_dir / "codex_review.md").write_text("review", encoding="utf-8")

    with pytest.raises(ValueError, match="Pro 分类汇总尚未完成"):
        finalize_codex_review(tmp_path)
