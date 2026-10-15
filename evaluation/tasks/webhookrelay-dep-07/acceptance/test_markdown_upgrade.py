import importlib.metadata
import re
from datetime import datetime, timezone

from webhookrelay.payloads import Event
from webhookrelay.rendering import render_markdown
from webhookrelay.templating import TemplateRenderer


def links(html):
    """(href, class, text) for every anchor, independent of attribute order."""
    found = []
    for attrs, text in re.findall(r"<a ([^>]*)>([^<]*)</a>", html):
        values = dict(re.findall(r'(\w+)="([^"]*)"', attrs))
        found.append((values.get("href"), values.get("class"), text))
    return found


def alignment(cell_html):
    match = re.search(r'align="(\w+)"|text-align:\s*(\w+)', cell_html)
    return (match.group(1) or match.group(2)) if match else None


def test_markdown_version_is_pinned():
    assert importlib.metadata.version("Markdown") == "3.7"


def test_mentions_and_issues_are_linked():
    html = str(render_markdown("Ping @octo-cat and @Bob about #12, see #7.", issue_url="https://tracker.example/i/"))
    assert links(html) == [
        ("https://github.com/octo-cat", "mention", "@octo-cat"),
        ("https://github.com/Bob", "mention", "@Bob"),
        ("https://tracker.example/i/12", "issue", "#12"),
        ("https://tracker.example/i/7", "issue", "#7"),
    ]
    assert html.startswith("<p>Ping ") and html.endswith(".</p>")


def test_mentions_inside_emphasis_and_custom_prefix():
    html = str(render_markdown("**@alice** *thanks @bob*", mention_url="https://git.example/u"))
    assert "<strong><a" in html and "<em>thanks <a" in html
    assert [href for href, _, _ in links(html)] == ["https://git.example/u/alice", "https://git.example/u/bob"]


def test_issue_links_are_off_without_a_tracker_and_code_is_untouched():
    assert links(str(render_markdown("fixes #12"))) == []
    html = str(render_markdown("Run `notify @ops #3` or mail ops@example.com", issue_url="https://t.example"))
    assert "<code>notify @ops #3</code>" in html
    assert links(html) == []
    block = str(render_markdown("```python\nprint('@ops #3')\n```", issue_url="https://t.example"))
    assert block.startswith('<pre><code class="language-python">')
    assert links(block) == [] and "@ops #3" in block


def test_table_alignment_survives():
    html = str(render_markdown("| Left | Mid | Right |\n| :--- | :-: | --: |\n| a | b | c |"))
    headers = re.findall(r"<th[^>]*>[^<]*</th>", html)
    cells = re.findall(r"<td[^>]*>[^<]*</td>", html)
    assert [alignment(h) for h in headers] == ["left", "center", "right"]
    assert [alignment(c) for c in cells] == ["left", "center", "right"]
    assert "<thead>" in html and "<tbody>" in html


def test_lists_and_untrusted_html():
    html = str(render_markdown("1. one\n2. two\n\n* a\n* b\n\n<script>alert(1)</script>"))
    assert re.search(r"<ol>\s*<li>one</li>\s*<li>two</li>\s*</ol>", html)
    assert re.search(r"<ul>\s*<li>a</li>\s*<li>b</li>\s*</ul>", html)
    assert "<script" not in html


def test_email_template_renders_markdown_body():
    event = Event("ci", "build.failed", "b-1", {"body": "Build **failed**, cc @dev"},
                  datetime(2026, 1, 1, tzinfo=timezone.utc), {})
    html = TemplateRenderer().render("email.html", event)
    assert "<strong>failed</strong>" in html
    assert ("https://github.com/dev", "mention", "@dev") in links(html)
