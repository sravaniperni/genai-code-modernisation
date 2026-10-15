import pytest
from conftest import T0

from webhookrelay.payloads import Event
from webhookrelay.routing import Router, Rule, lookup


def event(type_="order.created", source="shop", data=None, headers=None):
    return Event(source, type_, "evt-1", data or {}, T0, headers or {})


def test_higher_priority_rule_wins():
    router = Router(
        [
            Rule.from_dict({"name": "catch-all", "targets": ["archive"]}, 0),
            Rule.from_dict({"name": "orders", "events": "order.*", "targets": ["crm"], "priority": 5}, 1),
        ]
    )
    assert router.route(event("order.created")) == ["crm"]
    assert router.route(event("user.deleted")) == ["archive"]


def test_continue_combines_targets_without_duplicates():
    specs = [
        {"name": "orders", "events": ["order.*"], "targets": ["crm", "audit"], "priority": 9, "continue": True},
        {"name": "shop", "sources": ["shop"], "targets": ["audit", "chat"], "priority": 3},
        {"name": "fallback", "targets": ["archive"], "priority": 1},
    ]
    router = Router([Rule.from_dict(spec, i) for i, spec in enumerate(specs)])
    assert router.route(event()) == ["crm", "audit", "chat"]
    assert [r.name for r in router.matching_rules(event(source="pos"))] == ["orders", "fallback"]


def test_header_and_payload_conditions():
    rule = Rule.from_dict(
        {"targets": ["prod"], "headers": {"X-Env": "prod*"}, "where": {"repo.owner.login": "acme", "labels.0": "bug"}}
    )
    data = {"repo": {"owner": {"login": "acme"}}, "labels": ["bug", "p1"]}
    assert rule.matches(event(data=data, headers={"X-Env": "production"}))
    assert not rule.matches(event(data=data, headers={"X-Env": "staging"}))
    assert not rule.matches(event(data=data))
    other = {"repo": {"owner": {"login": "other"}}, "labels": ["bug"]}
    assert not rule.matches(event(data=other, headers={"X-Env": "prod"}))


def test_lookup_and_unmatched_events():
    assert lookup({"a": {"b": [1, {"c": 2}]}}, "a.b.1.c") == 2
    assert not Rule.from_dict({"targets": ["x"], "where": {"a.b": None}}).matches(event(data={"a": 1}))
    assert Router([Rule.from_dict({"events": "push", "targets": ["ci"]})]).route(event("tag")) == []
    with pytest.raises(ValueError, match="no targets"):
        Rule.from_dict({"name": "empty"})
