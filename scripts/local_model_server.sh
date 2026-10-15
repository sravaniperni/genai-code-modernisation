#!/usr/bin/env bash
# Start/stop a local OpenAI-compatible inference server (llama.cpp via llama-cpp-python) on CPU.
#
#   scripts/local_model_server.sh install            # create venv, build llama-cpp-python
#   scripts/local_model_server.sh download 1.5b|7b   # fetch Apache-2.0 Qwen2.5-Coder GGUF weights
#   scripts/local_model_server.sh start 1.5b|7b      # serve on 127.0.0.1:${PORT:-8081}
#   scripts/local_model_server.sh stop
#   scripts/local_model_server.sh status
set -euo pipefail

LLM_HOME="${LLM_HOME:-/opt/llm}"
PORT="${PORT:-8081}"
THREADS="${THREADS:-$(nproc)}"
CTX="${CTX:-16384}"
PIDFILE="$LLM_HOME/server.pid"

model_file() {
  case "$1" in
    1.5b) echo "qwen2.5-coder-1.5b-instruct-q4_k_m.gguf" ;;
    7b) echo "qwen2.5-coder-7b-instruct-q4_k_m.gguf" ;;
    *) echo "unknown model size: $1 (use 1.5b or 7b)" >&2; exit 2 ;;
  esac
}

model_repo() {
  case "$1" in
    1.5b) echo "Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF" ;;
    7b) echo "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF" ;;
  esac
}

case "${1:-}" in
  install)
    mkdir -p "$LLM_HOME"
    python3.12 -m venv "$LLM_HOME/venv"
    "$LLM_HOME/venv/bin/pip" install -q --upgrade pip
    CMAKE_ARGS="-DGGML_NATIVE=ON -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF" \
      "$LLM_HOME/venv/bin/pip" install "llama-cpp-python[server]==0.3.16"
    ;;
  download)
    size="${2:?model size}"
    mkdir -p "$LLM_HOME/models"
    f="$(model_file "$size")"
    curl -sSL --retry 3 -o "$LLM_HOME/models/$f" "https://huggingface.co/$(model_repo "$size")/resolve/main/$f"
    sha256sum "$LLM_HOME/models/$f"
    ;;
  start)
    size="${2:?model size}"
    f="$(model_file "$size")"
    alias="${f%.gguf}"
    if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "server already running (pid $(cat "$PIDFILE"))"; exit 0
    fi
    nohup "$LLM_HOME/venv/bin/python" -m llama_cpp.server \
      --model "$LLM_HOME/models/$f" --model_alias "$alias" \
      --host 127.0.0.1 --port "$PORT" --n_ctx "$CTX" --n_threads "$THREADS" \
      > "$LLM_HOME/server-$size.log" 2>&1 &
    echo $! > "$PIDFILE"
    for _ in $(seq 1 90); do
      if curl -sf "http://127.0.0.1:$PORT/v1/models" > /dev/null; then
        echo "serving $alias on http://127.0.0.1:$PORT/v1 (pid $(cat "$PIDFILE"))"; exit 0
      fi
      sleep 2
    done
    echo "server failed to start; see $LLM_HOME/server-$size.log" >&2; exit 1
    ;;
  stop)
    if [[ -f "$PIDFILE" ]]; then kill "$(cat "$PIDFILE")" 2>/dev/null || true; rm -f "$PIDFILE"; fi
    ;;
  status)
    curl -sf "http://127.0.0.1:$PORT/v1/models" || { echo "not running"; exit 1; }
    ;;
  *)
    sed -n '2,9p' "$0"; exit 2 ;;
esac
