#!/usr/bin/env bash
# Start the REAL FastAPI backend for the Playwright end-to-end tests.
#
# Every run starts from a clean slate:
#   1. ensures a dedicated PostgreSQL database exists (default: modernisation_e2e; never the dev database),
#   2. migrates it down to base and back up to head with Alembic (all tables emptied),
#   3. recreates the data directory and a small sample git repository under E2E_ROOT/sources,
#   4. execs the API (uvicorn) in the foreground so the caller (Playwright's webServer) owns the process.
#
# No model endpoint, GitHub token or API token is configured, and no worker is started: tasks created in
# E2E stay QUEUED, which the UI must show honestly.
#
# Environment overrides:
#   E2E_ROOT           working directory for data and sources   (default /var/tmp/modernisation-e2e)
#   E2E_DB_NAME        database name                            (default modernisation_e2e)
#   E2E_DATABASE_URL   full SQLAlchemy URL (skips database creation)
#   E2E_BACKEND_PORT   API port                                 (default 8000)
#   E2E_LOG_LEVEL      backend log level                        (default WARNING)
#
# Usage: bash frontend/scripts/e2e-backend.sh   (Playwright runs it automatically via `npm run e2e`)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
PYTHON="$BACKEND_DIR/.venv/bin/python"
ALEMBIC="$BACKEND_DIR/.venv/bin/alembic"

E2E_ROOT="${E2E_ROOT:-/var/tmp/modernisation-e2e}"
E2E_DB_NAME="${E2E_DB_NAME:-modernisation_e2e}"
E2E_BACKEND_PORT="${E2E_BACKEND_PORT:-8000}"
DB_URL="${E2E_DATABASE_URL:-postgresql+psycopg://modernisation:modernisation-dev@127.0.0.1:5432/$E2E_DB_NAME}"

log() { printf '[e2e-backend] %s\n' "$*" >&2; }

if [[ ! -x "$PYTHON" ]]; then
  log "backend virtualenv not found at $BACKEND_DIR/.venv (create it with: cd backend && uv sync)"
  exit 1
fi

# --- 1. database --------------------------------------------------------------------------------------
if [[ -z "${E2E_DATABASE_URL:-}" ]]; then
  if [[ "$(id -u)" == "0" ]] && command -v psql > /dev/null; then
    # CREATE DATABASE fails harmlessly when it already exists.
    (cd / && su postgres -c "psql -q -c 'CREATE DATABASE $E2E_DB_NAME OWNER modernisation'") \
      > /dev/null 2>&1 || true
  else
    log "not root: assuming database $E2E_DB_NAME already exists (or set E2E_DATABASE_URL)"
  fi
fi

# --- 2. fresh schema ----------------------------------------------------------------------------------
export MODERNISATION_DATABASE_URL="$DB_URL"
log "migrating $E2E_DB_NAME (downgrade base, upgrade head)"
(cd "$BACKEND_DIR" && "$ALEMBIC" downgrade base > /dev/null 2>&1 && "$ALEMBIC" upgrade head > /dev/null)

# --- 3. data directory and sample repository ------------------------------------------------------------
rm -rf "$E2E_ROOT/data" "$E2E_ROOT/sources"
mkdir -p "$E2E_ROOT/data" "$E2E_ROOT/sources"
# The sandbox user must be able to traverse these directories.
chmod 755 "$E2E_ROOT" "$E2E_ROOT/data" "$E2E_ROOT/sources"

SAMPLE="$E2E_ROOT/sources/inventory"
mkdir -p "$SAMPLE/src/inventory" "$SAMPLE/tests"

git_fixture() {
  GIT_AUTHOR_NAME="E2E Fixture" GIT_AUTHOR_EMAIL="e2e-fixture@example.invalid" \
    GIT_COMMITTER_NAME="E2E Fixture" GIT_COMMITTER_EMAIL="e2e-fixture@example.invalid" \
    GIT_CONFIG_GLOBAL=/dev/null git -C "$SAMPLE" -c commit.gpgsign=false "$@"
}

cat > "$SAMPLE/pyproject.toml" << 'EOF'
[project]
name = "inventory"
version = "1.0.0"
requires-python = ">=3.10"
dependencies = []

[project.optional-dependencies]
test = ["pytest"]

