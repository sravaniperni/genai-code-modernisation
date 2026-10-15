from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel

from modernisation.agents.states import TRANSITIONS, IllegalTransition, TaskState, check_transition
from modernisation.llm.base import CallRecord, ChatMessage, ModelError, Pricing, RetryPolicy
from modernisation.llm.providers import AnthropicClient, OpenAICompatibleClient
from modernisation.llm.structured import StructuredOutputError, complete_structured, extract_json
from modernisation.log import REDACTED, redact, register_secret
from modernisation.repository_intelligence.languages import (
    detect_language,
    is_config_path,
    is_test_path,
    module_name_for_path,
)
from modernisation.repository_intelligence.python_parser import parse_python

# --- state machine ------------------------------------------------------------------------------------


def test_terminal_states_only_restart_to_queued():
    for state in (TaskState.FAILED, TaskState.CANCELLED, TaskState.ESCALATED):
        assert TRANSITIONS[state] == frozenset({TaskState.QUEUED})
    assert TRANSITIONS[TaskState.COMPLETED] == frozenset()


def test_publishing_only_reachable_through_approval():
    sources = [s for s, targets in TRANSITIONS.items() if TaskState.PUBLISHING in targets]
    assert sources == [TaskState.AWAITING_APPROVAL]


@pytest.mark.parametrize(
    ("a", "b"), [("QUEUED", "COMPLETED"), ("TESTING", "PUBLISHING"), ("COMPLETED", "QUEUED"), ("PLANNING", "TESTING")]
)
def test_illegal_transitions_rejected(a: str, b: str):
    with pytest.raises(IllegalTransition):
        check_transition(a, b)


def test_every_nonterminal_state_can_be_cancelled():
    for state, targets in TRANSITIONS.items():
        if state not in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED, TaskState.ESCALATED):
            assert TaskState.CANCELLED in targets


# --- classification and parsing ------------------------------------------------------------------------


def test_path_classification():
    assert detect_language("src/a.py") == "python"
    assert detect_language("requirements-dev.txt") == "requirements"
    assert is_test_path("tests/test_a.py") and is_test_path("pkg/a_test.py") and is_test_path("conftest.py")
    assert not is_test_path("src/testing_utils_impl.txt")
    assert is_config_path("pyproject.toml") and is_config_path(".github/workflows/ci.yml")
    assert module_name_for_path("src/pkg/sub/mod.py") == "pkg.sub.mod"
    assert module_name_for_path("pkg/__init__.py") == "pkg"


def test_python_parser_extracts_structure():
    src = b'''
import os, yaml as y
from .models import LineItem as LI
from . import util

class Repo(Base):
    """Repository docs."""
    LIMIT = 5

    @property
    def size(self) -> int:
        return len(os.listdir("."))

def load(path):
    with open(path) as fh:
        return y.load(fh)
'''
    parsed = parse_python(src)
    kinds = {(s.qualified_name, s.kind) for s in parsed.symbols}
    assert ("Repo", "class") in kinds and ("Repo.size", "method") in kinds and ("load", "function") in kinds
    assert ("Repo.LIMIT", "variable") in kinds
    repo_sym = next(s for s in parsed.symbols if s.name == "Repo")
    assert repo_sym.docstring == "Repository docs."
    size = next(s for s in parsed.symbols if s.name == "size")
    assert size.start_line == 10  # decorator line included
    imports = {(i.module, i.name, i.alias, i.level) for i in parsed.imports}
    assert ("yaml", None, "y", 0) in imports
    assert ("models", "LineItem", "LI", 1) in imports
    assert ("", "util", None, 1) in imports
    calls = {(r.qualifier, r.name) for r in parsed.references if r.kind == "call"}
    assert ("y", "load") in calls and ("os", "listdir") in calls


def test_parser_tolerates_syntax_errors():
    parsed = parse_python(b"def ok():\n    return 1\n\ndef broken(:\n")
    assert parsed.has_errors
    assert any(s.name == "ok" for s in parsed.symbols)


# --- log redaction -----------------------------------------------------------------------------------------


