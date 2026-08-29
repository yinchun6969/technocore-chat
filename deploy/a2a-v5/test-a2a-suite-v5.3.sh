#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
INSTALLER="$ROOT/install-a2a-suite-v5.3.sh"

bash -n "$INSTALLER"
grep -Fq 'MODE="check"' "$INSTALLER"
grep -Fq 'CHECK_ONLY: no installed files or services changed' "$INSTALLER"
grep -Fq 'A2A_V53_TELEGRAM_SOURCE_URL=' "$INSTALLER"
grep -Fq 'repair-love8-peer-bridge-v243.py" --apply' "$INSTALLER"
grep -Fq 'repair-aizong-wire-v3.4.py" --apply' "$INSTALLER"
grep -Fq 'identity_private_keys_mailboxes_cursors_provenance=preserved' "$INSTALLER"

python3 "$ROOT/test_telegram_notifications_v53.py"
echo "A2A_SUITE_V53_STATIC_TEST=PASS"
