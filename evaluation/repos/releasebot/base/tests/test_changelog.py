from releasebot.changelog import group_commits, prepend_entry, render_entry
from releasebot.commits import Commit, parse_log
from releasebot.config import SectionConfig
from releasebot.release import plan_release


def test_group_commits_uses_configured_sections(log):
    sections = group_commits(parse_log(log))
    assert [(s.title, [c.description for c in s.commits]) for s in sections] == [
        ("Features", ["add pagination to the export endpoint", "support --dry-run for every publisher"]),
        ("Bug Fixes", ["do not crash on an empty changelog"]),
    ]
    sections = group_commits(parse_log(log), [SectionConfig("feat", "New")])
    assert [s.title for s in sections] == ["New"]
    assert group_commits([], [SectionConfig("feat", "New")]) == []


def test_render_entry(config, log, tags, now):
    entry = render_entry(plan_release(config, log, tags, now=now), config)
    assert entry.startswith("## [1.5.0](https://git.example.com/acme/demo/compare/v1.4.2...v1.5.0) (March 5, 2026)")
    assert "### Features" in entry and "### Bug Fixes" in entry
    assert "* **API:** add pagination to the export endpoint" in entry
    assert "([0000006](https://git.example.com/acme/demo/commit/0000006" + "a" * 33 + ")) (closes #42)" in entry
    assert "BREAKING" not in entry


def test_render_entry_lists_breaking_changes(config, now):
    log = [Commit("b" * 40, "feat(api)!: remove v1\n\nBREAKING CHANGE: /v1 is gone"), Commit("a" * 40, "chore: x")]
    entry = render_entry(plan_release(config, log, [], now=now), config)
    assert "## 2.0.0 (March 5, 2026)" in entry
    assert "### ⚠ BREAKING CHANGES\n\n* **API:** /v1 is gone" in entry


def test_custom_template_directory(config, log, tags, now, tmp_path):
    (tmp_path / "changelog.md.j2").write_text("Release {{ version }} on {{ date | release_date }}\n")
    config.changelog.template_dirs = [str(tmp_path)]
    assert render_entry(plan_release(config, log, tags, now=now), config) == "Release 1.5.0 on March 5, 2026\n"


def test_prepend_entry():
    first = prepend_entry("", "## 1.0.0\n\n* a\n")
    assert first == "# Changelog\n\n## 1.0.0\n\n* a\n"
    second = prepend_entry(first, "## 1.1.0\n\n* b\n")
    assert second.index("## 1.1.0") < second.index("## 1.0.0")
    assert second.startswith("# Changelog\n")
