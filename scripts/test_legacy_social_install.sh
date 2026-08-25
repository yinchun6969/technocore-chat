#!/usr/bin/env bash
set -Eeuo pipefail

# Static smoke check for the legacy-config migration contract in the installer.
# This does not run the installer because it intentionally touches /opt and systemd.

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INSTALLER="$ROOT/scripts/install_aizong_social.sh"

bash -n "$INSTALLER"

grep -q '检测到旧版 Agent 配置' "$INSTALLER"
grep -q 'openssl genpkey -algorithm Ed25519' "$INSTALLER"
grep -q 'MAILBOX="mb-p-' "$INSTALLER"
grep -q 'printf '\''DID=%q' "$INSTALLER"
grep -q 'printf '\''FP=%q' "$INSTALLER"
grep -q 'printf '\''MAILBOX=%q' "$INSTALLER"
grep -q 'printf '\''KEY=%q' "$INSTALLER"
grep -q 'PRIVATE_NS' "$INSTALLER"

printf 'legacy social installer smoke: ok\n'
