from releasebot.notes import markdown_to_html, render_html
from releasebot.release import plan_release

ISSUES = "https://git.example.com/acme/demo/issues/{}"
USERS = "https://git.example.com/{}"


def test_issue_references_become_links():
    html = markdown_to_html("Fixes #12 and #7.", issue_url=ISSUES)
    assert 'href="https://git.example.com/acme/demo/issues/12"' in html
    assert ">#12</a>" in html and ">#7</a>" in html


def test_mentions_become_links_but_emails_do_not():
    html = markdown_to_html("Thanks @alice-b! Mail ops@example.com", user_url=USERS)
    assert 'href="https://git.example.com/alice-b"' in html
    assert "ops@example.com" in html and "example.com</a>" not in html


def test_code_is_left_alone():
    html = markdown_to_html("Use `#5` here\n\n```\n#6 @bob\n```\n", issue_url=ISSUES, user_url=USERS)
    assert "<a" not in html
    assert "<a" not in markdown_to_html("see #3 by @carol")  # no URL templates configured


def test_render_html(config, log, tags, now):
    config.project = "demo <beta>"
    html = render_html(plan_release(config, log, tags, now=now), config)
    assert "<title>demo &lt;beta&gt; 1.5.0</title>" in html
    assert "<h3>Features</h3>" in html
    assert 'href="https://git.example.com/acme/demo/issues/42"' in html
