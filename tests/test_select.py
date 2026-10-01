from dataclasses import replace
from datetime import timedelta

from brief.config import FilterConfig
from brief.models import ContentItem
from brief.pipeline.select import select
from conftest import NOW, make_config


def item(source="news", guid="g", hours_ago=1, url=None, title="제목", summary="", **kw):
    return ContentItem(
        source_id=source,
        guid=guid,
        title=title,
        url=url,
        canonical_url=url,
        summary_html=summary,
        published_at=NOW - timedelta(hours=hours_ago),
        first_seen_at=NOW - timedelta(hours=hours_ago),
        **kw,
    )


def test_window_and_history_filters(tmp_path):
    config = make_config(tmp_path)
    fresh, old, used = item(guid="a"), item(guid="b", hours_ago=30), item(guid="c")
    result = select(config, [fresh, old, used], published_ids={used.id}, now=NOW)
    assert [i.guid for i in result.chosen] == ["a"]
    assert result.filtered_out == 2


def test_recency_and_weight_rank(tmp_path):
    config = make_config(tmp_path)
    newer = item(guid="new", hours_ago=1)
    older = item(guid="old", hours_ago=10)
    light = item(source="blog", guid="blog", hours_ago=1)  # weight 0.5
    result = select(config, [older, light, newer], set(), NOW)
    assert [i.guid for i in result.chosen] == ["new", "old", "blog"]


def test_exclude_keywords_match_title_and_summary(tmp_path):
    config = replace(make_config(tmp_path), filter=FilterConfig(exclude_keywords=("광고",)))
    items = [
        item(guid="a", title="일반 글"),
        item(guid="b", title="광고 글"),
        item(guid="c", summary="<p>이건 광고</p>"),
    ]
    assert [i.guid for i in select(config, items, set(), NOW).chosen] == ["a"]


def test_same_url_from_two_sources_is_kept_once(tmp_path):
    config = make_config(tmp_path)
    url = "https://example.com/post"
    items = [item(source="blog", guid="x", url=url), item(source="news", guid="y", url=url)]
    result = select(config, items, set(), NOW)
    assert [(i.source_id, i.guid) for i in result.chosen] == [("news", "y")]  # higher weight wins


def test_article_count_and_skim_split(tmp_path):
    config = make_config(tmp_path, article_count=2, skim_count=1)
    items = [item(guid=str(n), hours_ago=n + 1) for n in range(5)]
    result = select(config, items, set(), NOW)
    assert [i.guid for i in result.chosen] == ["0", "1"]
    assert [i.guid for i in result.skim] == ["2"]
    assert result.candidates == 5
