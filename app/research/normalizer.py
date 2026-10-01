"""Turn per-category provider results into one clean, numbered list of SearchHits.

Why normalize at all?

- Providers disagree on field names and quality; the LLM prompt and the
  grounding checks should see one predictable shape.
- The same page often answers two queries (a "Goa guide" ranks for
  attractions *and* restaurants). Sending it twice wastes tokens.
- Web text contains junk: control characters, huge pages, unrelated pages,
  ``javascript:`` links, and text that tries to look like our prompt markup.
- Every result needs a short stable id (S1, S2, ...) so the LLM can cite it
  and our code can verify the citation.

Steps (in order, per result):
1. drop non-http(s) URLs
2. clean text (control chars, whitespace), strip anything resembling our
   ``<source>`` delimiters so a page cannot "close" its block in the prompt
3. drop results with almost no text
4. drop results that never mention the destination (irrelevance filter)
5. drop duplicate URLs (first category wins, categories are processed in fixed order)
6. truncate long content at a word boundary
7. assign ids S1..Sn in processing order and record the domain
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

from app.core.exceptions import TravelPlannerError
from app.research.text import clean_text, contains_phrase, fold, truncate
from app.schemas import ResearchCategory, ResearchQuery, SearchHit
from app.tools.search.base import SearchResultItem

MIN_CONTENT_CHARS = 40
_DELIMITER_LIKE = re.compile(r"</?\s*source\b[^>]*>?", re.IGNORECASE)


@dataclass
class CategoryResults:
    """What one search node produced: the query, provider items, and any failure."""

    query: ResearchQuery
    items: list[SearchResultItem] = field(default_factory=list)
    latency_ms: float | None = None
    error: TravelPlannerError | None = None

    @property
    def error_code(self) -> str | None:
        return self.error.code if self.error else None


@dataclass
class NormalizationOutcome:
    hits: list[SearchHit]
    kept_per_category: dict[ResearchCategory, int]
    dropped: dict[str, int]


def canonical_url(url: str) -> str:
    """Normalize for duplicate detection: lower-case host, no fragment/trailing slash/utm params."""
    parts = urlsplit(url)
    query = "&".join(p for p in parts.query.split("&") if p and not p.lower().startswith("utm_"))
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def domain_of(url: str) -> str:
    host = urlsplit(url).hostname or ""
    return host.removeprefix("www.")


def mentions_destination(text: str, destination: str) -> bool:
    """Relevance filter: the result must mention the destination or a significant word of it.

    'Washington, D.C.' is matched by 'Washington'; 'Goa' must appear as a word,
    so 'goal' does not count.
    """
    if contains_phrase(text, destination):
        return True
    words = [w for w in fold(destination).split() if len(w) >= 4]
    return any(contains_phrase(text, w) for w in words)


def normalize_results(
    batches: list[CategoryResults],
    *,
    provider: str,
    retrieved_at: datetime,
    max_content_chars: int,
) -> NormalizationOutcome:
    ordered = sorted(batches, key=lambda b: list(ResearchCategory).index(b.query.category))
    hits: list[SearchHit] = []
    seen_urls: set[str] = set()
    kept: dict[ResearchCategory, int] = {b.query.category: 0 for b in ordered}
    dropped = {"non_http_url": 0, "too_short": 0, "irrelevant": 0, "duplicate_url": 0}

    for batch in ordered:
        for item in batch.items:
            url = item.url.strip()
            if not url.startswith(("http://", "https://")):
                dropped["non_http_url"] += 1
                continue
            title = clean_text(_DELIMITER_LIKE.sub(" ", item.title)) or domain_of(url)
            content = clean_text(_DELIMITER_LIKE.sub(" ", item.content))
            if len(content) < MIN_CONTENT_CHARS:
                dropped["too_short"] += 1
                continue
            if not mentions_destination(f"{title} {content}", batch.query.destination):
                dropped["irrelevant"] += 1
                continue
            key = canonical_url(url)
            if key in seen_urls:
                dropped["duplicate_url"] += 1
                continue
            seen_urls.add(key)
            hits.append(
                SearchHit(
                    source_id=f"S{len(hits) + 1}",
                    category=batch.query.category,
                    query=batch.query.text,
                    title=title,
                    url=url,
                    domain=domain_of(url),
                    content=truncate(content, max_content_chars),
                    score=item.score,
                    provider=provider,
                    retrieved_at=retrieved_at,
                )
            )
            kept[batch.query.category] += 1
    return NormalizationOutcome(hits=hits, kept_per_category=kept, dropped=dropped)
