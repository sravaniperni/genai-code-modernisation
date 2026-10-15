import hashlib
import hmac
import importlib.metadata
import io
import json
from datetime import datetime, timezone

import pytest
import urllib3
from urllib3.exceptions import MaxRetryError, NewConnectionError
from urllib3.response import HTTPResponse

from jobqueue.errors import WebhookError
from jobqueue.executor import Executor
from jobqueue.job import Job, JobState
from jobqueue.queue import JobQueue
from jobqueue.registry import HandlerRegistry
from jobqueue.webhooks import WebhookNotifier

URL = "https://receiver.example.test/hooks/jobs"
T0 = datetime(2024, 5, 6, 8, 0, tzinfo=timezone.utc)


class FakePool:
    """Test double for urllib3.PoolManager returning real urllib3 responses."""

    def __init__(self, status=200, headers=None, error=None):
        self.status, self.headers, self.error, self.calls = status, headers or {}, error, []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.error is not None:
            raise self.error
        return HTTPResponse(body=io.BytesIO(b'{"ok": true}'), headers=self.headers, status=self.status,
                            preload_content=True)


def finished(state=JobState.SUCCEEDED, **kwargs):
    return Job(name="report", id="job-9", state=state, attempts=1, created_at=T0, finished_at=T0, **kwargs)


def test_urllib3_version_is_pinned():
    assert importlib.metadata.version("urllib3") == "2.2.3"


def test_retry_configuration():
    notifier = WebhookNotifier(URL, http=FakePool(), retries=5, backoff_factor=1.5)
    retry = notifier.retry
    assert retry.total == 5 and retry.backoff_factor == 1.5
    for status in (429, 500, 502, 503, 504):
        assert retry.is_retry("POST", status)
    assert not retry.is_retry("POST", 400) and not retry.is_retry("POST", 404)
    assert retry.is_retry("GET", 503) and retry.is_retry("PUT", 502)
    assert not retry.is_retry("PATCH", 503)


def test_successful_delivery():
    pool = FakePool(status=201, headers={"x-delivery-id": "d-123", "Content-Type": "application/json"})
    delivery = WebhookNotifier(URL, secret="k", http=pool).notify(finished())
    assert (delivery.status, delivery.delivery_id) == (201, "d-123")
    [(method, url, kwargs)] = pool.calls
    assert (method, url) == ("POST", URL)
    assert kwargs["retries"].is_retry("POST", 503)
    body = kwargs["body"]
    assert json.loads(body)["job"]["state"] == "succeeded"
    signature = "sha256=" + hmac.new(b"k", body, hashlib.sha256).hexdigest()
    assert kwargs["headers"]["X-Jobqueue-Signature"] == signature


@pytest.mark.parametrize("header, expected", [("15", 15.0), ("0.5", 0.5), ("86400", 120.0), ("-3", 0.0),
                                              ("Wed, 21 Oct 2015 07:28:00 GMT", None), (None, None)])
def test_error_responses_carry_retry_after(header, expected):
    headers = {"retry-after": header} if header is not None else {}
    with pytest.raises(WebhookError) as info:
        WebhookNotifier(URL, http=FakePool(status=429, headers=headers)).notify(finished(JobState.FAILED))
    assert info.value.status == 429 and info.value.retry_after == expected


def test_transport_errors_become_webhook_errors():
    reason = NewConnectionError(None, "connection refused")
    pool = FakePool(error=MaxRetryError(None, URL, reason=reason))
    with pytest.raises(WebhookError) as info:
        WebhookNotifier(URL, http=pool).notify(finished())
    assert info.value.status is None


def test_default_pool_and_subscriptions():
    notifier = WebhookNotifier(URL, events=["failed"])
    assert isinstance(notifier.http, urllib3.PoolManager)
    assert notifier.notify(finished()) is None
    assert notifier.notify(finished(JobState.CANCELLED)) is None


def test_executor_sends_completion_events():
    pool = FakePool(status=202, headers={"X-Delivery-Id": "abc"})
    registry = HandlerRegistry()
    registry.register("report", lambda payload: {"rows": payload["n"]})
    queue = JobQueue(registry=registry)
    job = queue.enqueue("report", {"n": 3})
    executor = Executor(queue.store, registry, notifier=WebhookNotifier(URL, http=pool))
    executor.execute(queue.store.claim_next(queue.clock.now(), "w"))
    assert queue.get(job.id).state == JobState.SUCCEEDED
    assert json.loads(pool.calls[0][2]["body"])["event"] == "job.succeeded"
