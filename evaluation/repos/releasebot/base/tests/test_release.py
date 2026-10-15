from releasebot.commits import Commit
from releasebot.release import plan_release
from releasebot.tags import Tag
from releasebot.versioning import BumpLevel


def test_plan_release(config, log, tags):
    plan = plan_release(config, log, tags)
    assert (plan.version, plan.tag, plan.level) == ("1.5.0", "v1.5.0", BumpLevel.MINOR)
    assert (plan.previous_version, plan.previous_tag.name) == ("1.4.2", "v1.4.2")
    assert [c.sha for c in plan.commits] == [c.sha for c in log[:4]]
    assert [s.title for s in plan.sections] == ["Features", "Bug Fixes"]
    assert plan.breaking == []


def test_nothing_to_release_and_first_release(config, log, tags):
    assert plan_release(config, [Commit("f" * 40, "docs: typo"), *log[-1:]], tags) is None
    plan = plan_release(config, log, [])  # without tags the configured version is the last release
    assert plan.previous_version == "1.4.2" and plan.previous_tag is None
    assert plan.version == "1.5.0"


def test_prerelease_plans(config, log, tags):
    tags = [*tags, Tag("v1.5.0-rc.1", "c" * 40)]
    plan = plan_release(config, [Commit("d" * 40, "feat: more"), Commit("c" * 40, "feat: x"), *log], tags, prerelease=True)
    assert plan.version == "1.5.0-rc.2"
    assert plan.prerelease and plan.variables()["tag"] == "v1.5.0-rc.2"
