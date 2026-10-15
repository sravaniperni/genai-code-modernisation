import re

from webhookrelay.rendering import render_markdown, sanitize


def anchors(html):
    return re.findall(r"<a [^>]*>[^<]*</a>", html)


def test_mentions_and_issue_references_are_linked():
    html = render_markdown("Thanks @octo-cat, fixes #12 (cc @Bob)", issue_url="https://tracker.example/issues/")
    links = anchors(html)
    assert any('href="https://github.com/octo-cat"' in a and 'class="mention"' in a for a in links)
    assert any(a.endswith(">@octo-cat</a>") for a in links)
    assert any('href="https://tracker.example/issues/12"' in a and ">#12<" in a for a in links)
    assert any('href="https://github.com/Bob"' in a for a in links)


def test_code_and_email_addresses_are_not_linked():
    html = render_markdown("Run `notify @ops` or mail ops@example.com about #4")
    assert "<code>notify @ops</code>" in html
    assert "ops@example.com" in html
    assert anchors(html) == []


def test_untrusted_html_is_sanitised():
    html = render_markdown('Hi <script>alert(1)</script> [x](javascript:alert(1)) <img src=x onerror=alert(1)>')
    assert "<script" not in html and "onerror" not in html and "javascript:" not in html
    assert sanitize('<p onclick="x()">ok</p>') == "<p>ok</p>"


def test_table_alignment_survives_sanitising():
    html = render_markdown("| Item | Qty |\n| :--- | ---: |\n| apple | 3 |")
    assert "<table>" in html
    assert '<th align="right">Qty</th>' in html
    assert '<td align="right">3</td>' in html


def test_inline_styles_are_filtered():
    html = sanitize('<span style="color: red; position: fixed; font-weight: bold">alert</span>')
    assert html.startswith("<span") and "alert</span>" in html
    assert "color: red" in html and "font-weight: bold" in html
    assert "position" not in html
