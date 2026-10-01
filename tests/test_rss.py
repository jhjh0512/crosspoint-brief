from datetime import UTC, datetime

import httpx
import pytest

from brief.config import SourceConfig
from brief.connectors import ConnectorError
from brief.connectors.rss import RssConnector, parse_feed
from brief.db import SourceState

SOURCE = SourceConfig(
    id="news", name="뉴스", connector="rss", url="https://news.example.kr/rss", language="ko"
)


def test_atom_entries_become_items(fixture_bytes):
    result = parse_feed(fixture_bytes("sample_atom.xml"), SOURCE)
    assert len(result.items) == 2
    first = result.items[0]
    assert first.title == "예시 프로젝트 1.0 공개 & 성능 2배 개선"
    assert first.guid == "https://news.example.kr/topic?id=101"
    assert first.url == "https://news.example.kr/topic?id=101"
    assert first.published_at == datetime(2026, 10, 1, 11, 31, 47, tzinfo=UTC)
    assert first.language == "ko"
    assert "<li>" in first.summary_html  # Atom content moved into summary when no separate summary
    assert first.source_id == "news" and first.ai_allowed


def test_rss_items_and_guid_fallback(fixture_bytes):
    source = SourceConfig(id="blog", name="Blog", connector="rss", url="https://blog.example.com/feed")
    result = parse_feed(fixture_bytes("sample_rss.xml"), source)
    assert [i.guid for i in result.items] == ["post-1", "https://blog.example.com/posts/2"]
    post = result.items[0]
    assert post.language == "en"  # from the feed when the source sets none
    assert post.tags == ["rust"]
    assert post.canonical_url == "https://blog.example.com/posts/1"
    untitled = result.items[1]
    assert untitled.title == "https://blog.example.com/posts/2"


def test_garbage_is_reported():
    with pytest.raises(ConnectorError):
        parse_feed(b"<<< not a feed", SOURCE)


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_conditional_get_and_304(fixture_bytes):
    seen = {}

    def handler(request):
        seen.update(request.headers)
        return httpx.Response(304)

    state = SourceState("news", etag='"abc"', last_modified="Wed, 01 Oct 2026 10:00:00 GMT")
    result = RssConnector().fetch(SOURCE, state, _client(handler))
    assert result.not_modified and result.etag == '"abc"'
    assert seen["if-none-match"] == '"abc"'
    assert seen["if-modified-since"] == "Wed, 01 Oct 2026 10:00:00 GMT"


def test_fetch_keeps_new_validators(fixture_bytes):
    def handler(request):
        return httpx.Response(200, content=fixture_bytes("sample_atom.xml"), headers={"ETag": '"v2"'})

    result = RssConnector().fetch(SOURCE, SourceState("news"), _client(handler))
    assert len(result.items) == 2 and result.etag == '"v2"'


def test_http_errors_raise_connector_error():
    with pytest.raises(ConnectorError, match="HTTP 503"):
        RssConnector().fetch(SOURCE, SourceState("news"), _client(lambda r: httpx.Response(503)))
