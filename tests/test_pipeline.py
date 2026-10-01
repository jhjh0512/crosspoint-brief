from datetime import timedelta

import pytest

from brief.connectors import FetchResult, register
from brief.connectors.base import ConnectorError
from brief.db import Database
from brief.models import ContentItem
from brief.pipeline.publish import publish
from brief.scheduler import DayState, publish_due
from conftest import NOW, make_config


class FakeConnector:
    type_name = "fake"

    def __init__(self):
        self.items: dict[str, list[ContentItem]] = {}
        self.fail: set[str] = set()

    def fetch(self, source, state, client):
        if source.id in self.fail:
            raise ConnectorError("boom")
        return FetchResult(items=list(self.items.get(source.id, [])))


@pytest.fixture
def fake():
    connector = FakeConnector()
    register(connector)
    return connector


def _item(source, n, hours_ago=1):
    return ContentItem(
        source_id=source,
        guid=f"{source}-{n}",
        title=f"{source} 기사 {n}",
        url=f"https://example.com/{source}/{n}",
        canonical_url=f"https://example.com/{source}/{n}",
        summary_html=f"<p>요약 {n}</p>",
        published_at=NOW - timedelta(hours=hours_ago),
    )


def test_publish_end_to_end(tmp_path, fake):
    config = make_config(tmp_path)
    fake.items["news"] = [_item("news", n) for n in range(3)]
    fake.fail.add("blog")
    db = Database(config.db_path)

    outcome = publish(config, db, now=NOW, client=object())
    assert not outcome.skipped
    epub = config.publications_dir / "am-2026-10-02.epub"
    assert epub.is_file() and epub.stat().st_size == outcome.record.size
    opds = (config.www_dir / "opds.xml").read_text(encoding="utf-8")
    assert 'href="/publications/am-2026-10-02.epub"' in opds
    assert outcome.record.summary == "기사 3개 · 뉴스"

    again = publish(config, db, now=NOW + timedelta(minutes=5), client=object())
    assert again.skipped and again.record.sha256 == outcome.record.sha256


def test_items_are_not_repeated_next_day(tmp_path, fake):
    config = make_config(tmp_path, window_hours=48)
    fake.items["news"] = [_item("news", 0)]
    db = Database(config.db_path)
    publish(config, db, now=NOW, client=object())

    fake.items["news"] = [_item("news", 0), _item("news", 1, hours_ago=-20)]  # one old, one new
    nxt = publish(config, db, now=NOW + timedelta(days=1), client=object())
    assert nxt.record.summary == "기사 1개 · 뉴스"


def test_force_rebuild_reuses_its_own_items(tmp_path, fake):
    config = make_config(tmp_path)
    fake.items["news"] = [_item("news", 0)]
    db = Database(config.db_path)
    publish(config, db, now=NOW, client=object())
    rebuilt = publish(config, db, now=NOW, force=True, client=object())
    assert not rebuilt.skipped and rebuilt.record.summary == "기사 1개 · 뉴스"


def test_old_publications_are_pruned(tmp_path, fake):
    config = make_config(tmp_path, keep_publications=2)
    db = Database(config.db_path)
    for day in range(3):
        publish(config, db, now=NOW + timedelta(days=day), client=object())
    live = [r.id for r in db.live_publications()]
    assert live == ["am-2026-10-04", "am-2026-10-03"]
    assert not (config.publications_dir / "am-2026-10-02.epub").exists()
    opds = (config.www_dir / "opds.xml").read_text(encoding="utf-8")
    assert "am-2026-10-02" not in opds


def test_publish_due_window_and_retry(tmp_path, fake):
    config = make_config(tmp_path)  # 06:30, retry 07:00 Asia/Seoul
    db = Database(config.db_path)
    state = DayState()
    # NOW is 2026-10-01 21:30 UTC = 10-02 06:30 KST; kst() builds other KST times on 10-02.
    kst = lambda h, m: NOW + timedelta(hours=h - 6, minutes=m - 30)  # noqa: E731

    assert not publish_due(config, db, kst(6, 29), state)
    assert publish_due(config, db, kst(6, 30), state)
    state.attempts = 1  # first attempt failed
    assert not publish_due(config, db, kst(6, 45), state)
    assert publish_due(config, db, kst(7, 0), state)
    state.attempts = 2
    assert not publish_due(config, db, kst(9, 0), state)
    # Next day resets the attempt counter.
    assert publish_due(config, db, kst(6, 31) + timedelta(days=1), state)


def test_publish_due_catches_up_after_downtime_but_not_late_at_night(tmp_path, fake):
    config = make_config(tmp_path)
    db = Database(config.db_path)
    kst = lambda h, m: NOW + timedelta(hours=h - 6, minutes=m - 30)  # noqa: E731
    assert publish_due(config, db, kst(10, 0), DayState())
    assert not publish_due(config, db, kst(13, 0), DayState())
