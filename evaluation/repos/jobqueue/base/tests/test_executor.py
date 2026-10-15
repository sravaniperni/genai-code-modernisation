import logging

from jobqueue.errors import WebhookError
from jobqueue.executor import Executor
from jobqueue.history import ExecutionHistory
from jobqueue.job import JobState
from jobqueue.retry import RetryPolicy

from conftest import START


class RecordingNotifier:
    def __init__(self, fail=False):
        self.jobs, self.fail = [], fail

    def notify(self, job):
        self.jobs.append(job.id)
        if self.fail:
            raise WebhookError("endpoint down")


def claim(queue):
    return queue.store.claim_next(queue.clock.now(), "w1")


def test_successful_job_is_recorded_and_notified(queue):
    notifier = RecordingNotifier()
    executor = Executor(queue.store, queue.registry, clock=queue.clock, notifier=notifier)
    job = queue.enqueue("add", {"a": 2, "b": 3})
    executor.execute(claim(queue))
    done = queue.get(job.id)
    assert (done.state, done.result, done.finished_at) == (JobState.SUCCEEDED, 5, START)
    assert notifier.jobs == [job.id]


def test_failing_job_is_retried_later_then_failed(queue, clock):
    queue.registry.register("flaky", lambda payload: 1 / 0)
    executor = Executor(queue.store, queue.registry, clock=clock, retry_policy=RetryPolicy(base_delay=10))
    job = queue.enqueue("flaky", max_attempts=2)
    executor.execute(claim(queue))
    first = queue.get(job.id)
    assert first.state == JobState.PENDING and first.run_at > START and "ZeroDivisionError" in first.last_error
    assert claim(queue) is None
    clock.advance(hours=1)
    executor.execute(claim(queue))
    final = queue.get(job.id)
    assert (final.state, final.attempts, final.finished_at) == (JobState.FAILED, 2, clock.now())


def test_async_handlers_are_awaited(queue):
    async def double(payload):
        return payload["n"] * 2

    queue.registry.register("double", double)
    job = queue.enqueue("double", {"n": 21})
    Executor(queue.store, queue.registry, clock=queue.clock).execute(claim(queue))
    assert queue.get(job.id).result == 42


def test_notification_failures_do_not_change_the_outcome(queue, caplog):
    executor = Executor(queue.store, queue.registry, clock=queue.clock, notifier=RecordingNotifier(fail=True))
    job = queue.enqueue("add", {"a": 1, "b": 1})
    with caplog.at_level(logging.WARNING, logger="jobqueue.executor"):
        executor.execute(claim(queue))
    assert queue.get(job.id).state == JobState.SUCCEEDED
    assert any(job.id in record.getMessage() for record in caplog.records)


def test_attempts_are_written_to_history(queue, clock):
    history = ExecutionHistory()
    queue.registry.register("flaky", lambda payload: 1 / 0)
    executor = Executor(queue.store, queue.registry, clock=clock, history=history)
    job = queue.enqueue("flaky", max_attempts=1)
    executor.execute(claim(queue))
    [attempt] = history.attempts(job.id)
    assert (attempt.outcome, attempt.attempt, attempt.started_at) == ("failed", 1, START)
    assert attempt.error.startswith("ZeroDivisionError")
