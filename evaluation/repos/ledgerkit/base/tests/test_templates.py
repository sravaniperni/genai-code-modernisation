import pytest

from ledgerkit.accounts import AccountType
from ledgerkit.errors import TemplateNotFoundError
from ledgerkit.templates import available_templates, is_supported, load_template, template_info


def test_bundled_templates():
    assert available_templates() == ["legacy-retail", "nonprofit", "small-business"]
    chart = load_template("small-business")
    assert chart.get("6100").parent == "6000"
    assert chart.get("3100").type is AccountType.EQUITY


def test_template_metadata_and_support():
    info = template_info("legacy-retail")
    assert info["version"] == "2019.4-CH" and info["accounts"] == 8
    assert load_template("legacy-retail").get("1010").name == "Caisse enregistreuse – Genève"
    assert is_supported("nonprofit") and not is_supported("legacy-retail")


def test_unknown_template():
    with pytest.raises(TemplateNotFoundError):
        load_template("enterprise")
