from __future__ import annotations

import asyncio
import random
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable

import httpx

from .config import SearchConfig
from .models import Paper

ATOM = "http://www.w3.org/2005/Atom"
ARXIV = "http://arxiv.org/schemas/atom"
NAMESPACES = {"atom": ATOM, "arxiv": ARXIV}
USER_AGENT = "deepseek-paper-survey/0.1 (academic research orchestrator)"


def _text(element: ET.Element, path: str) -> str | None:
    found = element.find(path, NAMESPACES)
    if found is None or found.text is None:
        return None
    return " ".join(found.text.split())


def _paper_id(entry_url: str) -> str:
    identifier = entry_url.rstrip("/").rsplit("/", 1)[-1]
    return re.sub(r"v\d+$", "", identifier)


def normalize_paper_title(title: str) -> str:
    return re.sub(r"\W+", "", title).casefold()


def paper_identity_keys(paper: Paper) -> set[str]:
    keys = {f"id:{paper.paper_id.casefold()}", f"title:{normalize_paper_title(paper.title)}"}
    if paper.doi:
        keys.add(f"doi:{paper.doi.casefold()}")
    return keys


def parse_arxiv_feed(xml_text: str, query: str) -> list[Paper]:
    root = ET.fromstring(xml_text)
    papers: list[Paper] = []
    for entry in root.findall("atom:entry", NAMESPACES):
        url = _text(entry, "atom:id") or ""
        if not url:
            continue
        links = {
            link.attrib.get("title", link.attrib.get("rel", "")): link.attrib.get("href", "")
            for link in entry.findall("atom:link", NAMESPACES)
        }
        categories = [
            category.attrib["term"]
            for category in entry.findall("atom:category", NAMESPACES)
            if category.attrib.get("term")
        ]
        doi = _text(entry, "arxiv:doi")
        primary = entry.find("arxiv:primary_category", NAMESPACES)
        papers.append(
            Paper(
                paper_id=_paper_id(url),
                title=_text(entry, "atom:title") or "Untitled",
                abstract=_text(entry, "atom:summary") or "",
                authors=[
                    name
                    for author in entry.findall("atom:author", NAMESPACES)
                    if (name := _text(author, "atom:name"))
                ],
                published=_text(entry, "atom:published"),
                updated=_text(entry, "atom:updated"),
                doi=doi,
                url=links.get("alternate", url),
                pdf_url=links.get("pdf"),
                primary_category=primary.attrib.get("term") if primary is not None else None,
                categories=categories,
                matched_queries=[query],
            )
        )
    return papers


def deduplicate_papers(papers: Iterable[Paper]) -> list[Paper]:
    unique: dict[str, Paper] = {}
    title_index: dict[str, str] = {}
    for paper in papers:
        key = paper.doi.lower() if paper.doi else paper.paper_id.lower()
        normalized_title = normalize_paper_title(paper.title)
        existing_key = title_index.get(normalized_title, key)
        if existing_key in unique:
            existing = unique[existing_key]
            existing.matched_queries = list(
                dict.fromkeys(existing.matched_queries + paper.matched_queries)
            )
            continue
        unique[key] = paper
        title_index[normalized_title] = key
    return list(unique.values())


def deterministic_rank(paper: Paper) -> tuple[int, str, str]:
    text = f"{paper.title} {paper.abstract}".casefold()
    signals = (
        ("vllm", 14),
        ("llm serving", 10),
        ("large language model serving", 10),
        ("pagedattention", 8),
        ("kv cache", 7),
        ("sglang", 7),
        ("inference system", 6),
        ("request scheduling", 5),
        ("disaggregated prefill", 5),
        ("chunked prefill", 5),
        ("continuous batching", 5),
        ("speculative decoding", 4),
        ("flashattention", 4),
        ("tensor parallel", 4),
        ("model parallel", 4),
        ("distributed training", 4),
        ("megatron", 3),
        ("deepspeed", 3),
    )
    score = sum(weight * text.count(term) for term, weight in signals)
    score += min(len(paper.matched_queries), 4)
    return (-score, paper.published or "", paper.paper_id)


async def search_arxiv(
    config: SearchConfig, progress: Callable[[str], None] | None = None
) -> list[Paper]:
    report = progress or (lambda _message: None)
    timeout = httpx.Timeout(config.request_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": USER_AGENT}) as client:

        async def search_one(query: str, query_number: int) -> list[Paper]:
            response: httpx.Response | None = None
            for attempt in range(config.max_retries + 1):
                response = await client.get(
                    config.endpoint,
                    params={
                        "search_query": query,
                        "start": 0,
                        "max_results": config.max_results_per_query,
                        "sortBy": "relevance",
                        "sortOrder": "descending",
                    },
                )
                if response.status_code not in {429, 500, 502, 503, 504}:
                    response.raise_for_status()
                    return parse_arxiv_feed(response.text, query)
                if attempt >= config.max_retries:
                    break
                retry_after = response.headers.get("Retry-After")
                try:
                    server_delay = float(retry_after) if retry_after else 0.0
                except ValueError:
                    server_delay = 0.0
                delay = max(server_delay, min(60.0, 5.0 * (2**attempt)))
                report(
                    f"[discover] arXiv returned HTTP {response.status_code} for query "
                    f"{query_number}/{len(config.queries)}; retrying in {delay:.0f}s "
                    f"({attempt + 1}/{config.max_retries})"
                )
                await asyncio.sleep(delay + random.random())
            assert response is not None
            response.raise_for_status()
            raise RuntimeError("unreachable")

        # arXiv 对突发请求较敏感，检索阶段保守串行；32 路并发只用于论文阅读。
        result_sets: list[list[Paper]] = []
        for index, query in enumerate(config.queries):
            if index:
                await asyncio.sleep(config.request_delay_seconds)
            query_number = index + 1
            report(f"[discover] query {query_number}/{len(config.queries)}: {query}")
            result_sets.append(await search_one(query, query_number))

    papers = deduplicate_papers(paper for group in result_sets for paper in group)
    return sorted(papers, key=deterministic_rank)
