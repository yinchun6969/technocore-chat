#!/usr/bin/env bash
set -Eeuo pipefail

RAW="https://raw.githubusercontent.com/yinchun6969/technocore-chat/a2a-deploy-v1/deploy/a2a-v1/install.sh"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

curl -fsSL "$RAW" -o "$TMP"

# v1.1 auth compatibility fix:
# systemd EnvironmentFile strips trailing whitespace from an unquoted value such as
# AI_KEY_PREFIX=Bearer<space>. The v1 script then concatenated prefix+key directly,
# producing Authorization: Bearer<key>. Normalize the prefix and insert one space here.
if grep -q 'AI_HEADER: AI_PREFIX + AI_KEY' "$TMP"; then
  sed -i 's/AI_HEADER: AI_PREFIX + AI_KEY/AI_HEADER: ((AI_PREFIX.strip() + " ") if AI_PREFIX.strip() else "") + AI_KEY/' "$TMP"
fi

# Keep the displayed/default prefix whitespace-free. The Python code above inserts the
# separator safely, so both "Bearer" and a custom non-empty scheme work.
sed -i 's/API-key prefix \[Bearer \]/API-key prefix [Bearer]/g' "$TMP" || true
sed -i 's/AI_KEY_PREFIX=${AI_KEY_PREFIX:-Bearer }/AI_KEY_PREFIX=${AI_KEY_PREFIX:-Bearer}/g' "$TMP" || true

# If this wrapper itself is started through `curl ... | sudo bash`, stdin is the curl pipe.
# The downloaded interactive installer must read from the terminal instead, otherwise its
# first `read` sees EOF immediately after printing the banner and exits under `set -e`.
if [[ -r /dev/tty ]]; then
  exec bash "$TMP" </dev/tty
else
  echo "No interactive TTY available. Download the script first, then run it with sudo bash." >&2
  exit 1
fi
