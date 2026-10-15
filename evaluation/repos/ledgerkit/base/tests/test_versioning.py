import pytest

from ledgerkit.errors import FormatError
from ledgerkit.versioning import (check_format_version, format_version_info, is_legacy_version,
                                  latest_template_version, needs_upgrade, satisfies)


def test_format_version_compatibility():
    check_format_version("1.0.0")
    check_format_version("1.4.0")
    for bad in ("1.5.0", "2.0.0", "0.9.0", "1.4", "v1.4.0"):
        with pytest.raises(FormatError):
            check_format_version(bad)
    assert needs_upgrade("1.3.9") and not needs_upgrade("1.4.0")


def test_format_version_info():
    assert format_version_info("1.4.0-rc.1+build.7") == {"major": 1, "minor": 4, "patch": 0, "prerelease": "rc.1",
                                                         "build": "build.7"}


def test_template_versions():
    assert latest_template_version(["1.3", "2019.4-CH", "2.1.0", "2.0.post1"]) == "2.1.0"
    assert latest_template_version(["2019.4-CH", "0.1"]) == "0.1"
    assert is_legacy_version("2019.4-CH") and not is_legacy_version("1.3")


def test_requirement_matching():
    assert satisfies("0.9.0", ">=0.8")
    assert satisfies("1.0.0rc1", ">=0.9,<2")
    assert not satisfies("0.9.0", ">=0.5,<0.9")
    assert not satisfies("2019.4-CH", ">=0")
    with pytest.raises(FormatError):
        satisfies("1.0", "about 1")
