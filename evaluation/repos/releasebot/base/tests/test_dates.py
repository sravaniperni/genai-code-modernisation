from datetime import date, datetime

import pytest

from releasebot.dates import detect_language, format_release_date

LOCALE_VARS = ("LC_ALL", "LC_CTYPE", "LANG", "LANGUAGE")


@pytest.fixture
def clean_locale(monkeypatch):
    for name in LOCALE_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_explicit_languages():
    assert format_release_date(date(2026, 3, 5), language="en") == "March 5, 2026"
    assert format_release_date(datetime(2026, 3, 5, 23, 0), language="de") == "5. März 2026"
    assert format_release_date(date(2026, 8, 1), language="fr") == "1 août 2026"
    assert format_release_date(date(2026, 8, 1), language="xx") == "August 1, 2026"


def test_language_follows_the_locale_environment(clean_locale):
    clean_locale.setenv("LANG", "de_DE.UTF-8")
    assert detect_language() == "de"
    assert format_release_date(date(2026, 10, 3)) == "3. Oktober 2026"


def test_unsupported_or_missing_locale_falls_back_to_english(clean_locale):
    assert detect_language() == "en"
    clean_locale.setenv("LANG", "C.UTF-8")
    assert detect_language() == "en"
