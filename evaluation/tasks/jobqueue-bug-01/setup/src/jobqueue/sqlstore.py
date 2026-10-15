"""Job store backed by a SQL database (SQLAlchemy)."""

from __future__ import annotations

import json
import threading
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine, func, or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import TypeDecorator

from jobqueue.errors import JobNotFound
from jobqueue.job import Job, JobState
from jobqueue.payload import decode_payload, encode_payload
from jobqueue.store import JobStore, mark_running

Base = declarative_base()


class UTCDateTime(TypeDecorator):
    """Persists aware datetimes as naive UTC and loads them back as aware UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        return value.astimezone(timezone.utc).replace(tzinfo=None) if value is not None else None

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        return value.replace(tzinfo=timezone.utc) if value is not None else None


class JobRecord(Base):
    __tablename__ = "jobqueue_jobs"

    id = Column(String(32), primary_key=True)
    seq = Column(Integer, nullable=False)
    name = Column(String(120), nullable=False)
    queue = Column(String(64), nullable=False, index=True)
    state = Column(String(16), nullable=False, index=True)
    priority = Column(Integer, nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False)
    payload = Column(Text, nullable=False)
    result = Column(Text)
    run_at = Column(UTCDateTime)
    created_at = Column(UTCDateTime, nullable=False)
    started_at = Column(UTCDateTime)
    finished_at = Column(UTCDateTime)
    last_error = Column(Text)
    worker = Column(String(120))
    unique_key = Column(String(200), index=True)


jobs = JobRecord.__table__
COLUMNS = [column.name for column in jobs.columns]


def _to_row(job: Job) -> dict[str, Any]:
    row = {name: getattr(job, name) for name in COLUMNS}
    row.update(state=job.state.value, priority=int(job.priority), payload=encode_payload(job.payload),
               result=json.dumps(job.result) if job.result is not None else None)
    return row


def _from_row(row: Any) -> Job:
    data = {name: row[name] for name in COLUMNS}
    data.update(state=JobState(data["state"]), payload=decode_payload(data["payload"]),
                result=json.loads(data["result"]) if data["result"] is not None else None)
    return Job(**data)


class SQLJobStore(JobStore):
    """Jobs in a SQLAlchemy database; ``SQLJobStore("sqlite://")`` is a thread-safe in-memory database."""

    def __init__(self, url: str = "sqlite://", *, engine: Engine | None = None):
        if engine is None:
            options: dict[str, Any] = {}
            if url.startswith("sqlite"):
                options["connect_args"] = {"check_same_thread": False}
                if url in ("sqlite://", "sqlite:///:memory:"):
                    options["poolclass"] = StaticPool
            engine = create_engine(url, **options)
        self.engine = engine
        self._lock = threading.RLock()
        Base.metadata.create_all(engine)

    def add(self, job: Job) -> None:
        with self._lock:
            self.engine.execute(jobs.insert().values(**_to_row(job)))

    def get(self, job_id: str) -> Job:
        with self._lock:
            row = self.engine.execute(select([jobs]).where(jobs.c.id == job_id)).first()
        if row is None:
            raise JobNotFound(job_id)
        return _from_row(row)

    def update(self, job: Job) -> None:
        with self._lock:
            result = self.engine.execute(jobs.update().where(jobs.c.id == job.id).values(**_to_row(job)))
        if result.rowcount == 0:
            raise JobNotFound(job.id)

    def claim_next(self, now: datetime, worker: str, queues: Sequence[str] | None = None) -> Job | None:
        query = select([jobs]).where(jobs.c.state == JobState.PENDING.value)
        query = query.where(or_(jobs.c.run_at.is_(None), jobs.c.run_at <= now))
        if queues:
            query = query.where(jobs.c.queue.in_(list(queues)))
        query = query.order_by(jobs.c.priority.desc(), jobs.c.created_at.desc(), jobs.c.seq.desc()).limit(1)
        with self._lock:
            row = self.engine.execute(query).first()
            if row is None:
                return None
            job = _from_row(row)
            mark_running(job, now, worker)
            self.update(job)
        return job

    def list(self, *, state: JobState | None = None, queue: str | None = None,
             limit: int | None = None) -> list[Job]:
        query = select([jobs]).order_by(jobs.c.created_at, jobs.c.seq)
        if state is not None:
            query = query.where(jobs.c.state == JobState(state).value)
        if queue is not None:
            query = query.where(jobs.c.queue == queue)
        with self._lock:
            return [_from_row(row) for row in self.engine.execute(query.limit(limit))]

    def find_active(self, unique_key: str) -> Job | None:
        query = select([jobs]).where(jobs.c.unique_key == unique_key).where(jobs.c.state.in_(["pending", "running"]))
        with self._lock:
            row = self.engine.execute(query.limit(1)).first()
        return _from_row(row) if row is not None else None

    def counts(self) -> dict[str, int]:
        query = select([jobs.c.state, func.count(jobs.c.id).label("total")]).group_by(jobs.c.state)
        with self._lock:
            found = {row["state"]: row["total"] for row in self.engine.execute(query)}
        return {state.value: found.get(state.value, 0) for state in JobState}

    def close(self) -> None:
        self.engine.dispose()
