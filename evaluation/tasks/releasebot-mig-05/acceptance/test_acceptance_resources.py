import os
import re
from pathlib import Path

import pytest

from releasebot.errors import TemplateNotFoundError
from releasebot.templating import list_bundled_templates, load_template_source

LEGACY_NAMES = r"(read_text|open_text|read_binary|open_binary|contents|is_resource|path)"
LEGACY_CALL = re.compile(rf"\bresources\.{LEGACY_NAMES}\(")
LEGACY_IMPORT = re.compile(rf"from importlib\.resources import [^\n]*\b{LEGACY_NAMES}\b")


def test_bundled_templates_are_listed():
    assert list_bundled_templates() == ["changelog.md.j2", "notes.html.j2", "release.md.j2"]


def test_bundled_template_sources():
    assert load_template_source("changelog.md.j2").startswith("## {% if compare_url %}")
    assert '{% include "release.md.j2" %}' in load_template_source("changelog.md.j2")
    assert "### ⚠ BREAKING CHANGES" in load_template_source("release.md.j2")  # non-ASCII content survives
    notes = load_template_source("notes.html.j2")
    assert notes.startswith("<!DOCTYPE html>") and notes.endswith("</html>\n")


def test_user_directories_take_precedence(tmp_path):
    (tmp_path / "release.md.j2").write_text("custom {{ version }}", encoding="utf-8")
    other = tmp_path / "other"
    other.mkdir()
    assert load_template_source("release.md.j2", [other, tmp_path]) == "custom {{ version }}"
    assert load_template_source("release.md.j2", [str(tmp_path / "missing")]).startswith("{% if breaking %}")
    (other / "extra.j2").write_text("x")
    assert load_template_source("extra.j2", [other]) == "x"


def test_unknown_or_unsafe_names(tmp_path):
    for name in ("missing.j2", "extra.j2", "../cli.py", "templates/release.md.j2", ".hidden", ""):
        with pytest.raises(TemplateNotFoundError):
            load_template_source(name)
    with pytest.raises(TemplateNotFoundError):
        load_template_source("missing.j2", [tmp_path])


def test_legacy_resource_functions_are_gone():
    source = (Path(os.environ.get("REPO_ROOT", ".")) / "src" / "releasebot" / "templating.py").read_text()
    assert not LEGACY_CALL.search(source) and not LEGACY_IMPORT.search(source)
