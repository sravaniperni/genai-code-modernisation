import random

from conftest import BASE_TS, make_log, sha

from releasebot.release import plan_release
from releasebot.tags import Tag, latest_release, release_tags
from releasebot.versioning import next_prerelease, sort_versions

SPEC_ORDER = [
    "1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2", "1.0.0-beta.11",
    "1.0.0-rc.1", "1.0.0", "1.0.1-0", "1.0.1-1", "1.0.1-2.alpha", "1.0.1", "1.1.0-rc.9", "1.1.0-rc.10", "1.1.0",
]


def test_semver_precedence():
    shuffled = SPEC_ORDER[:]
    random.Random(7).shuffle(shuffled)
    assert sort_versions(shuffled) == SPEC_ORDER


def test_final_release_sorts_after_its_prereleases():
    assert sort_versions(["2.0.0", "2.0.0-rc.2", "1.9.0", "2.0.0-rc.1"]) == ["1.9.0", "2.0.0-rc.1", "2.0.0-rc.2", "2.0.0"]
    assert sort_versions(["1.0.0+build.2", "1.0.0-rc.1+build.9", "0.9.0"]) == ["0.9.0", "1.0.0-rc.1+build.9", "1.0.0+build.2"]


def test_latest_release_tag_is_the_final_release():
    tags = [Tag("v2.0.0-rc.1", sha(1)), Tag("v2.0.0", sha(3)), Tag("v2.0.0-rc.2", sha(2)), Tag("v1.9.0", sha(0))]
    assert latest_release(tags).tag.name == "v2.0.0"
    assert [rt.version for rt in release_tags(tags)] == ["1.9.0", "2.0.0-rc.1", "2.0.0-rc.2", "2.0.0"]
    assert latest_release(tags, include_prereleases=False).version == "2.0.0"


def test_release_candidates_after_rc9():
    existing = [f"1.3.0-rc.{n}" for n in range(1, 11)]
    assert next_prerelease("1.3.0", "rc", existing) == "1.3.0-rc.11"
    assert next_prerelease("1.3.0", "beta", ["1.3.0-beta.2", "1.3.0-beta.10", "1.3.0-beta.9"]) == "1.3.0-beta.11"


def test_planning_after_a_final_release(config, now):
    log = make_log("fix: handle timeouts", "feat: add retries", "chore: release 2.0.0", "fix: rc.2 fix", "feat: rc.1 work")
    tags = [Tag("v2.0.0-rc.1", log[4].sha, BASE_TS), Tag("v2.0.0-rc.2", log[3].sha, BASE_TS + 1), Tag("v2.0.0", log[2].sha, BASE_TS + 2)]
    plan = plan_release(config, log, tags, now=now)
    assert (plan.previous_version, plan.version) == ("2.0.0", "2.1.0")
    assert [c.description for c in plan.commits] == ["handle timeouts", "add retries"]


def test_planning_the_next_release_candidate(config, now):
    log = make_log("feat: more", "feat: rc work", start=200)  # the older commit is tagged rc.10
    tags = [Tag(f"v1.5.0-rc.{n}", sha(300 + n), BASE_TS) for n in range(1, 10)] + [Tag("v1.5.0-rc.10", log[1].sha, BASE_TS)]
    plan = plan_release(config, log, tags, prerelease=True, now=now)
    assert plan.previous_version == "1.5.0-rc.10"
    assert plan.version == "1.5.0-rc.11"
    assert [c.description for c in plan.commits] == ["more"]
