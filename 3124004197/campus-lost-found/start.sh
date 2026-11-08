#!/usr/bin/env bash
set -euo pipefail
CAMPUS_PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -x "$CAMPUS_PROJECT_DIR/.venv/bin/python" ]]; then
    python3 -m venv "$CAMPUS_PROJECT_DIR/.venv"
    "$CAMPUS_PROJECT_DIR/.venv/bin/python" -m pip install -r "$CAMPUS_PROJECT_DIR/requirements.txt"
fi
exec "$CAMPUS_PROJECT_DIR/.venv/bin/python" "$CAMPUS_PROJECT_DIR/start.py" "$@"
