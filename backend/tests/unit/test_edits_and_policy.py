from __future__ import annotations

from pathlib import Path

import pytest

from modernisation.agents.edits import Edit, EditError, apply_edit, apply_edits, parse_edits
from modernisation.execution.policy import ChangePolicy, PolicyViolation, safe_target


def test_parse_single_block_with_fence_and_path_line():
    text = (
        "Here is the fix:\n\nsrc/pkg/mod.py\n```python\n<<<<<<< SEARCH\n    return a / 1000\n=======\n"
        "    return a / 100\n>>>>>>> REPLACE\n```\n"
    )
    edits = parse_edits(text)
    assert edits == [Edit("src/pkg/mod.py", "    return a / 1000\n", "    return a / 100\n")]


def test_parse_multiple_blocks_and_new_file():
    text = (
        "a.py\n<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE\n\n"
        "b/new.py\n<<<<<<< SEARCH\n=======\nprint('hi')\n>>>>>>> REPLACE\n"
    )
    edits = parse_edits(text)
    assert [e.path for e in edits] == ["a.py", "b/new.py"]
    assert edits[1].search == ""


def test_parse_accepts_file_tag_as_path_line():
    text = '<file path="src/a.py">\n<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE\n</file>\n'
    assert parse_edits(text) == [Edit("src/a.py", "x = 1\n", "x = 2\n")]


def test_apply_exact_match():
    assert apply_edit("a\nb\nc\n", Edit("f", "b\n", "B\n")) == "a\nB\nc\n"


def test_apply_tolerates_trailing_whitespace():
    content = "def f():\n    return 1   \n"
    assert apply_edit(content, Edit("f", "def f():\n    return 1\n", "def f():\n    return 2\n")) == (
        "def f():\n    return 2\n"
    )


def test_apply_tolerates_uniform_indentation_loss():
    content = "class A:\n    def f(self):\n        return 1\n"
    out = apply_edit(content, Edit("f", "def f(self):\n    return 1\n", "def f(self):\n    return 2\n"))
    assert out == "class A:\n    def f(self):\n        return 2\n"


def test_ambiguous_match_rejected():
    with pytest.raises(EditError) as exc:
        apply_edit("x = 1\nx = 1\n", Edit("f", "x = 1\n", "x = 2\n"))
    assert exc.value.code == "ambiguous_match"


def test_missing_match_rejected():
    with pytest.raises(EditError) as exc:
        apply_edit("x = 1\n", Edit("f", "y = 1\n", "y = 2\n"))
    assert exc.value.code == "no_match"


def test_editing_missing_file_rejected_and_creation_allowed():
    with pytest.raises(EditError):
        apply_edits({"a.py": None}, [Edit("a.py", "x\n", "y\n")])
    assert apply_edits({"a.py": None}, [Edit("a.py", "", "new\n")])["a.py"] == "new\n"


@pytest.mark.parametrize(
    ("path", "code"),
    [
        ("../etc/passwd", "path_traversal"),
        ("src/../../x.py", "path_traversal"),
        ("/etc/passwd", "absolute_path"),
        ("C:/Windows/x", "absolute_path"),
        (".git/hooks/pre-commit", "forbidden_path"),
        ("pkg/.git/config", "forbidden_path"),
        (".github/workflows/ci.yml", "forbidden_path"),
        ("config/.env", "forbidden_path"),
        ("deploy/server.pem", "forbidden_path"),
    ],
)
def test_policy_rejects_unsafe_paths(path: str, code: str):
    with pytest.raises(PolicyViolation) as exc:
        ChangePolicy().check_path(path)
    assert exc.value.code == code


def test_policy_scope_and_forbidden_globs():
    policy = ChangePolicy(allowed_paths=["src/**", "pyproject.toml"], forbidden_paths=["src/vendor/**"])
    assert policy.check_path("./src/pkg/mod.py") == "src/pkg/mod.py"
    assert policy.check_path("pyproject.toml") == "pyproject.toml"
    with pytest.raises(PolicyViolation) as exc:
        policy.check_path("docs/index.md")
    assert exc.value.code == "out_of_scope"
    with pytest.raises(PolicyViolation) as exc:
        policy.check_path("src/vendor/lib.py")
    assert exc.value.code == "forbidden_path"


def test_policy_blocks_test_weakening_and_removal():
    policy = ChangePolicy()
    old = "def test_a():\n    assert f() == 1\n\ndef test_b():\n    assert g()\n"
    with pytest.raises(PolicyViolation) as exc:
        policy.check_content("tests/test_x.py", old, "def test_a():\n    assert f() == 1\n")
    assert exc.value.code == "test_removed"
    with pytest.raises(PolicyViolation) as exc:
        policy.check_content("tests/test_x.py", old, "import pytest\n@pytest.mark.skip\n" + old)
    assert exc.value.code == "test_weakened"
    with pytest.raises(PolicyViolation) as exc:
        policy.check_content("tests/test_x.py", old, None)
    assert exc.value.code == "test_deleted"
    policy.check_content("tests/test_x.py", old, old + "\ndef test_c():\n    assert True\n")  # adding is fine


def test_policy_can_forbid_test_changes():
    with pytest.raises(PolicyViolation) as exc:
        ChangePolicy(allow_test_changes=False).check_path("tests/test_x.py")
    assert exc.value.code == "test_change_forbidden"


def test_safe_target_refuses_symlink_escape(tmp_path: Path):
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (ws / "src" / "link").symlink_to(outside)
    with pytest.raises(PolicyViolation) as exc:
        safe_target(ws, "src/link/evil.py")
    assert exc.value.code == "symlink_path"
    assert safe_target(ws, "src/ok.py") == ws.resolve() / "src/ok.py"