[tool.pytest.ini_options]
testpaths = ["tests"]
EOF

cat > "$SAMPLE/README.md" << 'EOF'
# inventory

Small inventory and pricing library used as the end-to-end test fixture.
EOF

cat > "$SAMPLE/src/inventory/__init__.py" << 'EOF'
"""Inventory management helpers."""

from inventory.pricing import apply_discount, order_total

__all__ = ["apply_discount", "order_total"]
EOF

cat > "$SAMPLE/src/inventory/models.py" << 'EOF'
"""Domain models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LineItem:
    sku: str
    unit_price: float
    quantity: int

    def __post_init__(self) -> None:
        if self.quantity < 0:
            raise ValueError("quantity must be non-negative")
EOF

cat > "$SAMPLE/src/inventory/pricing.py" << 'EOF'
"""Pricing rules."""

from __future__ import annotations

from inventory.models import LineItem

BULK_THRESHOLD = 10


def apply_discount(price: float, percent: float) -> float:
    """Return ``price`` reduced by ``percent`` percent, never below zero."""
    if percent < 0 or percent > 100:
        raise ValueError("percent must be between 0 and 100")
    return round(price - price * percent / 1000, 2)


def order_total(items: list[LineItem], discount_percent: float = 0.0) -> float:
    """Total of all line items after an order-level discount."""
    subtotal = sum(item.unit_price * item.quantity for item in items)
    return apply_discount(subtotal, discount_percent)


def is_bulk(item: LineItem) -> bool:
    return item.quantity >= BULK_THRESHOLD
EOF

cat > "$SAMPLE/tests/test_pricing.py" << 'EOF'
import pytest

from inventory.models import LineItem
from inventory.pricing import apply_discount, order_total


def test_zero_discount_keeps_price():
    assert apply_discount(50.0, 0) == 50.0


def test_invalid_percent_rejected():
    with pytest.raises(ValueError):
        apply_discount(10.0, 120)


def test_order_total_without_discount():
    items = [LineItem("a", 2.5, 4), LineItem("b", 1.0, 3)]
    assert order_total(items) == 13.0
EOF

git_fixture init -q -b main
git_fixture add -A
git_fixture commit -q -m "initial import"

cat > "$SAMPLE/src/inventory/report.py" << 'EOF'
"""Reporting helpers."""

from __future__ import annotations

from inventory.models import LineItem
from inventory.pricing import is_bulk, order_total


def summary(items: list[LineItem]) -> dict[str, float]:
    return {"total": order_total(items), "bulk_lines": float(sum(1 for i in items if is_bulk(i)))}
EOF

cat > "$SAMPLE/tests/test_report.py" << 'EOF'
from inventory.models import LineItem
from inventory.report import summary


def test_summary_counts_bulk_lines():
    items = [LineItem("a", 1.0, 12), LineItem("b", 2.0, 1)]
    assert summary(items)["bulk_lines"] == 1.0
EOF

git_fixture add -A
git_fixture commit -q -m "add order summary report"
chmod -R a+rX "$SAMPLE"
log "sample repository ready at $SAMPLE"

# --- 4. API -------------------------------------------------------------------------------------------
# Never inherit credentials or model settings from the calling shell.
for var in $(env | grep -o '^MODERNISATION_[A-Z_]*' || true); do
  [[ "$var" == "MODERNISATION_DATABASE_URL" ]] || unset "$var"
done
export MODERNISATION_DATA_DIR="$E2E_ROOT/data"
export MODERNISATION_ALLOWED_LOCAL_ROOTS="[\"$E2E_ROOT/sources\"]"
export MODERNISATION_API_CORS_ORIGINS='["http://localhost:5173","http://127.0.0.1:5173"]'
export MODERNISATION_MODEL_PROVIDER=none
export MODERNISATION_LOG_LEVEL="${E2E_LOG_LEVEL:-WARNING}"

log "starting API on 127.0.0.1:$E2E_BACKEND_PORT (database $E2E_DB_NAME)"
# Run outside backend/ so a developer's backend/.env (read from the working directory) cannot leak in.
cd "$E2E_ROOT"
exec "$PYTHON" -m modernisation.cli api --host 127.0.0.1 --port "$E2E_BACKEND_PORT"
