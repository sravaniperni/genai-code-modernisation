import subprocess

import pytest

from releasebot.errors import HookError
from releasebot.hooks import quote, render_command, run_hooks


def test_render_command_quotes_values():
    command = render_command("notify {project} {version} --text={text}", {"project": "demo", "version": "1.5.0", "text": "it's done; rm -rf /"})
    assert command == "notify demo 1.5.0 --text='it'\"'\"'s done; rm -rf /'"
    assert quote("") == "''"
    assert render_command("echo {{literal}}", {}) == "echo {literal}"


def test_unknown_placeholder():
    with pytest.raises(HookError, match="unknown placeholder"):
        render_command("deploy {target}", {"version": "1.0.0"})


def test_run_hooks_stops_at_first_failure():
    ran = []

    def runner(command, cwd):
        ran.append(command)
        return subprocess.CompletedProcess(command, 1 if "fail" in command else 0, stdout="ok")

    with pytest.raises(HookError):
        run_hooks(["build {version}", "fail", "never"], {"version": "1.0.0"}, runner=runner)
    assert ran == ["build 1.0.0", "fail"]
    assert run_hooks(["echo {version}"], {"version": "2.0.0"}, dry_run=True)[0].command == "echo 2.0.0"
