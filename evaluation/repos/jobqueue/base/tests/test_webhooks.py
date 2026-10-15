import hashlib
import hmac
import io
import json

import pytest
from urllib3.response import HTTPResponse

from jobqueue.errors import WebhookError
from jobqueue.job import Job, JobState
from jobqueue.webhooks import WebhookNotifier

from conftest import START


class FakeHTTP:
    """Stands in for urllib3.PoolManager: records requests, answers with canned responses."""

    def __init__(self, status=200, headers=None):
        self.status, self.headers, self.requests = status, headers or {}, []

    def request(self, method, url, body=None, headers=None, **kwargs):
        self.requests.append({"method": method, "url": url, "body": body, "headers": headers, **kwargs})
        return HTTPResponse(body=io.BytesIO(b"{}"), headers=self.headers, status=self.status, preload_content=True)


def finished(state=JobState.SUCCEEDED):
    return Job(name="add", id="job-1", state=state, attempts=1, created_at=START, finished_at=START)


def test_delivers_signed_event():
    http = FakeHTTP(status=202, headers={"X-Delivery-Id": "dlv-7"})
    notifier = WebhookNotifier("https://hooks.example.test/jobs", secret="s3cret", http=http)
    delivery = notifier.notify(finished())
    assert (delivery.status, delivery.delivery_id) == (202, "dlv-7")
    [sent] = http.requests
    assert (sent["method"], sent["url"]) == ("POST", "https://hooks.example.test/jobs")
    assert json.loads(sent["body"])["event"] == "job.succeeded"
    assert json.loads(sent["body"])["job"]["id"] == "job-1"
    expected = hmac.new(b"s3cret", sent["body"], hashlib.sha256).hexdigest()
    assert sent["headers"]["X-Jobqueue-Signature"] == f"sha256={expected}"


def test_error_status_raises_with_retry_hint():
    http = FakeHTTP(status=503, headers={"Retry-After": "30"})
    with pytest.raises(WebhookError) as info:
        WebhookNotifier("https://hooks.example.test/jobs", http=http).notify(finished(JobState.FAILED))
    assert (info.value.status, info.value.retry_after) == (503, 30.0)


def test_only_subscribed_states_are_sent():
    http = FakeHTTP()
    notifier = WebhookNotifier("https://hooks.example.test/jobs", http=http, events=["failed"])
    assert notifier.notify(finished()) is None
    assert notifier.notify(finished(JobState.FAILED)).status == 200
    assert len(http.requests) == 1


def test_posts_are_retried_on_transient_errors():
    http = FakeHTTP()
    notifier = WebhookNotifier("https://hooks.example.test/jobs", http=http, retries=4)
    assert notifier.retry.is_retry("POST", 503) and not notifier.retry.is_retry("POST", 400)
    notifier.notify(finished())
    assert http.requests[0]["retries"].total == 4
