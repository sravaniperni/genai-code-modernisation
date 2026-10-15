import importlib.metadata

import pytest

from ledgerkit.errors import FormatError
from ledgerkit.templates import is_supported, template_info
from ledgerkit.versioning import is_legacy_version, latest_template_version, satisfies


def test_packaging_is_pinned_to_24_2():
    assert importlib.metadata.version("packaging") == "24.2"


@pytest.mark.parametrize("value", ["2019.4-CH", "2018-final", "r2019.2", "v2019q4", "2019.4 CH"])
def test_legacy_versions_are_recognised(value):
    assert is_legacy_version(value)
    assert not satisfies(value, ">=0")


@pytest.mark.parametrize("value", ["1.3", "2.0.post1", "1.0rc1", "v1.2", "2019-r2", "1.0-1"])
def test_pep440_versions_are_not_legacy(value):
    assert not is_legacy_version(value)


def test_latest_template_version_ordering():
    assert latest_template_version(["1.3", "2019.4-CH", "2.1.0", "2.0.post1"]) == "2.1.0"
    assert latest_template_version(["2019.4-CH", "0.0.1", "2018-final"]) == "0.0.1"
    assert latest_template_version(["1.0rc1", "1.0", "1.0.dev4"]) == "1.0"
    assert latest_template_version(["1.10", "1.9.9", "1.2"]) == "1.10"
    assert latest_template_version(iter(["2019.4-CH"])) == "2019.4-CH"
    assert latest_template_version(["2019.4-CH", "2018-final"]) in {"2019.4-CH", "2018-final"}


def test_requirement_matching():
    assert satisfies("0.9.0", ">=0.8")
    assert satisfies("1.0.0rc1", ">=0.9,<2")
    assert satisfies("1.4.2", "==1.*")
    assert satisfies("0.9.0", "~=0.9")
    assert not satisfies("0.9.0", ">=0.5,<0.9")
    assert not satisfies("2.0", "!=2.0.0")
    for requirement in ("about 1", "=>1.0", "1.0"):
        with pytest.raises(FormatError):
            satisfies("1.0", requirement)


def test_template_support_checks():
    assert template_info("legacy-retail")["version"] == "2019.4-CH"
    assert is_legacy_version(template_info("legacy-retail")["version"])
    assert not is_legacy_version(template_info("nonprofit")["version"])
    assert not is_supported("legacy-retail")
    assert is_supported("legacy-retail", "0.8.5")
    assert is_supported("nonprofit") and is_supported("small-business")
    assert not is_supported("nonprofit", "2.0.0")
    assert is_supported("nonprofit", "1.5.0.dev3")
    assert not is_supported("small-business", "0.7.9")
