"""Release notes: the Markdown body of a release and an HTML page where ``#12`` and ``@user`` become links."""

from __future__ import annotations

from typing import TYPE_CHECKING

import markdown
from jinja2 import Markup, escape
from markdown.extensions import Extension
from markdown.inlinepatterns import Pattern

from releasebot.changelog import render_template
from releasebot.config import ProjectConfig

if TYPE_CHECKING:
    from releasebot.release import ReleasePlan

ISSUE_PATTERN = r"(?<![\w&/#])#(\d+)\b"
MENTION_PATTERN = r"(?<![\w@/.])@([A-Za-z0-9][A-Za-z0-9-]{0,38})\b"


class ReferencePattern(Pattern):
    """Inline pattern turning ``#12`` / ``@alice`` into a link built from ``url_template``."""

    def __init__(self, pattern: str, md: markdown.Markdown, url_template: str, css_class: str, label: str):
        super().__init__(pattern, md)
        self.url_template, self.css_class, self.label = url_template, css_class, label

    def handleMatch(self, m):  # noqa: N802 - Markdown API
        element = markdown.util.etree.Element("a")
        element.set("href", self.url_template.format(m.group(2)))
        element.set("class", self.css_class)
        element.text = markdown.util.AtomicString(f"{self.label}{m.group(2)}")
        return element


class ReferenceExtension(Extension):
    def __init__(self, **kwargs):
        self.config = {
            "issue_url": ["", "URL template for #123 references ({} is replaced by the number)"],
            "user_url": ["", "URL template for @user mentions ({} is replaced by the user name)"],
        }
        super().__init__(**kwargs)

    def extendMarkdown(self, md, md_globals):  # noqa: N802 - Markdown API
        if self.getConfig("issue_url"):
            pattern = ReferencePattern(ISSUE_PATTERN, md, self.getConfig("issue_url"), "issue", "#")
            md.inlinePatterns.add("issue_reference", pattern, "<not_strong")
        if self.getConfig("user_url"):
            pattern = ReferencePattern(MENTION_PATTERN, md, self.getConfig("user_url"), "user-mention", "@")
            md.inlinePatterns.add("user_mention", pattern, "<not_strong")


def markdown_to_html(text: str, *, issue_url: str | None = None, user_url: str | None = None) -> str:
    extension = ReferenceExtension(issue_url=issue_url or "", user_url=user_url or "")
    return markdown.Markdown(extensions=[extension, "fenced_code", "tables"], output_format="html").convert(text)


def render_markdown(plan: ReleasePlan, config: ProjectConfig) -> str:
    """Markdown body used for the release on the hosting service."""
    return render_template("release.md.j2", plan, config).strip() + "\n"


def render_html(plan: ReleasePlan, config: ProjectConfig) -> str:
    """A standalone HTML page with the release notes (for e-mail or the project website)."""
    hosting = config.hosting
    body = markdown_to_html(render_markdown(plan, config), issue_url=hosting.issue_url, user_url=hosting.user_url)
    title = escape(f"{config.project} {plan.version}")
    return render_template("notes.html.j2", plan, config, autoescape=True, title=title, body=Markup(body))
