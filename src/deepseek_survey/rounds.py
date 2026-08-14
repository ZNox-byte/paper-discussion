from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import read_json
from .arxiv import paper_identity_keys
from .models import Paper, ScreeningDecision


@dataclass(frozen=True, slots=True)
class RoundContext:
    round_number: int
    parent_run: Path | None
    excluded_identity_keys: frozenset[str]
    previous_papers: tuple[dict[str, Any], ...]

    @classmethod
    def first(cls) -> RoundContext:
        return cls(1, None, frozenset(), ())

    def as_dict(self) -> dict[str, Any]:
        return {
            "round_number": self.round_number,
            "parent_run": str(self.parent_run) if self.parent_run else None,
            "excluded_paper_count": len(self.previous_papers),
            "excluded_identity_keys": sorted(self.excluded_identity_keys),
            "previous_papers": list(self.previous_papers),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RoundContext:
        parent = raw.get("parent_run")
        return cls(
            round_number=int(raw.get("round_number", 1)),
            parent_run=Path(parent).resolve() if parent else None,
            excluded_identity_keys=frozenset(raw.get("excluded_identity_keys", ())),
            previous_papers=tuple(raw.get("previous_papers", ())),
        )


def load_saved_round_context(run_dir: Path) -> RoundContext:
    path = run_dir / "round_context.json"
    if not path.exists():
        return RoundContext.first()
    raw = read_json(path)
    if not isinstance(raw, dict):
        raise TypeError(f"Invalid round context: {path}")
    return RoundContext.from_dict(raw)


def _load_round_group(run_dir: Path) -> tuple[int, Path | None, list[dict[str, Any]]]:
    selection_path = run_dir / "screening" / "selection.json"
    candidates_path = run_dir / "candidates.json"
    if not selection_path.exists():
        raise ValueError(f"上一轮尚未产生有效筛选结果: {selection_path}")
    if not candidates_path.exists():
        raise ValueError(f"上一轮缺少候选论文文件: {candidates_path}")

    selection = ScreeningDecision.model_validate(read_json(selection_path))
    candidates = [Paper.model_validate(item) for item in read_json(candidates_path)]
    papers_by_id = {paper.paper_id: paper for paper in candidates}
    manifest_path = run_dir / "run.json"
    manifest = read_json(manifest_path) if manifest_path.exists() else {}
    round_number = int(manifest.get("round_number", 1))
    parent_value = manifest.get("parent_run")
    parent_run = Path(parent_value).resolve() if parent_value else None

    entries: list[dict[str, Any]] = []
    for number, item in enumerate(selection.selected, start=1):
        paper = papers_by_id.get(item.paper_id)
        if paper is None:
            raise ValueError(
                f"上一轮入选论文 {item.paper_id} 不在候选文件中: {candidates_path}"
            )
        entries.append(
            {
                "round_number": round_number,
                "source_run": str(run_dir),
                "task_id": f"P{number:02d}",
                "paper_id": paper.paper_id,
                "title": paper.title,
                "doi": paper.doi,
                "url": paper.url,
            }
        )
    return round_number, parent_run, entries


def load_next_round_context(
    parent_run: Path, *, expected_title: str | None = None
) -> RoundContext:
    direct_parent = parent_run.resolve()
    current = direct_parent
    visited: set[Path] = set()
    groups: list[tuple[int, list[dict[str, Any]]]] = []
    direct_round_number = 1

    while current is not None:
        if current in visited:
            raise ValueError(f"轮次父链存在循环: {current}")
        visited.add(current)
        manifest_path = current / "run.json"
        manifest = read_json(manifest_path) if manifest_path.exists() else {}
        if expected_title and manifest.get("title") != expected_title:
            raise ValueError(
                f"父轮次研究主题不匹配: expected {expected_title!r}, "
                f"got {manifest.get('title')!r} in {current}"
            )
        round_number, next_parent, entries = _load_round_group(current)
        if current == direct_parent:
            direct_round_number = round_number
        groups.append((round_number, entries))
        current = next_parent

    excluded_keys: set[str] = set()
    previous_papers: list[dict[str, Any]] = []
    seen_paper_ids: set[str] = set()
    for _, entries in reversed(groups):
        for entry in entries:
            paper = Paper(
                paper_id=entry["paper_id"],
                title=entry["title"],
                abstract="",
                doi=entry.get("doi"),
                url=entry["url"],
            )
            excluded_keys.update(paper_identity_keys(paper))
            if paper.paper_id not in seen_paper_ids:
                previous_papers.append(entry)
                seen_paper_ids.add(paper.paper_id)

    return RoundContext(
        round_number=direct_round_number + 1,
        parent_run=direct_parent,
        excluded_identity_keys=frozenset(excluded_keys),
        previous_papers=tuple(previous_papers),
    )


def filter_previously_selected(
    papers: list[Paper], context: RoundContext
) -> tuple[list[Paper], list[Paper]]:
    eligible: list[Paper] = []
    excluded: list[Paper] = []
    for paper in papers:
        destination = (
            excluded
            if paper_identity_keys(paper) & context.excluded_identity_keys
            else eligible
        )
        destination.append(paper)
    return eligible, excluded
