from dataclasses import replace

import httpx
import pytest

from deepseek_survey.arxiv import deduplicate_papers, parse_arxiv_feed, search_arxiv
from deepseek_survey.config import load_config

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2309.06180v2</id>
    <updated>2025-01-28T00:00:00Z</updated>
    <published>2023-09-12T00:00:00Z</published>
    <title>  Efficient Memory Management for Large Language Model Serving with PagedAttention  </title>
    <summary>A test abstract.</summary>
    <author><name>Woosuk Kwon</name></author>
    <arxiv:primary_category term="cs.DC"/>
    <category term="cs.DC"/>
    <link href="https://arxiv.org/abs/2309.06180" rel="alternate" type="text/html"/>
    <link title="pdf" href="https://arxiv.org/pdf/2309.06180" rel="related" type="application/pdf"/>
  </entry>
</feed>
"""


def test_parse_arxiv_feed() -> None:
    papers = parse_arxiv_feed(FEED, 'all:"PagedAttention"')
    assert len(papers) == 1
    paper = papers[0]
    assert paper.paper_id == "2309.06180"
    assert paper.title == (
        "Efficient Memory Management for Large Language Model Serving with PagedAttention"
    )
    assert paper.pdf_url == "https://arxiv.org/pdf/2309.06180"
    assert paper.primary_category == "cs.DC"


def test_deduplicate_merges_queries() -> None:
    first = parse_arxiv_feed(FEED, "all:vLLM")[0]
    second = parse_arxiv_feed(FEED, 'all:"PagedAttention"')[0]
    merged = deduplicate_papers([first, second])
    assert len(merged) == 1
    assert merged[0].matched_queries == ["all:vLLM", 'all:"PagedAttention"']


@pytest.mark.asyncio
async def test_date_sorting_reaches_arxiv_and_rate_limit_is_not_empty_results(monkeypatch):
    original_client = httpx.AsyncClient
    requests = []
    status = 200
    def handler(request):
        requests.append(request)
        return httpx.Response(status, text=FEED)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original_client(
        **kw, transport=httpx.MockTransport(handler)))
    config = replace(load_config("config.toml").search, queries=('all:"PagedAttention"',),
                     sort_by="submittedDate", sort_order="descending", max_retries=0)
    papers = await search_arxiv(config)
    assert len(papers) == 1
    assert requests[0].url.params["sortBy"] == "submittedDate"
    assert requests[0].url.params["sortOrder"] == "descending"
    status = 429
    with pytest.raises(httpx.HTTPStatusError):
        await search_arxiv(config)


def test_arxiv_error_feed_is_not_a_paper():
    with pytest.raises(ValueError, match="arXiv 查询错误"):
        parse_arxiv_feed(FEED.replace("http://arxiv.org/abs/2309.06180v2", "http://arxiv.org/api/errors"), "bad")
