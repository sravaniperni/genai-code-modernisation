# ledgerkit (benchmark fixture)

`ledgerkit` is a small double-entry bookkeeping library written for this benchmark: chart of accounts,
balanced journal entries with `Decimal` money, exchange rates and conversion (with a background rate
refresher), fiscal calendars and period closing, trial balance / income statement / balance sheet
reports, CSV and bank-feed import, a versioned JSON interchange format (marshmallow + semver), API
validation schemas (pydantic), signed report exports (PyJWT), SQL persistence (SQLAlchemy, in-memory
SQLite in tests), an sqlite3 audit trail, tar.gz backups, bundled chart templates and a click CLI.

The baseline deliberately pins old dependency versions (see `base/requirements.txt`) and uses APIs that
are deprecated on Python 3.12, so that realistic maintenance tasks can be derived from it
(`evaluation/tasks/ledgerkit-*`).

All code in this directory was written from scratch for the benchmark and is released under the
MIT licence:

    Copyright (c) 2026 the benchmark authors

    Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
    associated documentation files (the "Software"), to deal in the Software without restriction,
    including without limitation the rights to use, copy, modify, merge, publish, distribute,
    sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all copies or
    substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT
    NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
    NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES
    OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
    CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Tasks

| id | category | split |
| --- | --- | --- |
| ledgerkit-dep-01 … dep-08 | dependency_upgrade (click, PyJWT, pydantic, SQLAlchemy, marshmallow, arrow, packaging, semver) | dep-01/02 dev, rest heldout |
| ledgerkit-mig-01 … mig-06 | deprecated_api_migration (utcnow, sqlite3 adapters, importlib.resources, threading aliases, logging.warn, tarfile/rmtree) | mig-01 dev, rest heldout |
| ledgerkit-bug-01 … bug-06 | bug_fix (allocation rounding, closing signs, period end, conversion direction, balance tolerance, decimal comma) | bug-01 dev, rest heldout |
