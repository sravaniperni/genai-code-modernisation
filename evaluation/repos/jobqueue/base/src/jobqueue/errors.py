"""Exception hierarchy shared by every jobqueue component."""

from __future__ import annotations


class JobQueueError(Exception):
    """Base class for all jobqueue errors."""


class JobNotFound(JobQueueError, KeyError):
    """No job with the requested id exists."""


class DuplicateJob(JobQueueError):
    def __init__(self, unique_key: str, existing_id: str):
        super().__init__(f"a job with unique key {unique_key!r} is already active ({existing_id})")
        self.unique_key, self.existing_id = unique_key, existing_id


class PayloadTooLarge(JobQueueError, ValueError):
    def __init__(self, size: int, limit: int):
        super().__init__(f"payload is {size} bytes; the limit is {limit} bytes")
        self.size, self.limit = size, limit


class InvalidJobSpec(JobQueueError, ValueError):
    """A submission failed validation; ``errors`` maps field names to messages."""

    def __init__(self, errors: dict[str, str]):
        detail = "; ".join(f"{key}: {message}" for key, message in sorted(errors.items()))
        super().__init__(f"invalid job specification ({detail})")
        self.errors = errors


class InvalidSchedule(JobQueueError, ValueError):
    """A cron expression could not be parsed or never fires."""


class HandlerNotFound(JobQueueError, LookupError):
    """No handler is registered under the requested name."""


class TokenError(JobQueueError):
    """A job token is malformed, badly signed or lacks a required scope."""


class TokenExpired(TokenError):
    """A job token is past its expiry time."""


class WebhookError(JobQueueError):
    def __init__(self, message: str, *, status: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.status, self.retry_after = status, retry_after


class SerializationError(JobQueueError, ValueError):
    def __init__(self, messages: object):
        super().__init__(f"invalid job export: {messages}")
        self.messages = messages
