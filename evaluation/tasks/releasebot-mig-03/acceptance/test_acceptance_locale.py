import os
from datetime import date, datetime
from pathlib import Path

import pytest

from releasebot.dates import detect_language, format_release_date

LOCALE_VARIABLES = ("LC_ALL", "LC_CTYPE", "LANG", "LANGUAGE")
DAY = date(2026, 3, 5)


@pytest.fixture
def env(monkeypatch):
    for name in LOCALE_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_language_comes_from_lang(env):
    env.setenv("LANG", "de_DE.UTF-8")
    assert detect_language() == "de"
    assert format_release_date(DAY) == "5. März 2026"
    assert format_release_date(datetime(2026, 8, 1, 22, 15)) == "1. August 2026"


def test_precedence_of_locale_variables(env):
    env.setenv("LANGUAGE", "de:en")
    assert detect_language() == "de"
    env.setenv("LANG", "fr_FR.UTF-8")
    assert detect_language() == "fr"
    env.setenv("LC_CTYPE", "de_CH.UTF-8")
    assert detect_language() == "de"
    env.setenv("LC_ALL", "en_GB.UTF-8")
    assert format_release_date(DAY) == "March 5, 2026"
    env.setenv("LC_ALL", "")  # empty values are skipped
    assert detect_language() == "de"


def test_locale_names_are_normalised(env):
    for value, expected in [("de", "de"), ("fr_CA.ISO8859-1", "fr"), ("de_AT@euro", "de"), ("FR_fr.utf8", "fr")]:
        env.setenv("LANG", value)
        assert detect_language() == expected, value


def test_unsupported_locales_fall_back(env):
    assert detect_language() == "en"
    for value in ("C", "C.UTF-8", "POSIX", "pt_BR.UTF-8", "xx_YY.UTF-8", "klingon"):
        env.setenv("LANG", value)
        assert detect_language() == "en", value
        assert detect_language(default="de") == "de", value
    assert format_release_date(DAY) == "March 5, 2026"


def test_explicit_language_wins(env):
    env.setenv("LANG", "de_DE.UTF-8")
    assert format_release_date(DAY, language="fr") == "5 mars 2026"
    assert format_release_date(DAY, language="en") == "March 5, 2026"


def test_getdefaultlocale_is_gone():
    root = Path(os.environ.get("REPO_ROOT", ".")) / "src"
    assert not any("getdefaultlocale" in p.read_text() for p in root.rglob("*.py"))
