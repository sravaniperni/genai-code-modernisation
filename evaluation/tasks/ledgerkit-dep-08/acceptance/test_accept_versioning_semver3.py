import importlib.metadata
import json
import warnings

import pytest

from ledgerkit.errors import FormatError
from ledgerkit.formats import load_ledger
from ledgerkit.versioning import FORMAT_VERSION, check_format_version, format_version_info, needs_upgrade


def test_semver_is_pinned_to_3_0_4():
    assert importlib.metadata.version("semver") == "3.0.4"


@pytest.mark.parametrize("value", ["1.0.0", "1.3.7", "1.4.0", "1.4.0-rc.1", "1.4.0+build.5", "1.2.0-alpha+exp.sha.5114f85"])
def test_readable_versions(value):
    assert FORMAT_VERSION == "1.4.0"
    check_format_version(value)


@pytest.mark.parametrize(("value", "message"), [
    ("1.4", "invalid format version '1.4'"),
    ("v1.4.0", "invalid format version 'v1.4.0'"),
    ("01.4.0", "invalid format version '01.4.0'"),
    ("", "invalid format version ''"),
    (None, "invalid format version None"),
    ("2.0.0", "unsupported format version 2.0.0; this release reads 1.x"),
    ("0.9.9", "unsupported format version 0.9.9; this release reads 1.x"),
    ("1.4.1", "format version 1.4.1 is newer than the supported 1.4.0"),
    ("1.5.0-rc.1", "format version 1.5.0-rc.1 is newer than the supported 1.4.0"),
])
def test_rejected_versions(value, message):
    with pytest.raises(FormatError) as info:
        check_format_version(value)
    assert str(info.value) == message


def test_needs_upgrade_uses_semver_precedence():
    assert needs_upgrade("1.3.9")
    assert needs_upgrade("1.4.0-rc.1")
    assert needs_upgrade("0.1.0")
    assert not needs_upgrade("1.4.0")
    assert not needs_upgrade("1.4.0+build.9")
    assert not needs_upgrade("1.10.0")


def test_format_version_info_is_a_plain_dict():
    info = format_version_info("1.4.0-rc.1+build.7")
    assert isinstance(info, dict)
    assert info == {"major": 1, "minor": 4, "patch": 0, "prerelease": "rc.1", "build": "build.7"}
    assert format_version_info("1.2.3") == {"major": 1, "minor": 2, "patch": 3, "prerelease": None, "build": None}


def _document(version):
    return json.dumps({"formatVersion": version, "accounts": [{"code": "1000", "name": "Cash", "type": "asset"}],
                       "entries": []})


def test_documents_are_checked_by_format_version():
    ledger, _ = load_ledger(_document("1.3.0"))
    assert len(ledger.chart) == 1
    with pytest.raises(FormatError, match="newer than the supported"):
        load_ledger(_document("1.5.0"))
    with pytest.raises(FormatError, match="invalid format version"):
        load_ledger(_document("1.x"))


def test_no_semver_deprecation_warnings():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        check_format_version("1.2.0")
        for bad in ("2.0.0", "1.9.0", "x"):
            with pytest.raises(FormatError):
                check_format_version(bad)
        needs_upgrade("1.2.0")
        format_version_info("1.2.0-rc.1")
    offending = [str(w.message) for w in caught
                 if issubclass(w.category, (DeprecationWarning, PendingDeprecationWarning)) and "semver" in str(w.message)]
    assert offending == []
