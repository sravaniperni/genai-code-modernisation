from conftest import BASE_TS, make_log

from releasebot.changelog import group_commits, render_entry
from releasebot.commits import parse_log
from releasebot.config import SectionConfig, parse_config
from releasebot.notes import render_markdown
from releasebot.release import plan_release
from releasebot.tags import Tag

LOG = make_log(
    "fix: second fix",
    "perf: faster startup",
    "docs: typo",
    "feat(api): second feature",
    "fix(cli): first fix",
    "revert: undo the cache change",
    "feat: first feature",
    "chore: release 1.4.2",
)


def summary(sections):
    return [(s.title, [c.description for c in s.commits]) for s in sections]


def test_sections_follow_the_default_configuration_order():
    assert summary(group_commits(parse_log(LOG))) == [
        ("Features", ["second feature", "first feature"]),
        ("Bug Fixes", ["second fix", "first fix"]),
        ("Performance Improvements", ["faster startup"]),
        ("Reverts", ["undo the cache change"]),
    ]


def test_sections_follow_a_custom_order():
    sections = [SectionConfig("perf", "Speed"), SectionConfig("fix", "Fixes"), SectionConfig("docs", "Docs"), SectionConfig("feat", "New")]
    assert summary(group_commits(parse_log(LOG), sections)) == [
        ("Speed", ["faster startup"]),
        ("Fixes", ["second fix", "first fix"]),
        ("Docs", ["typo"]),
        ("New", ["second feature", "first feature"]),
    ]
    assert group_commits(parse_log(LOG[2:3]), sections)[0].title == "Docs"
    assert group_commits(parse_log(LOG[-1:]), sections) == []


def test_rendered_changelog_order(config, now):
    plan = plan_release(config, LOG, [Tag("v1.4.2", LOG[-1].sha, BASE_TS)], now=now)
    entry = render_entry(plan, config)
    positions = [entry.index(f"### {title}") for title in ("Features", "Bug Fixes", "Performance Improvements", "Reverts")]
    assert positions == sorted(positions)
    assert entry.index("second feature") < entry.index("first feature")
    notes = render_markdown(plan, config)
    assert notes.index("### Features") < notes.index("### Bug Fixes")


def test_configured_order_from_yaml(now):
    config = parse_config("project: demo\nversion: 1.4.2\nchangelog:\n  sections:\n    - {type: fix, title: Fixed}\n    - {type: feat, title: Added}\n")
    log = make_log("feat: newest is a feature", "fix: older fix", "chore: release")
    plan = plan_release(config, log, [Tag("v1.4.2", log[-1].sha, BASE_TS)], now=now)
    assert [s.title for s in plan.sections] == ["Fixed", "Added"]
    entry = render_entry(plan, config)
    assert entry.index("### Fixed") < entry.index("### Added")
