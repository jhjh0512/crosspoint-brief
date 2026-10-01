import xml.parsers.expat

from brief.render.sanitize import ELLIPSIS, first_sentences, html_to_text, sanitize_html


def assert_well_formed(fragment: str) -> None:
    parser = xml.parsers.expat.ParserCreate()
    parser.Parse(f"<root>{fragment}</root>", True)


def test_drops_scripts_and_unknown_tags_but_keeps_text():
    out, _ = sanitize_html('<div><script>evil()</script><span class="x">안녕</span><font>하세요</font></div>')
    assert "evil" not in out
    assert "span" not in out and "font" not in out
    assert "안녕" in out and "하세요" in out
    assert_well_formed(out)


def test_named_entities_become_characters():
    out, _ = sanitize_html("<p>a&nbsp;b &copy; &lt;tag&gt; &amp;</p>")
    assert "&nbsp;" not in out and "&copy;" not in out
    assert " " in out or "a b" in out
    assert "&lt;tag&gt;" in out and "&amp;" in out
    assert_well_formed(out)


def test_unsafe_links_are_unwrapped():
    out, _ = sanitize_html('<p><a href="javascript:x()">click</a> <a href="https://ok.example">ok</a></p>')
    assert "javascript" not in out
    assert '<a href="https://ok.example">ok</a>' in out
    assert ">click<" not in out and "click" in out


def test_unclosed_and_misnested_tags_are_repaired():
    out, _ = sanitize_html("<ul><li>one<li>two</ul><p>tail <b>bold")
    assert out == "<ul><li>one</li><li>two</li></ul><p>tail <b>bold</b></p>"
    assert_well_formed(out)


def test_br_is_self_closed_and_headings_are_demoted():
    out, _ = sanitize_html("<h1>Big</h1><p>a<br>b</p>")
    assert "<h3>Big</h3>" in out and "<br/>" in out
    assert_well_formed(out)


def test_loose_inline_text_is_wrapped():
    out, _ = sanitize_html("plain <b>text</b>")
    assert out == "<p>plain <b>text</b></p>"


def test_control_characters_are_removed():
    out, _ = sanitize_html("<p>bad\x00\x08char</p>")
    assert out == "<p>badchar</p>"
    assert_well_formed(out)


def test_truncation_keeps_structure_and_marks_the_cut():
    html = "<ul>" + "".join(f"<li>항목 {i} 입니다. 설명이 조금 깁니다.</li>" for i in range(20)) + "</ul>"
    out, truncated = sanitize_html(html, max_chars=60)
    assert truncated
    assert out.startswith("<ul><li>") and out.endswith("</li></ul>")
    assert ELLIPSIS in out
    assert len(html_to_text(out)) <= 70
    assert_well_formed(out)


def test_short_text_is_not_truncated():
    out, truncated = sanitize_html("<p>짧다</p>", max_chars=600)
    assert not truncated and out == "<p>짧다</p>"


def test_first_sentences():
    text = "첫 문장입니다. 둘째 문장! 셋째 문장? 넷째는 빠집니다."
    assert first_sentences(text, 3) == "첫 문장입니다. 둘째 문장! 셋째 문장?"
