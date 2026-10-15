from conftest import T0

from webhookrelay.payloads import Event
from webhookrelay.templating import TemplateRenderer


def make_event(**data):
    return Event("shop", "order.created", "evt-7", data, T0, {})


def test_plain_text_template():
    renderer = TemplateRenderer(base_url="https://relay.example/")
    text = renderer.render("chat.txt", make_event(title="Refund <requested>"))
    assert text == "[shop] order.created: Refund <requested>\nhttps://relay.example/admin/events/evt-7"
    assert renderer.render("chat.txt", make_event()).startswith("[shop] order.created\n")


def test_html_template_escapes_and_links():
    renderer = TemplateRenderer(base_url="https://relay.example")
    html = renderer.render("email.html", make_event(message="Hello <b>team</b>\nsecond line"))
    assert "<h1>Order.created from shop</h1>" in html
    assert "Hello &lt;b&gt;team&lt;/b&gt;<br>\nsecond line" in html
    assert '<a href="https://relay.example/admin/events/evt-7">evt-7</a>' in html


def test_markdown_bodies_in_html_templates():
    renderer = TemplateRenderer()
    html = renderer.render("email.html", make_event(body="**Shipped** by @octocat<script>alert(1)</script>"))
    assert "<strong>Shipped</strong>" in html
    assert "https://github.com/octocat" in html
    assert "<script>" not in html


def test_custom_templates_override_builtins():
    renderer = TemplateRenderer(
        {"chat.txt": "{{ event.type | upper }} {{ data.total }}", "note.html": "{{ data.n | nl2br }}"}
    )
    assert renderer.render("chat.txt", make_event(total=3)) == "ORDER.CREATED 3"
    assert renderer.render("note.html", make_event(n="a&b\nc")) == "a&amp;b<br>\nc"
