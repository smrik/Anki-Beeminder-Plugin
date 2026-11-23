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
grep -q 'install_python_prerequisites' "$WIZARD"
grep -q 'sudo pacman -Syu --needed' "$WIZARD"
grep -q 'COLLECTION_PATH="$SYNC_BASE/$SYNC_USERNAME/collection.anki2"' "$WIZARD"
! grep -q 'COLLECTION_PATH="$SYNC_BASE/collection.anki2"' "$WIZARD"
grep -q 'cd -- "$APP_DIR"' "$WIZARD"
grep -q 'sudo systemctl stop anki-sync-server.service' "$WIZARD"
grep -q 'cleanup_sync_server' "$WIZARD"

# The Linux host may provide inetutils `hostname`, which does not implement
# the GNU-only `hostname -I` option. The wizard must keep going and let the
# user enter the client-visible address instead of exiting under pipefail.
wizard_test_dir="$(mktemp -d)"
trap 'rm -rf "$wizard_test_dir"' EXIT
set +e
wizard_output="$({
  printf '\n\nY\n0.0.0.0\n8080\n\n'
} | XDG_CONFIG_HOME="$wizard_test_dir" bash -c '
  hostname() { return 64; }
  export -f hostname
  bash "$1"
' bash "$WIZARD" 2>&1)"
wizard_status=$?
set -e
test "$wizard_status" -ne 64
grep -q 'Client-visible Linux host' <<<"$wizard_output"
grep -q 'ERROR: SYNC_USERNAME is required' <<<"$wizard_output"
