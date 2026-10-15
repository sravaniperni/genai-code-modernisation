import importlib.metadata
import re

from conftest import make_log

from releasebot.notes import markdown_to_html, render_html
from releasebot.release import plan_release

ISSUES = "https://git.example.com/acme/demo/issues/{}"
USERS = "https://git.example.com/{}"


def links(html):
    return re.findall(r"<a\b[^>]*\bhref=\"([^\"]+)\"[^>]*>([^<]*)</a>", html)


def test_markdown_is_pinned_to_3_7():
    assert importlib.metadata.version("Markdown") == "3.7"


def test_issue_and_user_references_become_links():
    html = markdown_to_html("Fixes #12 and #7, reported by @alice-b and @Bob.", issue_url=ISSUES, user_url=USERS)
    assert links(html) == [
        ("https://git.example.com/acme/demo/issues/12", "#12"),
        ("https://git.example.com/acme/demo/issues/7", "#7"),
        ("https://git.example.com/alice-b", "@alice-b"),
        ("https://git.example.com/Bob", "@Bob"),
    ]
    assert re.search(r'<a\b[^>]*class="issue"[^>]*>#12</a>', html)
    assert re.search(r'<a\b[^>]*class="user-mention"[^>]*>@alice-b</a>', html)


def test_references_in_headings_lists_and_emphasis():
    html = markdown_to_html("## Fixes for #3\n\n* **closes #4**\n* *thanks @carol*\n", issue_url=ISSUES, user_url=USERS)
    assert [text for _, text in links(html)] == ["#3", "#4", "@carol"]
    assert "<strong>" in html and "<em>" in html and "<h2>" in html


def test_things_that_are_not_references():
    text = "Mail ops@example.com, see a/#5, entity &#35;6 and `#7 @dave`\n\n```\n#8 @erin\n```\n"
    html = markdown_to_html(text, issue_url=ISSUES, user_url=USERS)
    assert links(html) == []
    assert "<code>#7 @dave</code>" in html and "#8 @erin" in html
    assert links(markdown_to_html("see #3 by @carol")) == []  # nothing configured, nothing linked


def test_only_issue_links_when_no_user_url():
    html = markdown_to_html("See #1 by @frank", issue_url=ISSUES)
    assert [text for _, text in links(html)] == ["#1"]


def test_tables_and_fenced_code_still_work():
    html = markdown_to_html("| a | b |\n|---|---|\n| #1 | 2 |\n\n```python\nprint('#2')\n```\n", issue_url=ISSUES)
    assert "<table>" in html and "<td><a" in html
    assert "<pre><code class=\"language-python\">" in html


def test_release_notes_page(config, now):
    log = make_log("fix(api): handle empty payloads\n\nCloses #12", "feat: add export (thanks @alice)", "chore: init")
    html = render_html(plan_release(config, log, [], now=now), config)
    assert "<h3>Features</h3>" in html and "<h3>Bug Fixes</h3>" in html
    found = dict((text, href) for href, text in links(html))
    assert found["#12"] == "https://git.example.com/acme/demo/issues/12"
    assert found["@alice"] == "https://git.example.com/alice"