def test_redaction_masks_known_secrets_and_token_formats():
    register_secret("super-secret-value-123")
    text = (
        "token=super-secret-value-123 " + "ghp" + "_" + "b" * 32 + " "
        "Authorization: Bearer abc.def.ghi https://user:pass@github.com/x"
    )
    out = redact(text)
    assert "super-secret-value-123" not in out and "ghp_" not in out and "abc.def.ghi" not in out
    assert "user:pass" not in out
    assert out.count(REDACTED) >= 4


# --- model adapters (HTTP transport simulated; no claim about model quality) -----------------------------


def _client(handler, *, sink=None, cls=OpenAICompatibleClient, **kw):
    return cls(
        base_url="http://model.test/v1",
        model="m",
        api_key="test-api-key",
        timeout_s=5,
        max_output_tokens=50,
        temperature=0,
        retry=RetryPolicy(max_retries=2, sleep=lambda s: None),
        pricing=Pricing(1.0, 2.0),
        sink=sink,
        transport=httpx.MockTransport(handler),
        **kw,
    )


def test_openai_compatible_retries_transient_errors_and_records_every_attempt():
    attempts = {"n": 0}
    records: list[CallRecord] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise httpx.ConnectError("connection reset")
        if attempts["n"] == 2:
            return httpx.Response(429, headers={"retry-after": "0"}, json={"error": "rate"})
        body = json.loads(request.content)
        assert body["response_format"]["type"] == "json_schema"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"a": 1}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
            },
        )

    client = _client(handler, sink=records.append)
    out = client.complete([ChatMessage("user", "hi")], purpose="t", json_schema={"type": "object"})
    assert out.text == '{"a": 1}'
    assert [r.status for r in records] == ["error", "error", "ok"]
    assert records[-1].cost_usd == pytest.approx(1000 / 1e6 * 1.0 + 500 / 1e6 * 2.0)


def test_non_retryable_error_is_raised_immediately():
    records: list[CallRecord] = []
    client = _client(lambda r: httpx.Response(400, json={"error": "bad"}), sink=records.append)
    with pytest.raises(ModelError) as exc:
        client.complete([ChatMessage("user", "hi")], purpose="t")
    assert not exc.value.retryable and len(records) == 1


def test_retries_exhausted_raises_retryable_error():
    client = _client(lambda r: httpx.Response(503, text="overloaded"))
    with pytest.raises(ModelError) as exc:
        client.complete([ChatMessage("user", "hi")], purpose="t")
    assert exc.value.retryable


def test_llamacpp_structured_mode_payload():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}], "usage": {}})

    _client(handler, structured_mode="json_object_schema").complete(
        [ChatMessage("user", "x")], purpose="t", json_schema={"type": "object"}
    )
    assert seen["response_format"] == {"type": "json_object", "schema": {"type": "object"}}


def test_anthropic_uses_forced_tool_for_structured_output():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "content": [{"type": "tool_use", "name": "Out", "input": {"a": 2}}],
                "usage": {"input_tokens": 10, "output_tokens": 3},
                "stop_reason": "tool_use",
            },
        )

    client = _client(handler, cls=AnthropicClient)
    out = client.complete(
        [ChatMessage("system", "sys"), ChatMessage("user", "x")],
        purpose="t",
        json_schema={"type": "object"},
        schema_name="Out",
    )
    assert seen["url"].endswith("/v1/messages") and seen["system"] == "sys"
    assert seen["tool_choice"] == {"type": "tool", "name": "Out"}
    assert out.structured == {"a": 2} and out.prompt_tokens == 10


class _Out(BaseModel):
    value: int


def test_structured_output_correction_round():
    replies = iter(["not json at all", '```json\n{"value": 7}\n```'])
    client = _client(
        lambda r: httpx.Response(200, json={"choices": [{"message": {"content": next(replies)}}], "usage": {}})
    )
    result, _raw = complete_structured(client, [ChatMessage("user", "x")], _Out, purpose="t")
    assert result.value == 7


def test_structured_output_gives_up_after_bounded_rounds():
    client = _client(
        lambda r: httpx.Response(200, json={"choices": [{"message": {"content": '{"value": "x"}'}}], "usage": {}})
    )
    with pytest.raises(StructuredOutputError):
        complete_structured(client, [ChatMessage("user", "x")], _Out, purpose="t", correction_rounds=1)


def test_extract_json_handles_prose():
    assert extract_json('Sure! {"a": {"b": 1}} hope that helps') == {"a": {"b": 1}}
