from datetime import datetime, timezone

import httpx

from webhookrelay.clock import FixedClock
from webhookrelay.config import load_config
from webhookrelay.delivery import Dispatcher
from webhookrelay.payloads import Event
from webhookrelay.routing import Router, Rule
from webhookrelay.transports import HttpxTransport

T0 = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)

REPORTED_RULES = [
    {"name": "github-push", "events": ["push"], "targets": ["ci"]},
    {"name": "orders", "events": ["order.*"], "targets": ["erp"]},
    {"name": "catch-all", "targets": ["archive"]},
]


def event(type_, source="github"):
    return Event(source, type_, "e-1", {}, T0, {})


def router(specs):
    return Router([Rule.from_dict(spec, i) for i, spec in enumerate(specs)])


def test_reported_configuration():
    r = router(REPORTED_RULES)
    assert r.route(event("push")) == ["ci"]
    assert r.route(event("order.created")) == ["erp"]
    assert r.route(event("issues")) == ["archive"]


def test_reported_configuration_through_the_dispatcher():
    hosts = []

    def handler(request):
        hosts.append(request.url.host)
        return httpx.Response(200)

    config = load_config({"targets": {n: {"url": f"https://{n}.example/in"} for n in ("ci", "erp", "archive")},
                          "rules": REPORTED_RULES})
    dispatcher = Dispatcher(config, transport=HttpxTransport(transport=httpx.MockTransport(handler)),
                            clock=FixedClock(T0))
    assert [r.target for r in dispatcher.dispatch(event("push"))] == ["ci"]
    assert [r.target for r in dispatcher.dispatch(event("order.paid"))] == ["erp"]
    assert hosts == ["ci.example", "erp.example"]


def test_priorities_with_ties():
    r = router([
        {"name": "low", "targets": ["low"], "priority": -1},
        {"name": "a", "events": ["push"], "targets": ["a"], "priority": 5},
        {"name": "default-1", "targets": ["d1"]},
        {"name": "b", "events": ["push"], "targets": ["b"], "priority": 5},
        {"name": "default-2", "targets": ["d2"]},
        {"name": "top", "events": ["deploy"], "targets": ["top"], "priority": 10},
    ])
    assert r.route(event("push")) == ["a"]
    assert r.route(event("deploy")) == ["top"]
    assert r.route(event("tag")) == ["d1"]
    assert [rule.name for rule in r.matching_rules(event("push"))] == ["a"]


def test_continue_chains_follow_declaration_order():
    r = router([
        {"name": "audit", "targets": ["audit"], "continue": True},
        {"name": "metrics", "targets": ["metrics", "audit"], "continue": True},
        {"name": "pushes", "events": ["push"], "targets": ["ci"]},
        {"name": "fallback", "targets": ["archive"]},
        {"name": "urgent", "events": ["incident"], "targets": ["pager"], "priority": 3, "continue": True},
    ])
    assert r.route(event("push")) == ["audit", "metrics", "ci"]
    assert r.route(event("tag")) == ["audit", "metrics", "archive"]
    assert r.route(event("incident")) == ["pager", "audit", "metrics", "archive"]
    assert [rule.name for rule in r.matching_rules(event("push"))] == ["audit", "metrics", "pushes"]
