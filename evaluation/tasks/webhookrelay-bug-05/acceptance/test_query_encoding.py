from datetime import datetime, timezone
from urllib.parse import parse_qs, parse_qsl, urlsplit

import httpx
import pytest

from webhookrelay.clock import FixedClock
from webhookrelay.config import load_config
from webhookrelay.delivery import Dispatcher, build_delivery_url
from webhookrelay.payloads import Event
from webhookrelay.transports import HttpxTransport

T0 = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "value",
    ["p1+urgent", "+02:00", "a b", "x&y=z", "100%", "#ops", "/path/to?q=1", "Zürich", "c++ & c#", "a;b,c", "'quoted'"],
)
def test_values_round_trip(value):
    url = build_delivery_url("https://hooks.example/in", {"v": value})
    assert parse_qs(urlsplit(url).query) == {"v": [value]}


def test_keys_round_trip_and_order_is_kept():
    params = {"label": "p1+urgent", "a key": "1", "k&=": "2", "delivery": "d-1"}
    url = build_delivery_url("https://hooks.example/in", params)
    assert parse_qsl(urlsplit(url).query) == list(params.items())


def test_existing_query_fragment_and_none_values():
    url = build_delivery_url("https://hooks.example/in?team=core&sig=a%2Bb#frag",
                             {"tz": "+02:00", "skip": None, "n": 7})
    parts = urlsplit(url)
    assert (parts.scheme, parts.netloc, parts.path, parts.fragment) == ("https", "hooks.example", "/in", "frag")
    assert parse_qsl(parts.query) == [("team", "core"), ("sig", "a+b"), ("tz", "+02:00"), ("n", "7")]
    assert build_delivery_url("https://hooks.example/in", {"skip": None}) == "https://hooks.example/in"


def test_reported_target_configuration():
    seen = []

    def handler(request):
        seen.append(request.url)
        return httpx.Response(200)

    config = load_config({
        "targets": {"alerts": {"url": "https://hooks.example/in?team=core",
                               "params": {"label": "p1+urgent", "channel": "#ops", "tz": "+02:00"}}},
        "rules": [{"targets": ["alerts"]}],
    })
    dispatcher = Dispatcher(config, transport=HttpxTransport(transport=httpx.MockTransport(handler)),
                            clock=FixedClock(T0))
    [record] = dispatcher.dispatch(Event("shop", "order.created", "o-1", {}, T0, {}))
    query = dict(parse_qsl(seen[0].query.decode()))
    assert query == {"team": "core", "label": "p1+urgent", "channel": "#ops", "tz": "+02:00",
                     "delivery": record.delivery_id}
    assert seen[0].path == "/in" and seen[0].host == "hooks.example"
