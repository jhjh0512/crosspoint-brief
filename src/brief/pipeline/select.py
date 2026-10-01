"""Rule-based filtering and ranking: the first-pass filter, plus the stand-in for LLM selection."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from brief.config import Config
from brief.models import ContentItem
from brief.render.sanitize import html_to_text


@dataclass
class Selection:
    chosen: list[ContentItem]
    skim: list[ContentItem]  # candidates that did not make the cut
    candidates: int  # after filtering and dedupe
    filtered_out: int


def select(config: Config, items: list[ContentItem], published_ids: set[str], now: datetime) -> Selection:
    """Filter by window / keywords / history, dedupe by canonical URL, then rank by weight and recency."""
    window_start = now - timedelta(hours=config.publish.window_hours)
    keywords = [k.lower() for k in config.filter.exclude_keywords]

    kept: list[ContentItem] = []
    filtered = 0
    for item in items:
        source = config.source(item.source_id)
        if source is None or not source.enabled:
            filtered += 1
            continue
        when = item.sort_time
        if item.id in published_ids or when is None or when < window_start or when > now + timedelta(hours=1):
            filtered += 1
            continue
        if keywords and _matches_keyword(item, keywords):
            filtered += 1
            continue
        kept.append(item)

    ranked = sorted(kept, key=lambda i: _score(config, i, now), reverse=True)

    # Same article from several sources: keep the best-ranked copy.
    seen_urls: set[str] = set()
    deduped: list[ContentItem] = []
    for item in ranked:
        if item.canonical_url and item.canonical_url in seen_urls:
            filtered += 1
            continue
        if item.canonical_url:
            seen_urls.add(item.canonical_url)
        deduped.append(item)

    # Per-source cap, applied in rank order.
    per_source: dict[str, int] = {}
    capped: list[ContentItem] = []
    for item in deduped:
        cap = config.source(item.source_id).max_per_day
        if per_source.get(item.source_id, 0) >= cap:
            filtered += 1
            continue
        per_source[item.source_id] = per_source.get(item.source_id, 0) + 1
        capped.append(item)

    count = config.publish.article_count
    return Selection(
        chosen=capped[:count],
        skim=capped[count : count + config.publish.skim_count],
        candidates=len(capped),
        filtered_out=filtered,
    )


def _matches_keyword(item: ContentItem, keywords: list[str]) -> bool:
    haystack = f"{item.title} {html_to_text(item.summary_html)}".lower()
    return any(k in haystack for k in keywords)


def _score(config: Config, item: ContentItem, now: datetime) -> float:
    weight = config.source(item.source_id).weight
    age_hours = max(0.0, (now - item.sort_time).total_seconds() / 3600)
    recency = math.exp(-age_hours / config.publish.window_hours)
    points = item.signals.get("points", 0.0)
    popularity = 1.0 + math.log1p(points) / 5 if points > 0 else 1.0
    return weight * popularity * recency
