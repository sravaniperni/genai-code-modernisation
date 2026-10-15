from conftest import BASE_TS, make_log, sha

from releasebot.config import parse_config
from releasebot.release import plan_release
from releasebot.tags import Tag, latest_release, release_tags, version_from_tag

MONOREPO_TAGS = [
    Tag("api/v1.2.0", sha(1), BASE_TS),
    Tag("web/v3.0.0", sha(2), BASE_TS + 10),
    Tag("api/v1.3.0", sha(3), BASE_TS + 20),
    Tag("cli/v9.9.9", sha(4), BASE_TS + 30),
    Tag("v4.0.0", sha(5), BASE_TS + 40),
]


def test_only_tags_with_the_prefix_are_release_tags():
    assert version_from_tag("api/v1.3.0", "api/v") == "1.3.0"
    assert version_from_tag("web/v3.0.0", "api/v") is None
    assert version_from_tag("cli/v9.9.9", "api/v") is None
    assert version_from_tag("x1.2.3", "v") is None
    assert version_from_tag("release-1.2.3", "release-") == "1.2.3"
    assert version_from_tag("hotfix-1.2.3", "release-") is None
    assert version_from_tag("1.2.3", "") == "1.2.3"
    assert version_from_tag("v1.2.3", "") is None


def test_latest_release_per_component():
    assert [rt.tag.name for rt in release_tags(MONOREPO_TAGS, "api/v")] == ["api/v1.2.0", "api/v1.3.0"]
    assert latest_release(MONOREPO_TAGS, "api/v").version == "1.3.0"
    assert latest_release(MONOREPO_TAGS, "web/v").version == "3.0.0"
    assert latest_release(MONOREPO_TAGS, "v").tag.name == "v4.0.0"
    assert latest_release(MONOREPO_TAGS, "docs/v") is None


def test_planning_a_component_release(now):
    config = parse_config("project: api\nversion: 0.1.0\ntag_prefix: api/v\n")
    log = make_log("feat(api): add bulk export", "fix(web): layout", "chore: release api 1.3.0", "feat(web): v3")
    tags = [Tag("api/v1.3.0", log[2].sha, BASE_TS), Tag("web/v3.0.0", log[3].sha, BASE_TS)]
    plan = plan_release(config, log, tags, now=now)
    assert (plan.previous_version, plan.previous_tag.name) == ("1.3.0", "api/v1.3.0")
    assert (plan.version, plan.tag) == ("1.4.0", "api/v1.4.0")
    assert [c.description for c in plan.commits] == ["add bulk export", "layout"]
