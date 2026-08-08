#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WIZARD="$ROOT_DIR/scripts/setup_linux_sync.sh"

test -f "$WIZARD"
bash -n "$WIZARD"
grep -q 'ask_secret SYNC_PASSWORD' "$WIZARD"
grep -q 'ask_secret BEEMINDER_TOKEN' "$WIZARD"
grep -q 'anki-sync-server.service' "$WIZARD"
grep -q 'anki-beeminder.timer' "$WIZARD"
grep -q 'systemctl daemon-reload' "$WIZARD"
! grep -q 'ANKIWEB_PASSWORD' "$WIZARD"
