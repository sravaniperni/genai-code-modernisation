import os
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from webhookrelay.payloads import PayloadError, decode_body, normalise, parse_content_type

T0 = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "header, expected",
    [
        ("application/json", ("application/json", {})),
        ("Application/JSON; Charset=UTF-8", ("application/json", {"charset": "UTF-8"})),
        ("  text/plain ;  charset = latin-1  ", ("text/plain", {"charset": "latin-1"})),
        ('multipart/form-data; boundary="----=_Part;0_1"', ("multipart/form-data", {"boundary": "----=_Part;0_1"})),
        ('text/plain; title="say \\"hi\\""; charset=utf-8', ("text/plain", {"title": 'say "hi"', "charset": "utf-8"})),
        ("application/vnd.acme.event+json; version=2; charset=utf-8",
         ("application/vnd.acme.event+json", {"version": "2", "charset": "utf-8"})),
        ("application/x-www-form-urlencoded", ("application/x-www-form-urlencoded", {})),
        ("", ("application/octet-stream", {})),
        ("   ", ("application/octet-stream", {})),
        (None, ("application/octet-stream", {})),
    ],
)
def test_parse_content_type(header, expected):
    assert parse_content_type(header) == expected


def test_parameters_without_values_are_ignored():
    media_type, params = parse_content_type("text/plain; format=flowed; delsp; charset=us-ascii")
    assert media_type == "text/plain"
    assert params["charset"] == "us-ascii" and params["format"] == "flowed"


def test_charset_driven_decoding():
    assert decode_body("Grüße".encode("latin-1"), 'text/plain; charset="ISO-8859-1"') == {"text": "Grüße"}
    assert decode_body('{"name": "Zoë"}'.encode("utf-16"), "application/json; charset=utf-16") == {"name": "Zoë"}
    assert decode_body(b'{"a": 1}', "Application/Vnd.Acme+JSON") == {"a": 1}
    assert decode_body(b"a=1&b=two", "application/x-www-form-urlencoded; charset=utf-8") == {"a": "1", "b": "two"}
    assert decode_body(b"<e><data><x>1</x></data></e>", "application/xml; charset=utf-8") == {"x": "1"}
    with pytest.raises(PayloadError, match="charset|decode"):
        decode_body(b"x", "text/plain; charset=no-such-charset")
    with pytest.raises(PayloadError, match="unsupported"):
        decode_body(b"x", "image/png")


def test_normalise_uses_the_content_type_header():
    event = normalise("shop", {"Content-Type": "application/json; charset=utf-8", "X-Event-Type": "order.paid"},
                      '{"id": "o-1", "note": "café"}'.encode(), T0)
    assert (event.type, event.id, event.data["note"]) == ("order.paid", "o-1", "café")
    form = normalise("slack", {"Content-Type": "application/x-www-form-urlencoded"},
                     b"payload=%7B%22type%22%3A%22block_actions%22%7D", T0)
    assert form.type == "block_actions"


def test_cgi_is_no_longer_used():
    src = Path(os.environ["REPO_ROOT"]) / "src"
    offenders = [
        path.name
        for path in src.rglob("*.py")
        if re.search(r"^\s*(import cgi\b|from cgi import)", path.read_text(), re.MULTILINE)
    ]
    assert offenders == []
