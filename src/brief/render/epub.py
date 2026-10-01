"""EPUB 3 writer shaped for CrossPoint.

- One article = one spine item, so TOC jumps and (later) bookmarks map to articles.
- Both nav.xhtml and toc.ncx: CrossPoint ships parsers for each.
- Only well-formed XHTML with predefined entities (expat, XML_GE=0).
- No embedded fonts: the reader uses the SD-card CJK font the user installed.
- Deterministic zip (fixed order and timestamps): same publication -> same bytes -> same sha256.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from brief import __version__
from brief.models import Article, Publication
from brief.render.sanitize import xml_attr, xml_text

_XHTML_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{lang}" lang="{lang}">
<head>
<meta charset="utf-8"/>
<title>{title}</title>
<link rel="stylesheet" type="text/css" href="../style.css"/>
</head>
<body>
{body}
</body>
</html>
"""

_CSS = """body { margin: 0; }
h1 { font-size: 1.3em; margin: 0 0 0.8em 0; }
h1.section { font-size: 1.05em; margin: 0 0 0.6em 0; }
h2 { font-size: 1.2em; margin: 0 0 0.4em 0; }
p.meta { font-size: 0.85em; margin: 0 0 0.8em 0; }
p.label { font-size: 0.8em; font-style: italic; margin: 0.8em 0 0.2em 0; }
p.link { font-size: 0.8em; margin: 0.2em 0 0 0; }
blockquote { margin: 0.5em 0 0.5em 1em; }
li { margin: 0 0 0.3em 0; }
"""

_SUMMARY_LABEL = {
    "feed": "입력원 제공 요약",
    "excerpt": "앞부분 발췌",
    "none": "원문 추출 실패, 제목만",
}


@dataclass
class _Doc:
    id: str
    href: str  # relative to OEBPS/
    title: str
    body: str


@dataclass
class _TocEntry:
    title: str
    href: str
    children: list[_TocEntry]


def book_uuid(publication_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"crosspoint-brief:{publication_id}"))


def build_epub(pub: Publication) -> bytes:
    docs, toc = _documents(pub)
    created = pub.created_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    uid = f"urn:uuid:{book_uuid(pub.id)}"

    files: list[tuple[str, str]] = [
        ("META-INF/container.xml", _container()),
        ("OEBPS/content.opf", _opf(pub, docs, uid, created)),
        ("OEBPS/nav.xhtml", _nav(pub, toc)),
        ("OEBPS/toc.ncx", _ncx(pub, docs, toc, uid)),
        ("OEBPS/style.css", _CSS),
    ]
    files += [(f"OEBPS/{d.href}", _xhtml(pub.language, d.title, d.body)) for d in docs]

    stamp = _zip_time(pub.created_at)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        # The mimetype entry must come first and be stored uncompressed.
        zf.writestr(_zinfo("mimetype", stamp, zipfile.ZIP_STORED), b"application/epub+zip")
        for name, text in files:
            zf.writestr(_zinfo(name, stamp, zipfile.ZIP_DEFLATED), text.encode("utf-8"))
    return buffer.getvalue()


def _zinfo(name: str, stamp: tuple[int, ...], compress: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=stamp)
    info.compress_type = compress
    info.external_attr = 0o644 << 16
    return info


def _zip_time(value: datetime) -> tuple[int, int, int, int, int, int]:
    return (value.year, value.month, value.day, value.hour, value.minute, value.second - value.second % 2)


# --- documents ------------------------------------------------------------------------------------


