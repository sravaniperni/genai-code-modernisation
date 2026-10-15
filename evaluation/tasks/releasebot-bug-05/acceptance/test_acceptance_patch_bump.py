import json

from click.testing import CliRunner
from conftest import BASE_TS, CONFIG_YAML, make_log

from releasebot.bumping import BumpRules, determine_bump, next_version
from releasebot.cli import cli
from releasebot.commits import Commit, parse_commit
from releasebot.release import plan_release
from releasebot.tags import Tag
from releasebot.versioning import BumpLevel


def commits(*messages):
    return [parse_commit(Commit(f"{i:040x}", m)) for i, m in enumerate(messages)]


def test_fixes_alone_bump_the_patch_version():
    assert determine_bump(commits("fix: a")) is BumpLevel.PATCH
    assert determine_bump(commits("fix(parser): a", "docs: b", "fix(fix): c")) is BumpLevel.PATCH
    assert determine_bump(commits("perf: faster")) is BumpLevel.PATCH
    assert next_version("1.4.2", commits("fix: a", "fix(cli): b")) == "1.4.3"
    assert next_version("0.3.1", commits("perf(io): faster")) == "0.3.2"
    assert next_version("1.4.2", commits("fix: a"), prerelease=True) == "1.4.3-rc.1"


def test_custom_patch_types():
    rules = BumpRules(patch_types=("fix", "deps"))
    assert next_version("2.0.0", commits("deps: bump httpx", "chore: tidy"), rules) == "2.0.1"
    assert next_version("2.0.0", commits("perf: faster"), rules) is None


def test_other_levels_are_unchanged():
    assert determine_bump(commits("docs: a", "chore(fix): b", "ci: c")) is BumpLevel.NONE
    assert determine_bump(commits("fix: a", "feat: b")) is BumpLevel.MINOR
    assert determine_bump(commits("fix!: a")) is BumpLevel.MAJOR


def test_release_plan_with_only_fixes(config, now):
    log = make_log("fix: handle empty changelog", "fix(hosting): retry on 502", "docs: readme", "chore: release 1.4.2")
    plan = plan_release(config, log, [Tag("v1.4.2", log[-1].sha, BASE_TS)], now=now)
    assert plan is not None
    assert (plan.version, plan.tag) == ("1.4.3", "v1.4.3")
    assert [s.title for s in plan.sections] == ["Bug Fixes"]


def test_cli_next_with_only_fixes(tmp_path):
    log = make_log("fix: handle empty changelog", "chore: release 1.4.2")
    (tmp_path / "c.yml").write_text(CONFIG_YAML)
    (tmp_path / "log.json").write_text(json.dumps([vars(c) for c in log]))
    (tmp_path / "tags.json").write_text(json.dumps([{"name": "v1.4.2", "sha": log[-1].sha}]))
    argv = ["--config", str(tmp_path / "c.yml"), "next", "--log", str(tmp_path / "log.json"), "--tags", str(tmp_path / "tags.json")]
    result = CliRunner().invoke(cli, argv, prog_name="releasebot")
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "1.4.3"
