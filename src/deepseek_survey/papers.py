from __future__ import annotations

import asyncio
import io
import re
from dataclasses import dataclass

import httpx
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .arxiv import USER_AGENT
from .models import Paper
from .text import sanitize_unicode


@dataclass(frozen=True, slots=True)
class PaperContent:
    paper_id: str
    source: str
    text: str
    page_count: int | None
    warning: str | None = None
    full_text: str | None = None


def extract_pdf_text(content: bytes) -> tuple[str, int]:
    reader = PdfReader(io.BytesIO(content))
    pages: list[str] = []
    for number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pages.append(f"\n[PAGE {number}]\n{text.strip()}")
    return sanitize_unicode("\n".join(pages).strip()), len(reader.pages)


def truncate_paper(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    first_end = int(max_chars * 0.6)
    middle_size = int(max_chars * 0.2)
    last_size = max_chars - first_end - middle_size
    center = len(text) // 2
    middle_start = max(0, center - middle_size // 2)
    return (
        text[:first_end]
        + "\n\n[... CONTENT OMITTED: MIDDLE SAMPLE FOLLOWS ...]\n\n"
        + text[middle_start : middle_start + middle_size]
        + "\n\n[... CONTENT OMITTED: FINAL SAMPLE FOLLOWS ...]\n\n"
        + text[-last_size:]
    )


async def fetch_paper_content(
    client: httpx.AsyncClient,
    paper: Paper,
    max_chars: int,
) -> PaperContent:
    if not paper.pdf_url:
        return PaperContent(
            paper_id=paper.paper_id,
            source="abstract",
            text=f"[ABSTRACT]\n{paper.abstract}",
            page_count=None,
            warning="No PDF URL; analysis is based on the abstract only.",
        )
    try:
        response = await client.get(paper.pdf_url, follow_redirects=True)
        response.raise_for_status()
        text, page_count = await asyncio.to_thread(extract_pdf_text, response.content)
        if len(re.sub(r"\s+", "", text)) < 500:
            raise ValueError("PDF text extraction produced too little text")
        return PaperContent(
            paper_id=paper.paper_id,
            source="pdf",
            text=truncate_paper(text, max_chars),
            page_count=page_count,
            full_text=text,
            warning=("Text supplied to the reader was sampled; full extracted text is saved."
                     if len(text) > max_chars else None),
        )
    except (httpx.HTTPError, PdfReadError, ValueError, OSError) as exc:
        return PaperContent(
            paper_id=paper.paper_id,
            source="abstract",
            text=f"[ABSTRACT]\n{paper.abstract}",
            page_count=None,
            warning=f"PDF unavailable ({type(exc).__name__}); analysis uses abstract only.",
        )


async def fetch_all_papers(
    papers: list[Paper],
    *,
    max_chars: int,
    concurrency: int,
    timeout_seconds: float,
) -> dict[str, PaperContent]:
    semaphore = asyncio.Semaphore(concurrency)
    timeout = httpx.Timeout(timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": USER_AGENT}) as client:

        async def guarded(paper: Paper) -> PaperContent:
            async with semaphore:
                return await fetch_paper_content(client, paper, max_chars)

        contents = await asyncio.gather(*(guarded(paper) for paper in papers))
    return {content.paper_id: content for content in contents}
