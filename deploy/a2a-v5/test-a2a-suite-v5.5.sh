#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
SUITE="$ROOT/install-a2a-suite-v5.5.sh"
INSTALLER="$ROOT/install-verifiable-evidence-v5.5.sh"

bash -n "$SUITE" "$INSTALLER"
grep -Eq '^V54_REF="[0-9a-f]{40}"$' "$SUITE"
grep -Eq '^SOURCE_REF="[0-9a-f]{40}"$' "$SUITE" "$INSTALLER"
grep -Eq '^V54_SHA256="[0-9a-f]{64}"$' "$SUITE"
grep -Eq '^SOURCE_SHA256="[0-9a-f]{64}"$' "$SUITE"
! grep -q '__[A-Z_]*__' "$SUITE" "$INSTALLER"
grep -Fq 'technocore status --task-id wf-...' "$SUITE" "$INSTALLER"
grep -Fq 'identity_private_keys_mailboxes_cursors_nonces_provenance_artifacts=preserved' "$SUITE"
grep -Fq 'existing signed-stage protocol retained' "$SUITE"
python3 "$ROOT/test_evidence_v55.py"
python3 "$ROOT/test_curator_reliability_v51.py"
python3 "$ROOT/test_v55_integration.py"
python3 "$ROOT/test_human_action_center_v1.py"
python3 "$ROOT/test_telegram_notifications_v53.py"
python3 "$ROOT/test_verifiable_evidence_installer_v55.py"
bash "$ROOT/test-a2a-suite-v5.4.sh"
echo "A2A_SUITE_V55_TEST=PASS"
