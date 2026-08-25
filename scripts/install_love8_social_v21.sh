#!/usr/bin/env bash
set -Eeuo pipefail
REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/yinchun6969/technocore-chat/love8-social-v2}"
TMP_BASE="/root/install-love8-social-v2-base.sh"
TMP_UP="/root/upgrade-love8-social-v21.sh"

if [[ -s /opt/love8-agent/social/config.env ]]; then
  echo '[+] Existing Love8 Social detected; upgrading directly to v2.1.0'
else
  echo '[+] No Love8 Social v2 config detected; installing base runtime first'
  curl -fsSL "$REPO_RAW/scripts/install_love8_social_v2.sh" -o "$TMP_BASE"
  bash "$TMP_BASE"
fi

curl -fsSL "$REPO_RAW/scripts/upgrade_love8_social_v21.sh" -o "$TMP_UP"
bash "$TMP_UP"
