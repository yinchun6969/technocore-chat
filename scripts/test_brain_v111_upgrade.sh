#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PATCH111="$ROOT/scripts/upgrade_aizong_brain_v111.sh"
PATCH112="$ROOT/scripts/upgrade_aizong_brain_v112.sh"

bash -n "$PATCH111"
bash -n "$PATCH112"

grep -q '\*/v1) printf.*chat/completions' "$PATCH111"
grep -q 'cat >/usr/local/bin/tc-brain-test' "$PATCH111"
grep -q 'AIZONG_BRAIN_OK' "$PATCH111"
grep -q 'API key is root-only and hidden' "$PATCH111"
grep -q 'systemctl restart "$SERVICE"' "$PATCH111"

# The v1.1.2 patch must expand completion headroom for reasoning-capable models
# while preserving the 500-character public reply cap in the social client.
grep -q 'BRAIN_MAX_TOKENS="768"' "$PATCH112"
grep -q 'Completion budget:' "$PATCH112"
grep -q 'Reasoning channel: present' "$PATCH112"
grep -q 'final answer was truncated' "$PATCH112"
grep -q '), 2048)' "$PATCH112"
grep -q 'systemctl restart "$SERVICE"' "$PATCH112"

# The standalone brain tests must call only the configured model endpoint. They must not
# write to Technocore rooms or know the Technocore base URL at all.
for PATCH in "$PATCH111" "$PATCH112"; do
  TEST_BLOCK="$(sed -n '/cat >\/usr\/local\/bin\/tc-brain-test/,/^EOF$/p' "$PATCH")"
  if printf '%s\n' "$TEST_BLOCK" | grep -Eq 'technocore\.chat|/r/|signed_post'; then
    echo 'brain test unexpectedly contains a Technocore write path' >&2
    exit 1
  fi
done

# Secret persistence into chmod-600 brain.env is expected. Reject obvious direct
# operator-facing output of the variable itself, but allow hidden configured/empty status.
for PATCH in "$PATCH111" "$PATCH112"; do
  if awk '/^[[:space:]]*echo / && /\$BRAIN_KEY/ {bad=1} END {exit bad ? 0 : 1}' "$PATCH"; then
    echo 'patch appears to echo BRAIN_KEY' >&2
    exit 1
  fi
  if awk '/^[[:space:]]*printf / && /\$BRAIN_KEY/ && $0 !~ />/ && $0 !~ /configured \(hidden\)/ {bad=1} END {exit bad ? 0 : 1}' "$PATCH"; then
    echo 'patch appears to printf BRAIN_KEY' >&2
    exit 1
  fi
done

printf 'brain v1.1.1/v1.1.2 upgrade smoke: ok\n'
