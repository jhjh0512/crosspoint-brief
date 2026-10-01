"""Build the Publication model. P0-1 has no LLM, so every editorial stage uses its rule fallback."""

from __future__ import annotations

from datetime import datetime

from brief.config import Config
from brief.models import Article, ContentItem, Publication, Section, SourceStatus
from brief.pipeline.select import Selection
from brief.render.sanitize import first_sentences, html_to_text, sanitize_html, xml_text

WEEKDAYS_KO = "월화수목금토일"

RULE_NOTES = [
    "선별: 점수·최근성 순 (규칙 대체, LLM 선별 미적용)",
    "요약: 입력원이 제공한 요약 또는 앞부분 발췌 (규칙 대체, LLM 요약 미적용)",
    "편집: 기본 순서와 템플릿 문구 (규칙 대체, LLM 편집 미적용)",
]


def publication_id(config: Config, now_utc: datetime) -> tuple[str, str]:
    """(publication id, local date) for the slot that `now_utc` falls in."""
    local_date = now_utc.astimezone(config.publish.tz).strftime("%Y-%m-%d")
    return f"{config.publish.slug}-{local_date}", local_date


def compose(
    config: Config, selection: Selection, statuses: list[SourceStatus], now_utc: datetime
) -> Publication:
    pub_id, local_date = publication_id(config, now_utc)
    local = now_utc.astimezone(config.publish.tz)
    title = f"{config.publish.title} {local_date} ({WEEKDAYS_KO[local.weekday()]})"

    sections: list[Section] = []
    by_source: dict[str, Section] = {}
    for item in selection.chosen:
        name = _source_name(config, item)
        section = by_source.get(item.source_id)
        if section is None:
            section = Section(title=name, articles=[])
            by_source[item.source_id] = section
            sections.append(section)
        section.articles.append(make_article(config, item, name))

    skim = [Article(item, _source_name(config, item), "", "none") for item in selection.skim]

    notes = list(RULE_NOTES)
    notes.append(
        f"후보 {selection.candidates}개 중 {len(selection.chosen)}개 선정, 거른 항목 {selection.filtered_out}개"
    )
    if not selection.chosen:
        notes.append("오늘은 조건에 맞는 새 기사가 없습니다.")

    return Publication(
        id=pub_id,
        title=title,
        author=config.publish.author,
        created_at=now_utc,
        local_date=local_date,
        sections=sections,
        skim=skim,
        sources=statuses,
        notes=notes,
        config_hash=config.fingerprint(),
        timezone=config.publish.timezone,
    )


def make_article(config: Config, item: ContentItem, source_name: str) -> Article:
    budget = config.publish.summary_max_chars
    fragment, _ = sanitize_html(item.summary_html, max_chars=budget) if item.summary_html else ("", False)
    if fragment:
        return Article(item, source_name, fragment, "feed")

    body_text = html_to_text(item.body_html) if item.body_html else ""
    if body_text:
        excerpt = first_sentences(body_text, count=3, max_chars=budget)
        return Article(item, source_name, f"<p>{xml_text(excerpt)}</p>", "excerpt")

    return Article(item, source_name, "", "none")


def _source_name(config: Config, item: ContentItem) -> str:
    source = config.source(item.source_id)
    return source.name if source else item.source_id
