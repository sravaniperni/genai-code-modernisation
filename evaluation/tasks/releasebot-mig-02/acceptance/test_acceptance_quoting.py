import os
import re
from pathlib import Path

import pytest

from releasebot.errors import HookError
from releasebot.hooks import quote, render_command, run_hooks
from releasebot.plugins import PublishContext
from releasebot.publishers import HooksPublisher
from releasebot.release import plan_release

NASTY = "it's \"done\"; $(touch pwned) `id` & | > < \\ *.py\n2nd line"


def test_quote_matches_posix_shell_rules():
    assert quote("1.5.0") == "1.5.0"
    assert quote("") == "''"
    assert quote("two words") == "'two words'"
    assert quote("it's") == "'it'\"'\"'s'"
    assert quote(42) == "42"
    assert quote("v1.5.0+build/7@x") == "v1.5.0+build/7@x"


def test_render_command():
    command = render_command("notify --project={project} {note} {{literal}}", {"project": "my app", "note": "a;b"})
    assert command == "notify --project='my app' 'a;b' {literal}"
    with pytest.raises(HookError):
        render_command("deploy {target}", {})


def test_values_survive_a_real_shell(tmp_path):
    results = run_hooks(["printf '%s' {text}"], {"text": NASTY}, cwd=tmp_path)
    assert results[0].returncode == 0
    assert results[0].output == NASTY
    assert not (tmp_path / "pwned").exists()


def test_hooks_publisher_runs_commands(config, log, tags, tmp_path):
    config.hooks = ["printf '%s\\n' {project} {version} {tag} > hook-output.txt", "test {previous_version} = 1.4.2"]
    plan = plan_release(config, log, tags)
    assert HooksPublisher(config).publish(plan, PublishContext(tmp_path)) == "ran 2 hook(s)"
    assert (tmp_path / "hook-output.txt").read_text() == "demo\n1.5.0\nv1.5.0\n"
    config.hooks = ["exit 3"]
    with pytest.raises(HookError):
        HooksPublisher(config).publish(plan, PublishContext(tmp_path))


def test_pipes_module_is_not_used():
    root = Path(os.environ.get("REPO_ROOT", ".")) / "src"
    for path in root.rglob("*.py"):
        assert not re.search(r"^\s*(import pipes|from pipes import)", path.read_text(), re.MULTILINE), path
