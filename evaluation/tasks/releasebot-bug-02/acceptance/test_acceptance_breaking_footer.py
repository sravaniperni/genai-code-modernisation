from conftest import BASE_TS, make_log

from releasebot.bumping import determine_bump, next_version
from releasebot.changelog import render_entry
from releasebot.commits import Commit, parse_commit
from releasebot.release import plan_release
from releasebot.tags import Tag
from releasebot.versioning import BumpLevel


def parse(message):
    return parse_commit(Commit("c" * 40, message))


def test_breaking_change_footer_with_hyphen():
    commit = parse("feat(config): read settings from pyproject.toml\n\nBREAKING-CHANGE: .releasebot.yml is no longer read")
    assert commit.breaking
    assert commit.breaking_description == ".releasebot.yml is no longer read"


def test_hyphenated_footer_among_other_footers():
    commit = parse(
        "fix(api): stop accepting XML\n\nThe XML parser was unmaintained.\n\n"
        "Refs: #77\nBREAKING-CHANGE: requests must be JSON;\n  send Content-Type application/json\nReviewed-by: Dana"
    )
    assert commit.breaking
    assert commit.breaking_description == "requests must be JSON;\nsend Content-Type application/json"
    assert commit.references == ("77",)
    assert commit.body == "The XML parser was unmaintained."


def test_both_spellings_and_non_breaking_footers():
    assert parse("feat: x\n\nBREAKING CHANGE: old spelling still works").breaking
    assert parse("feat!: bang still works").breaking
    for message in ("fix: y\n\nRefs: #1\nReviewed-by: Bob", "fix: z\n\nThis is not a breaking change: just a remark"):
        commit = parse(message)
        assert not commit.breaking and commit.breaking_description is None


def test_hyphenated_footer_triggers_a_major_release(config, now):
    commits = [parse("fix(api): stop accepting XML\n\nBREAKING-CHANGE: requests must be JSON"), parse("feat: add retries")]
    assert determine_bump(commits) is BumpLevel.MAJOR
    assert next_version("1.4.2", commits) == "2.0.0"
    assert next_version("0.7.3", commits) == "0.8.0"

    log = make_log("fix(api): stop accepting XML\n\nBREAKING-CHANGE: requests must be JSON", "feat: add retries", "chore: release")
    plan = plan_release(config, log, [Tag("v1.4.2", log[-1].sha, BASE_TS)], now=now)
    assert plan.version == "2.0.0"
    assert [c.breaking_description for c in plan.breaking] == ["requests must be JSON"]
    entry = render_entry(plan, config)
    assert "### ⚠ BREAKING CHANGES\n\n* **API:** requests must be JSON" in entry
