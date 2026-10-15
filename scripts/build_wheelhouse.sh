#!/usr/bin/env bash
# Build the offline wheelhouse used inside the execution sandbox (which has no network).
#
#   scripts/build_wheelhouse.sh [DEST]            # base test tooling + every benchmark repository's pins
#   WHEELHOUSE_SETS=base scripts/build_wheelhouse.sh   # base test tooling only (CI unit/integration tests)
#
# Only binary wheels for CPython 3.12 / manylinux x86_64 or pure Python are downloaded; no sdist is ever built.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-$ROOT/.data/wheelhouse}"
SETS="${WHEELHOUSE_SETS:-all}"
mkdir -p "$DEST"
files=("$ROOT/scripts/wheelhouse-base.txt")
if [[ "$SETS" == "all" ]]; then
  while IFS= read -r f; do files+=("$f"); done < <(find "$ROOT/evaluation/repos" -name wheelhouse.txt 2>/dev/null | sort)
fi
for f in "${files[@]}"; do
  # one requirement per invocation: a file may legitimately pin several versions of the same package
  grep -Ev '^\s*(#|$)' "$f" | while read -r req; do
    python3.12 -m pip download --quiet --no-deps --only-binary=:all: --python-version 3.12 \
      --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 --platform manylinux_2_28_x86_64 \
      --platform any -d "$DEST" "$req"
  done
done
echo "wheelhouse: $(ls "$DEST" | wc -l) wheels in $DEST"
