"""Turn untrusted feed HTML into a small, well-formed XHTML fragment.

CrossPoint parses chapters with expat built with XML_GE=0, so the output must be well-formed XML
and may only use the five predefined entities. HTMLParser decodes every other entity to its
character, and serialize() escapes just &, <, > and quotes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from xml.sax.saxutils import escape, quoteattr

_ALLOWED = {
    "p", "ul", "ol", "li", "blockquote", "pre", "code", "b", "strong", "i", "em", "a", "br",
    "h3", "h4", "h5", "h6", "sub", "sup", "del", "s",
}  # fmt: skip
_HEADING_MAP = {"h1": "h3", "h2": "h3"}
_DROP_CONTENT = {
    "script", "style", "iframe", "noscript", "template", "svg", "math", "object", "embed",
    "form", "button", "select", "textarea", "head", "title",
}  # fmt: skip
_VOID = {"br"}
_BLOCK = {"p", "ul", "ol", "li", "blockquote", "pre", "h3", "h4", "h5", "h6"}
_SAFE_SCHEMES = ("http://", "https://", "mailto:")
# Characters XML 1.0 forbids; expat rejects the whole chapter if any slip through.
_INVALID_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
_WS = re.compile(r"\s+")
_SENTENCE_END = re.compile(r"(?<=[.!?。])\s+")
ELLIPSIS = "…"


@dataclass
class _Node:
    tag: str | None  # None = text node
    text: str = ""
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[_Node] = field(default_factory=list)


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("root")
        self.stack = [self.root]
        self.skip_depth = 0
        self.pre_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if self.skip_depth:
            if tag in _DROP_CONTENT:
                self.skip_depth += 1
            return
        if tag in _DROP_CONTENT:
            self.skip_depth = 1
            return
        tag = _HEADING_MAP.get(tag, tag)
        if tag not in _ALLOWED:
            return  # unwrap: keep the children, drop the tag

        clean_attrs = {}
        if tag == "a":
            href = (dict(attrs).get("href") or "").strip()
            if not href.lower().startswith(_SAFE_SCHEMES):
                return
            clean_attrs["href"] = href

        # HTML's implicit closes that matter for feed snippets.
        if tag in ("p", "li") and self.stack[-1].tag == tag:
            self.stack.pop()
        node = _Node(tag, attrs=clean_attrs)
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)
            if tag == "pre":
                self.pre_depth += 1

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self.skip_depth:
            if tag in _DROP_CONTENT:
                self.skip_depth -= 1
            return
        tag = _HEADING_MAP.get(tag, tag)
        if tag not in _ALLOWED or tag in _VOID:
            return
        for depth in range(len(self.stack) - 1, 0, -1):
            if self.stack[depth].tag == tag:
                for closed in self.stack[depth:]:
                    if closed.tag == "pre":
                        self.pre_depth -= 1
                del self.stack[depth:]
                return

    def handle_data(self, data):
        if self.skip_depth or not data:
            return
        data = _INVALID_XML.sub("", data)
        if not self.pre_depth:
            data = _WS.sub(" ", data)
        parent = self.stack[-1]
        if parent.children and parent.children[-1].tag is None:
            parent.children[-1].text += data
        else:
            parent.children.append(_Node(None, text=data))


def _parse(html: str) -> _Node:
    builder = _TreeBuilder()
    builder.feed(html or "")
    builder.close()
    return builder.root


def _text_length(node: _Node) -> int:
    if node.tag is None:
        return len(node.text.strip())
    return sum(_text_length(c) for c in node.children)


def _cut_text(text: str, budget: int) -> str:
    """Cut text to roughly `budget` chars, preferring a sentence end, then a word boundary."""
    head = text[:budget]
    sentences = list(_SENTENCE_END.finditer(head))
    if sentences and sentences[-1].start() > budget // 2:
        return head[: sentences[-1].start()].rstrip() + " " + ELLIPSIS
    space = head.rfind(" ")
    if space > budget // 2:
        head = head[:space]
    return head.rstrip() + ELLIPSIS


def _truncate(node: _Node, budget: list[int], truncated: list[bool]) -> _Node | None:
    """Copy `node` while text fits in budget[0]; returns None once the budget is spent."""
    if budget[0] <= 0:
        truncated[0] = True
        return None
    if node.tag is None:
        length = len(node.text.strip())
        if length <= budget[0]:
            budget[0] -= length
            return _Node(None, text=node.text)
        cut = _cut_text(node.text, budget[0])
        budget[0] = 0
        truncated[0] = True
        return _Node(None, text=cut)
    copy = _Node(node.tag, attrs=dict(node.attrs))
    for child in node.children:
        kept = _truncate(child, budget, truncated)
        if kept is None:
            break
        copy.children.append(kept)
    return copy


def _attrs(attrs: dict[str, str]) -> str:
    return "".join(f" {k}={quoteattr(v)}" for k, v in attrs.items())


def _serialize(node: _Node) -> str:
    if node.tag is None:
        return escape(node.text)
    inner = "".join(_serialize(c) for c in node.children)
    if node.tag in _VOID:
        return f"<{node.tag}{_attrs(node.attrs)}/>"
    if node.tag in _BLOCK and not inner.strip():
        return ""  # drop empty paragraphs and list items
    return f"<{node.tag}{_attrs(node.attrs)}>{inner}</{node.tag}>"


def _serialize_root(root: _Node) -> str:
    """Block children as-is; runs of inline content wrapped in <p>; stray <li> wrapped in <ul>."""
    out: list[str] = []
    inline: list[_Node] = []
    items: list[_Node] = []

    def flush_inline():
        text = "".join(_serialize(n) for n in inline).strip()
        if text:
            out.append(f"<p>{text}</p>")
        inline.clear()

    def flush_items():
        body = "".join(_serialize(n) for n in items)
        if body:
            out.append(f"<ul>{body}</ul>")
        items.clear()

    for child in root.children:
        if child.tag == "li":
            flush_inline()
            items.append(child)
        elif child.tag in _BLOCK:
            flush_inline()
            flush_items()
            out.append(_serialize(child))
        else:
            flush_items()
            inline.append(child)
    flush_inline()
    flush_items()
    return "".join(out)


def sanitize_html(html: str, max_chars: int | None = None) -> tuple[str, bool]:
    """Return (xhtml_fragment, was_truncated). max_chars counts visible text only."""
    root = _parse(html)
    truncated = [False]
    if max_chars is not None and _text_length(root) > max_chars:
        root = _truncate(root, [max_chars], truncated) or _Node("root")
    return _serialize_root(root), truncated[0]


def html_to_text(html: str) -> str:
    root = _parse(html)
    parts: list[str] = []

    def walk(node: _Node):
        if node.tag is None:
            parts.append(node.text)
            return
        if node.tag in _BLOCK or node.tag == "br":
            parts.append(" ")
        for child in node.children:
            walk(child)
        if node.tag in _BLOCK:
            parts.append(" ")

    walk(root)
    return _WS.sub(" ", "".join(parts)).strip()


def first_sentences(text: str, count: int = 3, max_chars: int = 600) -> str:
    """Lead excerpt used when a source gives no summary (the rule-based stand-in for LLM summaries)."""
    sentences = _SENTENCE_END.split(text.strip())
    excerpt = " ".join(sentences[:count]).strip()
    if len(excerpt) > max_chars:
        excerpt = _cut_text(excerpt, max_chars)
    return excerpt


def xml_text(value: str) -> str:
    """Escape plain text for XHTML/XML element content."""
    return escape(_INVALID_XML.sub("", value or ""))


def xml_attr(value: str) -> str:
    """Escape plain text as a quoted XML attribute value (quotes included)."""
    return quoteattr(_INVALID_XML.sub("", value or ""))
