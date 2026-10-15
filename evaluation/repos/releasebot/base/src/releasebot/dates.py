"""Localised release dates; month names are bundled so no system locales need to be installed."""

from __future__ import annotations

import locale
import os
from datetime import date, datetime

MONTHS = {
    "en": ("January", "February", "March", "April", "May", "June", "July", "August", "September",
           "October", "November", "December"),
    "de": ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September",
           "Oktober", "November", "Dezember"),
    "fr": ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
           "octobre", "novembre", "décembre"),
}
PATTERNS = {
    "en": "{month} {day}, {year}",
    "de": "{day}. {month} {year}",
    "fr": "{day} {month} {year}",
}
DEFAULT_LANGUAGE = "en"
# Same precedence the C library uses for the user's preferred locale.
LOCALE_VARIABLES = ("LC_ALL", "LC_CTYPE", "LANG", "LANGUAGE")


def _preferred_locale() -> str | None:
    for variable in LOCALE_VARIABLES:
        value = os.environ.get(variable)
        if value:
            return value.split(":")[0] if variable == "LANGUAGE" else value
    return None


def detect_language(default: str = DEFAULT_LANGUAGE) -> str:
    """The two-letter language of the user's locale, or ``default`` if it is unsupported."""
    name = _preferred_locale()
    if not name:
        return default
    code = locale.normalize(name).split(".")[0].split("@")[0]
    if code in ("C", "POSIX"):
        return default
    language = code.split("_")[0].lower()
    return language if language in MONTHS else default


def format_release_date(value: date | datetime, *, language: str | None = None) -> str:
    """Format ``value`` in ``language`` (default: the user's locale), e.g. ``March 5, 2026``."""
    if isinstance(value, datetime):
        value = value.date()
    language = language or detect_language()
    if language not in MONTHS:
        language = DEFAULT_LANGUAGE
    month = MONTHS[language][value.month - 1]
    return PATTERNS[language].format(day=value.day, month=month, year=value.year)
