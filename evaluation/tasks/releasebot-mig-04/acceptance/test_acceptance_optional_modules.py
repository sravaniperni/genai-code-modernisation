import os
import sys
from pathlib import Path

from releasebot.plugins import Publisher, module_available
from releasebot.publishers import BUILTIN_PUBLISHERS


class NeedsThings(Publisher):
    name = "needs-things"
    requires = ("json", "rb_absent_module_xyz", "xml.etree.ElementTree", "rb_absent_pkg_xyz.sub", "json.no_such_sub")


def test_installed_modules_are_available():
    for name in ("json", "xml.etree.ElementTree", "releasebot.hooks", "httpx", "markdown"):
        assert module_available(name) is True, name


def test_missing_modules_are_reported_without_errors():
    for name in ("rb_absent_module_xyz", "rb_absent_pkg_xyz.sub", "json.no_such_sub", ""):
        assert module_available(name) is False, name


def test_availability_check_does_not_import(tmp_path, monkeypatch):
    (tmp_path / "rb_explodes_on_import.py").write_text("raise RuntimeError('must not be imported')\n")
    package = tmp_path / "rb_lazy_pkg"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "heavy.py").write_text("raise RuntimeError('must not be imported')\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    assert module_available("rb_explodes_on_import") is True
    assert module_available("rb_lazy_pkg.heavy") is True
    assert "rb_explodes_on_import" not in sys.modules and "rb_lazy_pkg.heavy" not in sys.modules


def test_publishers_report_missing_requirements(config):
    assert NeedsThings(config).missing_requirements() == ["rb_absent_module_xyz", "rb_absent_pkg_xyz.sub", "json.no_such_sub"]
    for publisher in BUILTIN_PUBLISHERS:
        assert publisher(config).missing_requirements() == [], publisher.name


def test_pkgutil_find_loader_is_gone():
    root = Path(os.environ.get("REPO_ROOT", ".")) / "src"
    assert not any("find_loader" in p.read_text() for p in root.rglob("*.py"))
