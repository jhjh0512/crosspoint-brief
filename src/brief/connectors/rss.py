"""RSS 2.0 / Atom connector."""

from __future__ import annotations

import calendar
import hashlib
import html
import re
from datetime import UTC, datetime

import feedparser
import httpx

from brief.config import SourceConfig
from brief.connectors.base import ConnectorError, FetchResult
from brief.db import SourceState
from brief.models import ContentItem
from brief.urls import canonical_url

_TAG_RE = re.compile(r"<[^>]+>")


class RssConnector:
    type_name = "rss"

    def fetch(self, source: SourceConfig, state: SourceState, client: httpx.Client) -> FetchResult:
        headers = {"Accept": "application/atom+xml, application/rss+xml, application/xml;q=0.9, */*;q=0.5"}
        if state.etag:
            headers["If-None-Match"] = state.etag
        if state.last_modified:
            headers["If-Modified-Since"] = state.last_modified

        try:
            response = client.get(source.url, headers=headers)
        except httpx.HTTPError as exc:
            raise ConnectorError(f"request failed: {exc.__class__.__name__}: {exc}") from exc

        if response.status_code == 304:
            return FetchResult(not_modified=True, etag=state.etag, last_modified=state.last_modified)
        if response.status_code != 200:
            raise ConnectorError(f"HTTP {response.status_code}")

        result = parse_feed(response.content, source)
        result.etag = response.headers.get("ETag")
        result.last_modified = response.headers.get("Last-Modified")
        return result


def parse_feed(content: bytes, source: SourceConfig) -> FetchResult:
    parsed = feedparser.parse(content)
    if parsed.bozo and not parsed.entries:
        raise ConnectorError(f"unparseable feed: {parsed.get('bozo_exception')!r}")

    feed_language = parsed.feed.get("language")
    items = []
    for entry in parsed.entries:
        item = _entry_to_item(entry, source, feed_language)
        if item is not None:
            items.append(item)
    return FetchResult(items=items)


def _entry_to_item(entry, source: SourceConfig, feed_language: str | None) -> ContentItem | None:
    title = _plain_text(entry.get("title", ""))
    link = entry.get("link") or None
    if not title and not link:
        return None

    guid = entry.get("id") or link or hashlib.sha1(title.encode("utf-8")).hexdigest()

    summary_html = entry.get("summary", "") or ""
    body_html = ""
    contents = entry.get("content") or []
    if contents:
        body_html = contents[0].get("value", "") or ""
    # Atom feeds often put the same text in both; keep one copy.
    if body_html and _plain_text(body_html) == _plain_text(summary_html):
        body_html = ""
    if not summary_html and body_html:
        summary_html, body_html = body_html, ""

    published = entry.get("published_parsed") or entry.get("updated_parsed")
    published_at = datetime.fromtimestamp(calendar.timegm(published), tz=UTC) if published else None

    tags = [t.get("term") for t in entry.get("tags", []) if t.get("term")]

    return ContentItem(
        source_id=source.id,
        guid=guid,
        title=title or link,
        url=link,
        canonical_url=canonical_url(link),
        summary_html=summary_html,
        body_html=body_html,
        published_at=published_at,
        language=source.language or feed_language,
        author=entry.get("author") or None,
        tags=tags,
        ai_allowed=source.ai_allowed,
    )


def _plain_text(value: str) -> str:
    return " ".join(html.unescape(_TAG_RE.sub(" ", value)).split())
