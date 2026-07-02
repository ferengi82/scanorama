#!/usr/bin/env bash
# Deploy auf den Raspberry Pi: Code per rsync nach ~/pilidar, venv +
# editable install. Voraussetzung: SSH-Host "pilidar" in ~/.ssh/config.
#
# Nutzung:
#   scripts/deploy.sh            # sync + install
#   scripts/deploy.sh --test     # zusätzlich pytest auf dem Pi ausführen

set -euo pipefail

HOST="${PILIDAR_HOST:-pilidar}"
REMOTE_DIR="~/pilidar"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "→ Sync $REPO_ROOT → $HOST:$REMOTE_DIR"
rsync -az --delete \
    --exclude ".git" \
    --exclude "venv" \
    --exclude "__pycache__" \
    --exclude "*.egg-info" \
    --exclude ".pytest_cache" \
    "$REPO_ROOT/" "$HOST:$REMOTE_DIR/"

echo "→ venv + editable install auf dem Pi"
ssh "$HOST" "cd $REMOTE_DIR && \
    if [ ! -d venv ]; then python3 -m venv --system-site-packages venv; fi && \
    ./venv/bin/pip install -q -e '.[dev]'"

if [[ "${1:-}" == "--test" ]]; then
    echo "→ pytest auf dem Pi"
    ssh "$HOST" "cd $REMOTE_DIR && ./venv/bin/python -m pytest -q"
fi

echo "✓ Deploy fertig — auf dem Pi: $REMOTE_DIR/venv/bin/pilidar"
