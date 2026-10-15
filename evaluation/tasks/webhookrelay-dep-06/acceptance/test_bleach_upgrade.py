import importlib.metadata
import re
from datetime import datetime, timezone

import pytest

from webhookrelay.payloads import Event
from webhookrelay.rendering import render_markdown, sanitize
from webhookrelay.templating import TemplateRenderer


def styles(html):
    """Map of CSS property -> value from the first style attribute in ``html``."""
    match = re.search(r'style="([^"]*)"', html)
    if not match:
        return {}
    pairs = [part.split(":", 1) for part in match.group(1).split(";") if ":" in part]
    return {name.strip(): value.strip() for name, value in pairs}


def test_bleach_version_is_pinned():
    assert importlib.metadata.version("bleach") == "6.2.0"


def test_allowed_tags_are_kept():
    html = ("<h2>T</h2><p>a<br>b</p><pre><code>x</code></pre><ul><li>i</li></ul><blockquote>q</blockquote>"
            "<del>d</del><strong>s</strong><em>e</em><hr>")
    assert sanitize(html) == html


def test_disallowed_tags_are_stripped_not_escaped():
    out = sanitize('<div><script>steal()</script><iframe src="x"></iframe><img src="a.png">ok</div>')
    assert out == "steal()ok"


def test_attributes_and_protocols():
    out = sanitize('<a href="https://x.example/a" title="t" class="mention" onclick="evil()">x</a>')
    assert re.fullmatch(r"<a [^>]+>x</a>", out)
    assert 'href="https://x.example/a"' in out and 'title="t"' in out and 'class="mention"' in out
    assert "onclick" not in out
    assert sanitize('<a href="mailto:ops@example.com">m</a>') == '<a href="mailto:ops@example.com">m</a>'
    assert "javascript" not in sanitize('<a href="javascript:alert(1)">j</a>')
    assert sanitize('<p class="x" id="y">p</p>') == "<p>p</p>"
    assert sanitize('<code class="language-py">c</code>') == '<code class="language-py">c</code>'
    table = '<table><tbody><tr><td align="center">1</td><th align="right">h</th></tr></tbody></table>'
    assert sanitize(table.replace(' align="right"', ' align="right" style="color: red"')) == table


@pytest.mark.parametrize(
    "style, expected",
    [
        ("color: red; position: fixed; font-weight: bold", {"color": "red", "font-weight": "bold"}),
        ("background-color: #fff; text-decoration: underline", {"background-color": "#fff",
                                                                  "text-decoration": "underline"}),
        ("position: absolute; top: 0", {}),
    ],
)
def test_inline_styles(style, expected):
    out = sanitize(f'<span style="{style}" class="hl">x</span>')
    assert out.startswith("<span") and out.endswith(">x</span>")
    assert 'class="hl"' in out
    assert styles(out) == expected


def test_style_is_not_allowed_on_other_tags():
    assert sanitize('<p style="color: red">p</p>') == "<p>p</p>"


def test_markdown_rendering_is_sanitised():
    html = str(render_markdown(
        "**Hi** @octocat <span style=\"color: green; position: fixed\">ok</span> <script>x()</script>\n\n"
        "| a | b |\n| :-: | --: |\n| 1 | 2 |",
    ))
    assert "<strong>Hi</strong>" in html
    assert re.search(r'<a [^>]*href="https://github.com/octocat"[^>]*>@octocat</a>', html)
    assert styles(html) == {"color": "green"}
    assert "<script" not in html
    assert re.search(r'<th align="center">a</th>\s*<th align="right">b</th>', html)


def test_html_notification_template():
    event = Event("shop", "note", "e1", {"body": "<b>bold</b> <img src=x onerror=alert(1)>"},
                  datetime(2026, 1, 1, tzinfo=timezone.utc), {})
    html = TemplateRenderer().render("email.html", event)
    assert "<b>bold</b>" in html
    assert "<img" not in html and "onerror" not in html
