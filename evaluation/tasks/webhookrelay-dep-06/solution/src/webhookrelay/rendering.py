"""Markdown to HTML rendering for notification bodies, followed by HTML sanitisation.

Webhook payloads are untrusted, so everything rendered here goes through :func:`sanitize`, which keeps a
small set of formatting tags, attributes and inline styles and drops everything else.
"""

from __future__ import annotations

import xml.etree.ElementTree as etree

import bleach
import markdown
from bleach.css_sanitizer import CSSSanitizer
from markdown.extensions import Extension
from markdown.inlinepatterns import Pattern
from markdown.util import AtomicString
from markupsafe import Markup

MENTION_RE = r"(?<![\w@/])@([A-Za-z0-9][A-Za-z0-9-]{0,38})\b"
ISSUE_RE = r"(?<![\w#&/])#(\d+)\b"

ALLOWED_TAGS = set(bleach.ALLOWED_TAGS) | {
    "p", "pre", "br", "hr", "h1", "h2", "h3", "h4", "del", "span",
    "table", "thead", "tbody", "tr", "th", "td",
}  # fmt: skip
ALLOWED_ATTRIBUTES = {
    **bleach.ALLOWED_ATTRIBUTES,
    "a": ["href", "title", "class"],
    "code": ["class"],
    "span": ["class", "style"],
    "th": ["align"],
    "td": ["align"],
}
ALLOWED_STYLES = ["color", "background-color", "font-weight", "text-decoration"]
CSS_SANITIZER = CSSSanitizer(allowed_css_properties=ALLOWED_STYLES)
ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


class _LinkPattern(Pattern):
    """Turns a regex match into an ``<a>`` element pointing at ``url_prefix + group``."""

    def __init__(self, pattern: str, md: markdown.Markdown, url_prefix: str, css_class: str, marker: str):
        super().__init__(pattern, md)
        self.url_prefix = url_prefix.rstrip("/")
        self.css_class = css_class
        self.marker = marker

    def handleMatch(self, m):  # noqa: N802 - Markdown API
        ref = m.group(2)
        element = etree.Element("a")
        element.set("href", f"{self.url_prefix}/{ref}")
        element.set("class", self.css_class)
        element.text = AtomicString(f"{self.marker}{ref}")  # not processed again
        return element


class RelayLinksExtension(Extension):
    """Links ``@user`` mentions and ``#123`` issue references."""

    def __init__(self, **kwargs):
        self.config = {
            "mention_url": ["https://github.com", "URL prefix for @mentions"],
            "issue_url": ["", "URL prefix for #123 references (disabled when empty)"],
        }
        super().__init__(**kwargs)

    def extendMarkdown(self, md, md_globals):  # noqa: N802 - Markdown API
        mention = _LinkPattern(MENTION_RE, md, self.getConfig("mention_url"), "mention", "@")
        md.inlinePatterns.add("relay_mention", mention, "<not_strong")
        if self.getConfig("issue_url"):
            issue = _LinkPattern(ISSUE_RE, md, self.getConfig("issue_url"), "issue", "#")
            md.inlinePatterns.add("relay_issue", issue, "<not_strong")


def sanitize(html: str) -> str:
    """Strip everything except the allowed tags, attributes, styles and URL schemes."""
    return bleach.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        css_sanitizer=CSS_SANITIZER,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    )


def render_markdown(text: str, *, mention_url: str = "https://github.com", issue_url: str = "") -> Markup:
    """Render untrusted Markdown to sanitised HTML that is safe to embed in a template."""
    links = RelayLinksExtension(mention_url=mention_url, issue_url=issue_url)
    md = markdown.Markdown(extensions=["tables", "fenced_code", "sane_lists", links], output_format="html")
    return Markup(sanitize(md.convert(text or "")))
