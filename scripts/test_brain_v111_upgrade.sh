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
grep -q 'chmod 600 "$BRAIN_CONFIG"' "$PATCH"

# The standalone brain test must call only the configured model endpoint. It must not
# write to Technocore rooms or know the Technocore base URL at all.
TEST_BLOCK="$(sed -n '/cat >\/usr\/local\/bin\/tc-brain-test/,/^EOF$/p' "$PATCH")"
if printf '%s\n' "$TEST_BLOCK" | grep -Eq 'technocore\.chat|/r/|signed_post'; then
  echo 'brain test unexpectedly contains a Technocore write path' >&2
  exit 1
fi

# Persisting BRAIN_KEY into the root-only env file is expected. Operator-facing output
# must only use fixed hidden/configured wording, never interpolate the secret itself.
grep -q 'Key:       %s' "$PATCH"
grep -q "configured (hidden)" "$PATCH"
if grep -Eq 'echo[[:space:]]+"?\$BRAIN_KEY|printf[^\n]*"?\$BRAIN_KEY"?[[:space:]]*$' "$PATCH"; then
  echo 'patch appears to print BRAIN_KEY directly' >&2
  exit 1
fi

printf 'brain v1.1.1 upgrade smoke: ok\n'
