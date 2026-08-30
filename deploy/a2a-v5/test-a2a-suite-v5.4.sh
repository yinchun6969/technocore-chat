#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
SUITE="$ROOT/install-a2a-suite-v5.4.sh"
CORE="$ROOT/install-autonomous-rnd-v5.sh"
CURATOR="$ROOT/install-curator-reliability-v5.2.sh"

for file in "$SUITE" "$CORE" "$CURATOR"; do bash -n "$file"; done
grep -Eq 'SOURCE_REF="[0-9a-f]{40}"' "$SUITE"
grep -Eq 'V5_REF="[0-9a-f]{40}"' "$CORE"
grep -Eq 'SOURCE_REF="[0-9a-f]{40}"' "$CURATOR"
! grep -q '__[A-Z_]*__' "$SUITE" "$CORE" "$CURATOR"
grep -Fq 'RND_V5_CURATOR_POLL_SECONDS=30' "$CORE"
grep -Fq 'rm -rf "\$ROOT/rnd-v5"' "$CORE"
! grep -Fq 'rm -rf "\$ROOT/rnd-v5" "\$ROOT/rnd-v5-state"' "$CORE"
grep -Fq 'repair-aizong-evidence-mirror-v3.5.py" --apply' "$SUITE"
grep -Fq 'install-curator-reliability-v5.2.sh" --apply' "$SUITE"
grep -Fq 'identity_private_keys_mailboxes_cursors_provenance_artifacts=preserved' "$SUITE"
python3 "$ROOT/test_curator_reliability_v51.py"
python3 "$ROOT/test_aizong_evidence_mirror_v35.py"
python3 "$ROOT/test_wire_room_v31.py"
python3 "$ROOT/test_telegram_notifications_v53.py"
echo "A2A_SUITE_V54_TEST=PASS"
