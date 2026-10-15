from releasebot.bumping import BumpRules, determine_bump, next_version
from releasebot.commits import Commit, parse_commit
from releasebot.versioning import BumpLevel


def commits(*messages):
    return [parse_commit(Commit(f"{i:040x}", m)) for i, m in enumerate(messages)]


def test_features_bump_minor():
    assert determine_bump(commits("feat: a", "fix: b", "docs: c")) is BumpLevel.MINOR
    assert next_version("1.4.2", commits("fix: b", "feat: a")) == "1.5.0"
    rules = BumpRules(minor_types=("feat", "deps"))
    assert next_version("1.4.2", commits("deps: bump httpx", "feat: x"), rules) == "1.5.0"
    assert determine_bump(commits("deps: bump httpx"), rules) is BumpLevel.MINOR


def test_breaking_changes_bump_major():
    assert next_version("1.4.2", commits("feat!: drop python 3.10", "fix: x")) == "2.0.0"
    # during initial development (0.x) breaking changes only bump the minor version
    assert next_version("0.3.1", commits("feat!: redesign")) == "0.4.0"
    rules = BumpRules(initial_development_minor=False)
    assert next_version("0.3.1", commits("feat!: redesign"), rules) == "1.0.0"


def test_no_release_without_relevant_commits():
    assert determine_bump(commits("docs: readme", "chore: deps", "ci: cache")) is BumpLevel.NONE
    assert next_version("1.4.2", commits("docs: readme")) is None
    assert next_version("1.4.2", []) is None


def test_prerelease_versions():
    assert next_version("1.4.2", commits("feat: a"), prerelease=True) == "1.5.0-rc.1"
    existing = ["1.5.0-rc.1"]
    assert next_version("1.5.0-rc.1", commits("feat: b"), prerelease=True, existing=existing) == "1.5.0-rc.2"
