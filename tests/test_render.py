import io
import xml.parsers.expat
import zipfile
from datetime import timedelta

from brief.db import PublicationRecord
from brief.models import ContentItem, SourceStatus
from brief.pipeline.compose import compose
from brief.pipeline.select import Selection
from brief.render.epub import build_epub
from brief.render.opds import build_opds
from conftest import NOW, make_config


def _items():
    return [
        ContentItem(
            source_id="news",
            guid=f"g{n}",
            title=f"기사 {n} <특수> & 문자",
            url=f"https://news.example.kr/topic?id={n}&x=1",
            summary_html="<ul><li>요점&nbsp;하나</li><li>요점 둘</li></ul>" if n != 2 else "",
            body_html="첫 문장. 둘째 문장. 셋째. 넷째." if n == 2 else "",
            published_at=NOW - timedelta(hours=n),
            first_seen_at=NOW - timedelta(hours=n),
        )
        for n in range(1, 4)
    ]


def _publication(tmp_path):
    config = make_config(tmp_path)
    items = _items()
    selection = Selection(chosen=items[:2], skim=items[2:], candidates=3, filtered_out=0)
    statuses = [
        SourceStatus("news", "뉴스", ok=True, new_items=3, detail="ok"),
        SourceStatus("blog", "Blog", False),
    ]
    return compose(config, selection, statuses, NOW)


def _parse_xml(data: bytes) -> None:
    parser = xml.parsers.expat.ParserCreate()
    parser.Parse(data, True)


def test_compose_ids_titles_and_fallbacks(tmp_path):
    pub = _publication(tmp_path)
    assert pub.id == "am-2026-10-02"
    assert pub.title == "아침 브리핑 2026-10-02 (금)"
    kinds = [a.summary_kind for a in pub.articles]
    assert kinds == ["feed", "excerpt"]
    assert pub.articles[1].summary_html == "<p>첫 문장. 둘째 문장. 셋째.</p>"
    assert any("규칙 대체" in n for n in pub.notes)


def test_epub_container_layout(tmp_path):
    data = build_epub(_publication(tmp_path))
    zf = zipfile.ZipFile(io.BytesIO(data))
    first = zf.infolist()[0]
    assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
    assert zf.read("mimetype") == b"application/epub+zip"
    names = zf.namelist()
    for required in ("META-INF/container.xml", "OEBPS/content.opf", "OEBPS/nav.xhtml", "OEBPS/toc.ncx"):
        assert required in names


def test_every_xml_file_is_well_formed_without_entities(tmp_path):
    data = build_epub(_publication(tmp_path))
    zf = zipfile.ZipFile(io.BytesIO(data))
    for name in zf.namelist():
        if name.endswith((".xhtml", ".opf", ".ncx", ".xml")):
            content = zf.read(name)
            _parse_xml(content)
            text = content.decode("utf-8")
            assert "&nbsp;" not in text, name


def test_spine_order_and_manifest_files_exist(tmp_path):
    data = build_epub(_publication(tmp_path))
    zf = zipfile.ZipFile(io.BytesIO(data))
    opf = zf.read("OEBPS/content.opf").decode()
    spine = [line.split('"')[1] for line in opf.splitlines() if line.startswith("<itemref")]
    assert spine == ["brief", "a001", "a002", "skim", "colophon"]
    for line in opf.splitlines():
        if line.startswith("<item "):
            href = line.split('href="')[1].split('"')[0]
            assert f"OEBPS/{href}" in zf.namelist()


def test_build_is_deterministic(tmp_path):
    assert build_epub(_publication(tmp_path)) == build_epub(_publication(tmp_path))


def test_failed_source_is_reported_in_colophon(tmp_path):
    zf = zipfile.ZipFile(io.BytesIO(build_epub(_publication(tmp_path))))
    colophon = zf.read("OEBPS/text/colophon.xhtml").decode()
    assert "Blog: 실패" in colophon and "뉴스: 정상" in colophon


def _record(n: int) -> PublicationRecord:
    return PublicationRecord(
        id=f"am-2026-10-0{n}",
        kind="morning-brief",
        title=f"아침 브리핑 2026-10-0{n}",
        author="CrossPoint Brief",
        created_at=NOW,
        local_date=f"2026-10-0{n}",
        filename=f"am-2026-10-0{n}.epub",
        size=1234,
        sha256="0" * 64,
        config_hash="abc",
        summary="기사 2개 · 뉴스",
        pruned=False,
    )


def test_opds_matches_crosspoint_parser_rules():
    feed = build_opds([_record(2), _record(1)], NOW, "CrossPoint Brief", "CrossPoint Brief")
    _parse_xml(feed)

    entries, current = [], None

    def start(name, attrs):
        nonlocal current
        if name == "entry":
            current = {"links": []}
        elif name == "link" and current is not None:
            current["links"].append(attrs)

    def end(name):
        nonlocal current
        if name == "entry":
            entries.append(current)
            current = None

    parser = xml.parsers.expat.ParserCreate()
    parser.StartElementHandler, parser.EndElementHandler = start, end
    parser.Parse(feed, True)

    assert len(entries) == 2
    for entry in entries:
        books = [
            link
            for link in entry["links"]
            if "opds-spec.org/acquisition" in link.get("rel", "")
            and link.get("type") == "application/epub+zip"
        ]
        assert len(books) == 1
        # CrossPoint's UrlUtils::buildUrl only resolves "/"-prefixed paths correctly.
        assert books[0]["href"].startswith("/publications/") and books[0]["href"].endswith(".epub")