def _documents(pub: Publication) -> tuple[list[_Doc], list[_TocEntry]]:
    docs: list[_Doc] = []
    toc: list[_TocEntry] = []

    docs.append(_Doc("brief", "text/brief.xhtml", "오늘의 3줄", _brief_body(pub)))
    toc.append(_TocEntry("오늘의 3줄", "text/brief.xhtml", []))

    number = 0
    for section in pub.sections:
        section_entry = None
        for index, article in enumerate(section.articles):
            number += 1
            href = f"text/a{number:03d}.xhtml"
            heading = f'<h1 class="section">{xml_text(section.title)}</h1>\n' if index == 0 else ""
            docs.append(
                _Doc(f"a{number:03d}", href, article.item.title, heading + _article_body(pub, article))
            )
            if section_entry is None:
                section_entry = _TocEntry(section.title, href, [])
                toc.append(section_entry)
            section_entry.children.append(_TocEntry(article.item.title, href, []))

    if pub.skim:
        docs.append(_Doc("skim", "text/skim.xhtml", "제목만 훑어보기", _skim_body(pub)))
        toc.append(_TocEntry("제목만 훑어보기", "text/skim.xhtml", []))

    docs.append(_Doc("colophon", "text/colophon.xhtml", "발행 정보", _colophon_body(pub)))
    toc.append(_TocEntry("발행 정보", "text/colophon.xhtml", []))
    return docs, toc


def _brief_body(pub: Publication) -> str:
    articles = pub.articles
    lines = [f"<h1>{xml_text(pub.title)}</h1>"]
    if not articles:
        lines.append("<p>오늘은 조건에 맞는 새 기사가 없습니다.</p>")
        return "\n".join(lines)
    sources = ", ".join(s.title for s in pub.sections)
    lines.append(f"<p>{xml_text(sources)}에서 기사 {len(articles)}개를 골랐습니다. 먼저 볼 만한 글:</p>")
    lines.append("<ul>")
    lines += [f"<li>{xml_text(a.item.title)}</li>" for a in articles[:3]]
    lines.append("</ul>")
    lines.append('<p class="label">LLM 편집이 꺼져 있어 상위 기사 제목으로 대신합니다.</p>')
    return "\n".join(lines)


def _article_body(pub: Publication, article: Article) -> str:
    item = article.item
    meta = [article.source_name]
    if item.published_at:
        meta.append(_local_time(pub, item.published_at))
    for key, label in (("points", "추천"), ("comments", "댓글")):
        if key in item.signals:
            meta.append(f"{label} {int(item.signals[key])}")

    parts = [f"<h2>{xml_text(item.title)}</h2>", f'<p class="meta">{xml_text(" · ".join(meta))}</p>']
    if article.summary_html:
        parts.append(f'<div class="summary">{article.summary_html}</div>')
    parts.append(f'<p class="label">{_SUMMARY_LABEL[article.summary_kind]}</p>')
    if item.url:
        parts.append(f'<p class="link">원문: <a href={xml_attr(item.url)}>{xml_text(item.url)}</a></p>')
    return "\n".join(parts)


def _skim_body(pub: Publication) -> str:
    lines = ["<h1>제목만 훑어보기</h1>", "<ul>"]
    lines += [f"<li>{xml_text(a.item.title)} <span>({xml_text(a.source_name)})</span></li>" for a in pub.skim]
    lines.append("</ul>")
    return "\n".join(lines)


def _colophon_body(pub: Publication) -> str:
    created_local = _local_time(pub, pub.created_at, with_date=True)
    lines = ["<h1>발행 정보</h1>", f"<p>생성: {xml_text(created_local)}</p>", "<h2>입력원</h2>", "<ul>"]
    if not pub.sources:
        lines.append("<li>이번 실행에서는 수집하지 않고 저장된 항목만 사용했습니다.</li>")
    for status in pub.sources:
        state = "정상" if status.ok else "실패"
        lines.append(f"<li>{xml_text(status.name)}: {state} — {xml_text(status.detail)}</li>")
    lines += ["</ul>", "<h2>처리</h2>", "<ul>"]
    lines += [f"<li>{xml_text(note)}</li>" for note in pub.notes]
    lines += [
        "</ul>",
        f"<p>설정 버전 {xml_text(pub.config_hash)} · crosspoint-brief {__version__}</p>",
    ]
    return "\n".join(lines)


