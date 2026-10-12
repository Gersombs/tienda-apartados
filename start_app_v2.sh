#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
PYTHON_COMMAND="${PYTHON_COMMAND:-python3.12}"
PYTHON_BIN="$VENV_DIR/bin/python"

usage() {
  echo "Usage: $0 [--install | --migrate | --init-catalog | --create-admin EMAIL [NAME]]"
  echo "With no option, starts the migrated backend and frontend development servers."
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required command not found: $1" >&2
    exit 1
  fi
}

case "${1:-}" in
  --install)
    require_command "$PYTHON_COMMAND"
    require_command pnpm
    "$PYTHON_COMMAND" -m venv "$VENV_DIR"
    "$PYTHON_BIN" -m pip install -r "$PROJECT_DIR/backend/requirements.lock"
    (cd "$PROJECT_DIR/frontend" && pnpm install --frozen-lockfile)
    exit 0
    ;;
  --migrate)
    if [[ ! -x "$PYTHON_BIN" ]]; then
      echo "Missing $PYTHON_BIN; run $0 --install first." >&2
      exit 1
    fi
    (cd "$PROJECT_DIR/backend" && "$PYTHON_BIN" -m alembic upgrade head)
    exit 0
    ;;
  --init-catalog)
    if [[ ! -x "$PYTHON_BIN" ]]; then
      echo "Missing $PYTHON_BIN; run $0 --install first." >&2
      exit 1
    fi
    (cd "$PROJECT_DIR/backend" && "$PYTHON_BIN" -m cli init-catalog)
    exit 0
    ;;
  --create-admin)
    if [[ ! -x "$PYTHON_BIN" ]]; then
      echo "Missing $PYTHON_BIN; run $0 --install first." >&2
      exit 1
    fi
    if [[ -z "${2:-}" ]]; then
      echo "An administrator email is required." >&2
      exit 2
    fi
    (cd "$PROJECT_DIR/backend" && "$PYTHON_BIN" -m cli create-admin --email "$2" --name "${3:-Administradora}")
    exit 0
    ;;
  -h|--help)
    usage
    exit 0
    ;;
  "")
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

require_command pnpm
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Missing local Python environment; run $0 --install first." >&2
  exit 1
fi
if [[ ! -d "$PROJECT_DIR/frontend/node_modules" ]]; then
  echo "Missing frontend dependencies; run $0 --install first." >&2
  exit 1
fi

(cd "$PROJECT_DIR/backend" && "$PYTHON_BIN" -m alembic upgrade head)

cleanup() {
  trap - EXIT INT TERM
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

(cd "$PROJECT_DIR/backend" && "$PYTHON_BIN" -m uvicorn main:app --host 127.0.0.1 --port "${PORT:-8000}" --reload) &
BACKEND_PID=$!
(cd "$PROJECT_DIR/frontend" && pnpm dev -- --host 127.0.0.1 --port "${VITE_PORT:-3000}") &
FRONTEND_PID=$!

echo "Backend: http://127.0.0.1:${PORT:-8000}"
echo "Frontend: http://127.0.0.1:${VITE_PORT:-3000}"
wait -n "$BACKEND_PID" "$FRONTEND_PID"
