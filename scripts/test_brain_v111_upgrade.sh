#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PATCH="$ROOT/scripts/upgrade_aizong_brain_v111.sh"

bash -n "$PATCH"

grep -q '\*/v1) printf.*chat/completions' "$PATCH"
grep -q 'cat >/usr/local/bin/tc-brain-test' "$PATCH"
grep -q 'AIZONG_BRAIN_OK' "$PATCH"
grep -q 'API key is root-only and hidden' "$PATCH"
grep -q 'systemctl restart "$SERVICE"' "$PATCH"

# The standalone brain test must call only the configured model endpoint. It must not
# write to Technocore rooms or know the Technocore base URL at all.
TEST_BLOCK="$(sed -n '/cat >\/usr\/local\/bin\/tc-brain-test/,/^EOF$/p' "$PATCH")"
if printf '%s\n' "$TEST_BLOCK" | grep -Eq 'technocore\.chat|/r/|signed_post'; then
  echo 'brain test unexpectedly contains a Technocore write path' >&2
  exit 1
fi

# The operator-facing status may name whether a key exists, but the patch must never
# print the key value itself.
if grep -Eq 'echo .*BRAIN_KEY|printf .*BRAIN_KEY' "$PATCH"; then
  echo 'patch appears to print BRAIN_KEY' >&2
  exit 1
fi

printf 'brain v1.1.1 upgrade smoke: ok\n'
