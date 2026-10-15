import importlib.metadata

from conftest import make_log

from releasebot.changelog import render_entry
from releasebot.notes import render_html, render_markdown
from releasebot.release import plan_release
from releasebot.templating import build_environment


def test_jinja2_is_pinned_to_3_1_6():
    assert importlib.metadata.version("Jinja2") == "3.1.6"


def test_changelog_entry(config, log, tags, now):
    entry = render_entry(plan_release(config, log, tags, now=now), config)
    assert entry.startswith("## [1.5.0](https://git.example.com/acme/demo/compare/v1.4.2...v1.5.0) (March 5, 2026)\n")
    commit = log[0].sha
    assert f"* **API:** add pagination to the export endpoint ([{commit[:7]}](https://git.example.com/acme/demo/commit/{commit})) (closes #42)" in entry
    assert "### Bug Fixes" in entry


def test_entry_without_hosting_links(config, now):
    config.hosting.web_url = None
    config.changelog.scope_aliases = {}
    log = make_log("feat(api)!: drop the v1 endpoints\n\nBREAKING CHANGE: clients must use /v2", "chore: init")
    entry = render_entry(plan_release(config, log, [], now=now), config)
    assert entry.startswith("## 2.0.0 (March 5, 2026)\n")
    assert "* **api:** clients must use /v2" in entry
    assert f"* **api:** drop the v1 endpoints ({log[0].sha[:7]})" in entry


def test_filters_in_custom_templates(config, log, tags, now, tmp_path):
    (tmp_path / "changelog.md.j2").write_text(
        "{{ project }} {{ version }} ({{ date | release_date }})\n"
        "{% for s in sections %}{% for c in s.commits %}- {{ c.scope | scope_label }}|{{ c.sha | commit_link }}\n{% endfor %}{% endfor %}"
    )
    config.changelog.template_dirs = [str(tmp_path)]
    config.changelog.language = "de"
    entry = render_entry(plan_release(config, log, tags, now=now), config)
    lines = entry.splitlines()
    assert lines[0] == "demo 1.5.0 (5. März 2026)"
    assert lines[1] == f"- API|[{log[0].sha[:7]}](https://git.example.com/acme/demo/commit/{log[0].sha})"
    assert lines[2].startswith("- |[")


def test_environment_filters_directly():
    env = build_environment(scope_aliases={"cli": "Command line"})
    template = env.from_string("{{ sha | commit_link }} {{ 'cli' | scope_label }} {{ 'core' | scope_label }}")
    assert template.render(sha="abcdef0123", commit_url="https://h/c/{sha}") == "[abcdef0](https://h/c/abcdef0123) Command line core"
    assert env.from_string("{{ sha | commit_link }}").render(sha="abcdef0123", commit_url=None) == "abcdef0"


def test_release_notes_html(config, log, tags, now):
    config.project = "demo & <friends>"
    plan = plan_release(config, log, tags, now=now)
    html = render_html(plan, config)
    assert "<title>demo &amp; &lt;friends&gt; 1.5.0</title>" in html
    assert "<h1>demo &amp; &lt;friends&gt; 1.5.0</h1>" in html
    assert "<h3>Features</h3>" in html and "<li>" in html and "&lt;h3&gt;" not in html
    assert 'href="https://git.example.com/acme/demo/issues/42"' in html
    assert render_markdown(plan, config).startswith("### Features\n")
