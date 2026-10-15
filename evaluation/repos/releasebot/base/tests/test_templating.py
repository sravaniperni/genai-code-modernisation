import pytest

from releasebot.errors import TemplateNotFoundError
from releasebot.templating import list_bundled_templates, load_template_source


def test_bundled_templates():
    assert list_bundled_templates() == ["changelog.md.j2", "notes.html.j2", "release.md.j2"]
    assert "{% include \"release.md.j2\" %}" in load_template_source("changelog.md.j2")


def test_search_paths_override_bundled_templates(tmp_path):
    (tmp_path / "release.md.j2").write_text("custom")
    assert load_template_source("release.md.j2", [tmp_path / "missing", tmp_path]) == "custom"
    assert load_template_source("notes.html.j2", [tmp_path]).startswith("<!DOCTYPE html>")


def test_unknown_templates():
    for name in ["missing.j2", "../cli.py", ""]:
        with pytest.raises(TemplateNotFoundError):
            load_template_source(name)
