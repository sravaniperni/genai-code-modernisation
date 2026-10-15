# webhookrelay (benchmark fixture)

`webhookrelay` is a small webhook relay service written for this benchmark. It is a Flask application that
receives webhooks (`POST /hooks/<source>`), authenticates them with HMAC signatures or JWT bearer tokens,
normalises JSON, form-encoded and XML bodies into events, runs them through plugins (discovered through the
`webhookrelay.plugins` entry-point group) and routing rules, and delivers them to downstream targets with
signing, retries, exponential backoff and Retry-After handling. Notification bodies can be rendered from
Jinja2 templates and Markdown (sanitised with bleach), there is an admin status page and JSON status
endpoint, archive replay into the WSGI app, and an asyncio batch sender.

All HTTP clients are injectable (httpx `MockTransport`, a fake urllib3 pool), so the tests never open
network connections.

Layout:

* `base/` - the project at its clean baseline: `src/webhookrelay/` (15 modules), `tests/` (64 tests),
  `requirements.txt` (exact runtime pins of the old library versions the tasks upgrade from),
  `requirements-dev.txt` (`pytest==8.3.5`).
* `wheelhouse.txt` - every wheel needed by the baseline and all 20 tasks, including transitive
  dependencies. It lists two versions of several packages, so download it line by line (see the comment
  at the top of the file).

Tasks: `evaluation/tasks/webhookrelay-dep-01..08` (dependency upgrades: PyJWT, Jinja2, Flask/Werkzeug,
urllib3, httpx, bleach, Markdown, importlib-metadata), `webhookrelay-mig-01..06` (deprecated API
migrations: datetime.utcnow/utcfromtimestamp, asyncio.get_event_loop, logging.warn, cgi, threading
camelCase aliases, ElementTree truth-testing) and `webhookrelay-bug-01..06` (bug fixes).

## Licence

The webhookrelay code, tests and task files are original work written for this benchmark and are released
under the MIT licence:

    Copyright (c) 2026 Benchmark Fixture Authors

    Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
    associated documentation files (the "Software"), to deal in the Software without restriction, including
    without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the
    following conditions:

    The above copyright notice and this permission notice shall be included in all copies or substantial
    portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT
    LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO
    EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
    IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR
    THE USE OR OTHER DEALINGS IN THE SOFTWARE.
