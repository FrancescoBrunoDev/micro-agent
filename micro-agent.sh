#!/usr/bin/env bash
# micro-agent — thin gateway for Pi + markdown memory
# Usage: micro-agent [--help]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_DIR" || exit 1

# Use virtualenv if available
if [ -d "$PROJECT_DIR/.venv" ]; then
    source "$PROJECT_DIR/.venv/bin/activate"
fi

exec python3 -m micro_agent.main "$@"
