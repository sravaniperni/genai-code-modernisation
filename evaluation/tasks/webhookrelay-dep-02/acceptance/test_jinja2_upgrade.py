import importlib.metadata
from datetime import datetime, timezone

import httpx

from webhookrelay.clock import FixedClock
from webhookrelay.config import load_config
from webhookrelay.delivery import Dispatcher
from webhookrelay.payloads import Event
from webhookrelay.templating import TemplateRenderer
from webhookrelay.transports import HttpxTransport

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def event(**data):
    return Event("shop", "order.created", "evt-42", data, T0, {})


def test_jinja2_version_is_pinned():
    assert importlib.metadata.version("Jinja2") == "3.1.6"


def test_chat_template_output_is_unchanged():
    renderer = TemplateRenderer(base_url="https://relay.example/")
    assert renderer.render("chat.txt", event(title="Refund <requested> & approved")) == (
        "[shop] order.created: Refund <requested> & approved\nhttps://relay.example/admin/events/evt-42"
    )
    assert renderer.render("chat.txt", event()) == "[shop] order.created\nhttps://relay.example/admin/events/evt-42"


def test_email_template_output_is_unchanged():
    renderer = TemplateRenderer(base_url="https://relay.example")
    html = renderer.render("email.html", event(message='Hi <b>"team"</b>\nline two\nline & three'))
    assert html == (
        "<h1>Order.created from shop</h1>\n"
        "<p>Hi &lt;b&gt;&#34;team&#34;&lt;/b&gt;<br>\nline two<br>\nline &amp; three</p>\n"
        '<p>Event <a href="https://relay.example/admin/events/evt-42">evt-42</a></p>'
    )


def test_markdown_body_in_email_template():
    html = TemplateRenderer().render("email.html", event(body="**Done** by @octocat <script>x()</script>"))
    assert '<div class="body"><p><strong>Done</strong> by ' in html
    assert 'href="https://github.com/octocat"' in html
    assert "<script>" not in html and "&lt;script&gt;" not in html


def test_filters_in_custom_templates():
    renderer = TemplateRenderer(
        {
            "note.html": "{{ data.text | nl2br }}|{{ event.id | event_link }}",
            "note.txt": "{{ data.text | nl2br }}|{{ event.id | event_link }}",
            "raw.html": "{{ data.text }}",
        },
        base_url="https://r.example",
    )
    text = "a < b\nc"
    assert renderer.render("note.html", event(text=text)) == (
        'a &lt; b<br>\nc|<a href="https://r.example/admin/events/evt-42">evt-42</a>'
    )
    assert renderer.render("note.txt", event(text=text)) == "a < b\nc|https://r.example/admin/events/evt-42"
    assert renderer.render("raw.html", event(text="<i>x</i>")) == "&lt;i&gt;x&lt;/i&gt;"


def test_templated_delivery():
    seen = []

    def handler(request):
        request.read()
        seen.append(request)
        return httpx.Response(200)

    config = load_config({
        "base_url": "https://relay.example",
        "targets": {
            "chat": {"url": "https://chat.example/in", "template": "chat.txt"},
            "mail": {"url": "https://mail.example/in", "template": "email.html"},
        },
        "rules": [{"targets": ["chat", "mail"]}],
    })
    dispatcher = Dispatcher(config, transport=HttpxTransport(transport=httpx.MockTransport(handler)),
                            clock=FixedClock(T0))
    records = dispatcher.dispatch(event(title="Paid", message="ok"))
    assert [r.status for r in records] == [200, 200]
    chat, mail = seen
    assert chat.headers["content-type"] == "text/plain; charset=utf-8"
    assert chat.content.decode() == "[shop] order.created: Paid\nhttps://relay.example/admin/events/evt-42"
    assert mail.headers["content-type"] == "text/html; charset=utf-8"
    assert "<p>ok</p>" in mail.content.decode()