def _local_time(pub: Publication, value: datetime, with_date: bool = False) -> str:
    local = value.astimezone(ZoneInfo(pub.timezone))
    return local.strftime("%Y-%m-%d %H:%M") if with_date else local.strftime("%m-%d %H:%M")


# --- package files --------------------------------------------------------------------------------


def _xhtml(lang: str, title: str, body: str) -> str:
    return _XHTML_TEMPLATE.format(lang=lang, title=xml_text(title), body=body)


def _container() -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
        "<rootfiles>\n"
        '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>\n'
        "</rootfiles>\n"
        "</container>\n"
    )


def _opf(pub: Publication, docs: list[_Doc], uid: str, created: str) -> str:
    manifest = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
        '<item id="css" href="style.css" media-type="text/css"/>',
    ]
    manifest += [f'<item id="{d.id}" href="{d.href}" media-type="application/xhtml+xml"/>' for d in docs]
    spine = [f'<itemref idref="{d.id}"/>' for d in docs]
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" '
        f'xml:lang="{pub.language}">\n'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f'<dc:identifier id="bookid">{uid}</dc:identifier>\n'
        f"<dc:title>{xml_text(pub.title)}</dc:title>\n"
        f"<dc:creator>{xml_text(pub.author)}</dc:creator>\n"
        f"<dc:language>{pub.language}</dc:language>\n"
        f"<dc:date>{created}</dc:date>\n"
        "<dc:publisher>crosspoint-brief</dc:publisher>\n"
        f'<meta property="dcterms:modified">{created}</meta>\n'
        "</metadata>\n"
        "<manifest>\n" + "\n".join(manifest) + "\n</manifest>\n"
        '<spine toc="ncx">\n' + "\n".join(spine) + "\n</spine>\n"
        "</package>\n"
    )


def _nav(pub: Publication, toc: list[_TocEntry]) -> str:
    def render(entries: list[_TocEntry]) -> str:
        items = []
        for e in entries:
            link = f"<a href={xml_attr(e.href)}>{xml_text(e.title)}</a>"
            child = f"<ol>{render(e.children)}</ol>" if e.children else ""
            items.append(f"<li>{link}{child}</li>")
        return "".join(items)

    body = f'<nav epub:type="toc" id="toc"><h1>목차</h1><ol>{render(toc)}</ol></nav>'
    return _XHTML_TEMPLATE.format(lang=pub.language, title="목차", body=body).replace(
        '<link rel="stylesheet" type="text/css" href="../style.css"/>',
        '<link rel="stylesheet" type="text/css" href="style.css"/>',
    )


def _ncx(pub: Publication, docs: list[_Doc], toc: list[_TocEntry], uid: str) -> str:
    play_order = {d.href: i + 1 for i, d in enumerate(docs)}
    counter = [0]

    def render(entries: list[_TocEntry]) -> str:
        out = []
        for e in entries:
            counter[0] += 1
            out.append(
                f'<navPoint id="np{counter[0]}" playOrder="{play_order[e.href]}">'
                f"<navLabel><text>{xml_text(e.title)}</text></navLabel>"
                f"<content src={xml_attr(e.href)}/>{render(e.children)}</navPoint>"
            )
        return "".join(out)

    depth = 2 if any(e.children for e in toc) else 1
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" xml:lang="{pub.language}">\n'
        f'<head><meta name="dtb:uid" content="{uid}"/><meta name="dtb:depth" content="{depth}"/>'
        '<meta name="dtb:totalPageCount" content="0"/><meta name="dtb:maxPageNumber" content="0"/></head>\n'
        f"<docTitle><text>{xml_text(pub.title)}</text></docTitle>\n"
        f"<navMap>{render(toc)}</navMap>\n"
        "</ncx>\n"
    )
