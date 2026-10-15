#!/usr/bin/env bash
# Run the frozen benchmark in platform and baseline modes with the local model, then write reports.
# Resumable: re-running with the same RUN_TAG continues where it stopped (finished tasks are never re-run).
#
#   RUN_TAG=2026-10-15 scripts/run_evaluation.sh            # all 100 tasks, both modes
#   SPLIT=dev RUN_TAG=dev-1 scripts/run_evaluation.sh       # development split only
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_TAG="${RUN_TAG:?set RUN_TAG}"
SPLIT="${SPLIT:-all}"
MODES="${MODES:-platform baseline}"
FINAL_FLAG="${FINAL_FLAG:---final}"
LOG_DIR="$ROOT/.data/eval-logs"
mkdir -p "$LOG_DIR"

export MODERNISATION_DATA_DIR="$ROOT/.data"
export MODERNISATION_WHEELHOUSE_DIR="${MODERNISATION_WHEELHOUSE_DIR:-$ROOT/.data/wheelhouse}"
export MODERNISATION_MODEL_PROVIDER="${MODERNISATION_MODEL_PROVIDER:-openai_compatible}"
export MODERNISATION_MODEL_BASE_URL="${MODERNISATION_MODEL_BASE_URL:-http://127.0.0.1:8081/v1}"
export MODERNISATION_MODEL_NAME="${MODERNISATION_MODEL_NAME:-qwen2.5-coder-1.5b-instruct-q4_k_m}"
export MODERNISATION_MODEL_STRUCTURED_OUTPUT="${MODERNISATION_MODEL_STRUCTURED_OUTPUT:-json_object_schema}"
export MODERNISATION_MODEL_MAX_OUTPUT_TOKENS="${MODERNISATION_MODEL_MAX_OUTPUT_TOKENS:-1536}"
export MODERNISATION_MODEL_TIMEOUT_S="${MODERNISATION_MODEL_TIMEOUT_S:-900}"
export MODERNISATION_LOG_LEVEL="${MODERNISATION_LOG_LEVEL:-WARNING}"
# Evaluation-wide context budgets (identical for both modes); see docs/EVALUATION_PROTOCOL.md
export MODERNISATION_EVAL_CONTEXT_CHARS="${MODERNISATION_EVAL_CONTEXT_CHARS:-10000}"
export MODERNISATION_EVAL_EDIT_CONTEXT_CHARS="${MODERNISATION_EVAL_EDIT_CONTEXT_CHARS:-16000}"

cd "$ROOT/backend"
curl -sf "$MODERNISATION_MODEL_BASE_URL/models" > /dev/null || { echo "model endpoint not reachable" >&2; exit 1; }
keys=()
for mode in $MODES; do
  key="$mode-$SPLIT-$RUN_TAG"
  keys+=("$key")
  echo "[$(date -u +%FT%TZ)] starting $key" | tee -a "$LOG_DIR/$RUN_TAG.log"
  .venv/bin/python -m modernisation.evaluation run $FINAL_FLAG --mode "$mode" --run-key "$key" --split "$SPLIT" \
    >> "$LOG_DIR/$key.out" 2>> "$LOG_DIR/$key.err"
  echo "[$(date -u +%FT%TZ)] finished $key" | tee -a "$LOG_DIR/$RUN_TAG.log"
done
IFS=,; .venv/bin/python -m modernisation.evaluation report --run-keys "${keys[*]}"
echo "[$(date -u +%FT%TZ)] reports written" | tee -a "$LOG_DIR/$RUN_TAG.log"
