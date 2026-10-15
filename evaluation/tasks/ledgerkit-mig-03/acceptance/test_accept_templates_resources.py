import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from ledgerkit.accounts import AccountType
from ledgerkit.errors import TemplateNotFoundError
from ledgerkit.templates import available_templates, is_supported, load_template, template_info


def test_only_json_templates_are_listed():
    assert available_templates() == ["legacy-retail", "nonprofit", "small-business"]


def test_template_contents():
    chart = load_template("small-business")
    assert len(chart) == 14
    assert [a.code for a in chart if a.parent == "6000"] == ["6100", "6200", "6300"]
    assert chart.get("2100").type is AccountType.LIABILITY
    nonprofit = load_template("nonprofit")
    assert nonprofit.get("4000").name == "Donations"


def test_utf8_content_is_preserved():
    chart = load_template("legacy-retail")
    assert chart.get("1000").name == "Kasse – Filiale Zürich"
    assert chart.get("1010").name == "Caisse enregistreuse – Genève"
    assert chart.get("6000").name == "Raumaufwand (Miete Straße 5)"
    assert chart.get("1200").currency == "EUR"


def test_template_info():
    assert template_info("legacy-retail") == {
        "name": "legacy-retail", "title": "Einzelhandel / Commerce de détail (2019)", "version": "2019.4-CH",
        "requires": ">=0.5,<0.9", "description": "Multi-currency retail chart shipped with the 2019 releases.",
        "accounts": 8}
    assert template_info("nonprofit")["version"] == "1.3"
    assert template_info("small-business")["accounts"] == 14


def test_support_checks():
    assert is_supported("small-business") and is_supported("nonprofit")
    assert not is_supported("legacy-retail")
    assert is_supported("legacy-retail", "0.8.1")


@pytest.mark.parametrize("name", ["enterprise", "README", "README.txt", "__init__", "small-business.json", ""])
def test_unknown_templates(name):
    with pytest.raises(TemplateNotFoundError) as info:
        load_template(name)
    assert isinstance(info.value, KeyError)
    with pytest.raises(KeyError):
        template_info(name)


def test_templates_load_from_a_zip_archive(tmp_path):
    package = Path(os.environ["REPO_ROOT"], "src", "ledgerkit")
    archive = tmp_path / "ledgerkit.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for path in package.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                zf.write(path, Path("ledgerkit", path.relative_to(package)).as_posix())
    code = ("import ledgerkit, ledgerkit.templates as t\n"
            "assert ledgerkit.__file__.startswith(%r), ledgerkit.__file__\n"
            "print(t.available_templates())\n"
            "print(t.load_template('legacy-retail').get('1000').name)\n"
            "print(t.template_info('nonprofit')['accounts'])\n") % str(archive)
    env = {**os.environ, "PYTHONPATH": str(archive), "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run([sys.executable, "-W", "error::DeprecationWarning", "-c", code], env=env,
                            capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["['legacy-retail', 'nonprofit', 'small-business']",
                                          "Kasse – Filiale Zürich", "8"]
