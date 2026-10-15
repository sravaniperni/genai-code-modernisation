# webhookrelay

A small webhook relay service. It receives webhooks over HTTP, authenticates them (HMAC signatures or
JWT bearer tokens), normalises JSON, form and XML bodies into events, runs them through plugins and
routing rules, and delivers them to downstream targets with signing, retries and exponential backoff.

* `app.py` - Flask application: `POST /hooks/<source>`, `GET /admin/status` and `/admin/status.json`
* `signatures.py` - HMAC and JWT verification, outbound delivery tokens
* `payloads.py` - content-type handling and body normalisation
* `routing.py` - routing rules
* `delivery.py`, `transports.py`, `scheduler.py` - delivery, HTTP transports, retry scheduling
* `templating.py`, `rendering.py` - Jinja2 notification bodies, Markdown rendering with sanitisation
* `plugins.py` - plugin registry (entry point group `webhookrelay.plugins`)
* `replay.py`, `batch.py` - replaying archived requests, concurrent batch sends

Run the tests with `pytest`. Runtime dependencies are pinned in `requirements.txt`.

Licensed under the MIT licence.
