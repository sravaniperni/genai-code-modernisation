# jobqueue

A lightweight persistent job queue and scheduler.

* `JobQueue` validates submissions (`JobSpec`) and stores jobs in a `JobStore`
  (`MemoryJobStore` in-process, `SQLJobStore` on any SQLAlchemy database).
* `WorkerPool` runs jobs on threads through an `Executor`, which applies the
  `RetryPolicy` (capped exponential backoff) and sends completion webhooks.
* `RecurringScheduler` enqueues jobs from cron expressions (`CronSchedule`).
* Handlers are registered on a `HandlerRegistry` or discovered from the
  `jobqueue.handlers` entry-point group of installed plugins.
* `TokenSigner` issues signed per-job tokens; `jobqueue.serialization`
  exports and imports jobs as JSON; `jobqueue` is the admin CLI.

Run the tests with `python -m pytest`.
