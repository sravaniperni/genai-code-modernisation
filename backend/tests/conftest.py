"""Test configuration.

Integration tests run against a real PostgreSQL database (MODERNISATION_TEST_DATABASE_URL, default: the
local ``modernisation_test`` database) migrated with Alembic, real git, and the real bubblewrap sandbox.
Tests that need an unavailable dependency are skipped with an explicit reason, never silently passed.
"""

from __future__ import annotations

import os
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

TEST_DB = os.environ.get(
    "MODERNISATION_TEST_DATABASE_URL",
    "postgresql+psycopg://modernisation:modernisation-dev@127.0.0.1:5432/modernisation_test",
)
REPO_ROOT = Path(__file__).resolve().parents[2]
BASE = Path(os.environ.get("MODERNISATION_TEST_BASE", "/var/tmp/modernisation-tests")) / uuid.uuid4().hex[:8]
WHEELHOUSE = Path(os.environ.get("MODERNISATION_TEST_WHEELHOUSE", REPO_ROOT / ".data" / "wheelhouse"))

# Configure the platform before any module reads settings.
os.environ["MODERNISATION_DATABASE_URL"] = TEST_DB
os.environ["MODERNISATION_DATA_DIR"] = str(BASE / "data")
os.environ["MODERNISATION_ALLOWED_LOCAL_ROOTS"] = f'["{BASE / "sources"}"]'
os.environ["MODERNISATION_ALLOWED_GITHUB_REPOSITORIES"] = '["example-org/allowed-repo"]'
os.environ["MODERNISATION_WHEELHOUSE_DIR"] = str(WHEELHOUSE)
os.environ["MODERNISATION_MODEL_PROVIDER"] = "none"
os.environ["MODERNISATION_SANDBOX_COMMAND_TIMEOUT_S"] = "120"
os.environ["MODERNISATION_WORKER_HEARTBEAT_S"] = "1"
os.environ.setdefault("MODERNISATION_LOG_LEVEL", "WARNING")
for key in list(os.environ):
    if key.startswith("MODERNISATION_") and key.endswith(("GITHUB_TOKEN", "API_KEY", "WEBHOOK_SECRET", "API_TOKEN")):
        del os.environ[key]


def _mkdir_traversable(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for p in [path, *path.parents]:
        if str(p) in ("/", "/var", "/var/tmp"):
            break
        p.chmod(0o755)
    return path


_mkdir_traversable(BASE / "data")
_mkdir_traversable(BASE / "sources")


def _db_available() -> bool:
    try:
        import sqlalchemy as sa

        engine = sa.create_engine(TEST_DB)
        with engine.connect() as conn:
            conn.execute(sa.text("select 1"))
        engine.dispose()
        return True
    except Exception:
        return False


DB_AVAILABLE = _db_available()
SANDBOX_AVAILABLE = shutil.which("bwrap") is not None and os.geteuid() == 0 and WHEELHOUSE.is_dir()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        if "postgres" in item.keywords and not DB_AVAILABLE:
            item.add_marker(pytest.mark.skip(reason=f"PostgreSQL not reachable at {TEST_DB}"))
        if "sandbox" in item.keywords and not SANDBOX_AVAILABLE:
            item.add_marker(
                pytest.mark.skip(
                    reason="bubblewrap sandbox requires bwrap, root (to drop to the sandbox uid) and a wheelhouse"
                )
            )


@pytest.fixture(scope="session")
def migrated_db() -> Iterator[str]:
    if not DB_AVAILABLE:
        pytest.skip("PostgreSQL not available")
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO_ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "backend" / "migrations"))
    cfg.set_main_option("sqlalchemy.url", TEST_DB)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield TEST_DB


@pytest.fixture()
def db(migrated_db: str) -> Iterator[None]:
    import sqlalchemy as sa

    from modernisation.db.models import Base
    from modernisation.db.session import get_engine
    from modernisation.repository_intelligence.retrieval import clear_cache

    engine = get_engine()
    with engine.begin() as conn:
        names = ", ".join(t.name for t in Base.metadata.sorted_tables)
        conn.execute(sa.text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    clear_cache()
    data = BASE / "data"
    for sub in ("repos", "workspaces"):
        shutil.rmtree(data / sub, ignore_errors=True)
    yield


@pytest.fixture()
def sources() -> Path:
    path = BASE / "sources" / uuid.uuid4().hex[:8]
    return _mkdir_traversable(path)


@pytest.fixture()
def sample_repo(sources: Path) -> Path:
    from tests.helpers import make_repo

    return make_repo(sources / "inventory")


@pytest.fixture()
def session(db: None) -> Iterator[object]:
    from modernisation.db.session import session_factory

    s = session_factory()()
    try:
        yield s
    finally:
        s.close()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    _write_scenario_reports()
    if os.environ.get("MODERNISATION_KEEP_TEST_DATA") != "1":
        shutil.rmtree(BASE, ignore_errors=True)


# --- scenario reports (recovery and security suites) -------------------------------------------------
SCENARIO_RESULTS: dict[str, list[dict[str, object]]] = {}


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[object]):  # type: ignore[no-untyped-def]
    outcome = yield
    report = outcome.get_result()
    meta = getattr(getattr(item, "function", None), "_scenario", None)
    if meta is None:
        return
    if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
        suite = "security" if "/security/" in str(item.path) else "recovery"
        SCENARIO_RESULTS.setdefault(suite, []).append(
            {
                **meta,
                "test": item.nodeid,
                "outcome": report.outcome,
                "duration_s": round(report.duration, 2),
                "observations": getattr(item, "_observations", {}),
                "detail": str(report.longrepr)[-1500:] if report.failed else None,
            }
        )


@pytest.fixture()
def observe(request: pytest.FixtureRequest):  # type: ignore[no-untyped-def]
    def record(**kwargs: object) -> None:
        obs = getattr(request.node, "_observations", {})
        obs.update(kwargs)
        request.node._observations = obs

    return record


def _write_scenario_reports() -> None:
    import json
    from datetime import UTC, datetime

    target = os.environ.get("MODERNISATION_SCENARIO_REPORT_DIR")
    if not target:
        return
    for suite, results in SCENARIO_RESULTS.items():

        def total(key: str, rows: list[dict[str, object]] = results) -> int:
            return sum(int((r["observations"] or {}).get(key, 0)) for r in rows)  # type: ignore[union-attr]

        summary = {
            "suite": suite,
            "generated_at": datetime.now(UTC).isoformat(),
            "scenarios": len(results),
            "passed": sum(r["outcome"] == "passed" for r in results),
            "failed": sum(r["outcome"] == "failed" for r in results),
            "skipped": sum(r["outcome"] == "skipped" for r in results),
            "duplicate_external_actions": total("duplicate_external_actions"),
            "lost_task_state": total("lost_state"),
            "incorrectly_resumed": total("incorrect_resume"),
            "results": sorted(results, key=lambda r: str(r["id"])),
        }
        path = Path(target) / f"{suite}-results.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, indent=2, default=str) + "\n")
