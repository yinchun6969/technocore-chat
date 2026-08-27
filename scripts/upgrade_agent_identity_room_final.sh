#!/usr/bin/env bash
set -Eeuo pipefail

SELECTOR="${1:-aizong}"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

log(){ printf '\n[+] %s\n' "$*"; }
die(){ printf '\n[x] %s\n' "$*" >&2; exit 1; }

[[ ${EUID:-$(id -u)} -eq 0 ]] || die "请用 root 执行；如果当前就是 root，不要加 sudo"
command -v curl >/dev/null || die "curl 未安装"

case "$SELECTOR" in
  aizong)
    log "AIZONG -> Social Brain v1.5.2 capacity-aware identity room"
    URL="https://raw.githubusercontent.com/yinchun6969/technocore-chat/main/scripts/upgrade_aizong_social_v152.sh"
    curl -fsSL --retry 5 --retry-delay 2 "$URL" -o "$TMP"
    bash -n "$TMP"
    exec bash "$TMP"
    ;;
  love8)
    log "LOVE8 -> Persistent v2.5.1 capacity-aware identity room"
    URL="https://raw.githubusercontent.com/yinchun6969/technocore-chat/love8-social-v2/scripts/upgrade_love8_identity_room_v251.sh"
    curl -fsSL --retry 5 --retry-delay 2 "$URL" -o "$TMP"
    bash -n "$TMP"
    exec bash "$TMP"
    ;;
  ai2ai)
    log "AI2AI -> R&D v5.2.1 capacity-aware identity room"
    URL="https://raw.githubusercontent.com/yinchun6969/technocore-chat/a2a-autonomous-rnd-v5/deploy/a2a-v5/install-identity-room-v5.2.1.sh"
    curl -fsSL --retry 5 --retry-delay 2 "$URL" -o "$TMP"
    bash -n "$TMP"
    exec bash "$TMP"
    ;;
  *)
    die "未知 agent: $SELECTOR；只支持 aizong / love8 / ai2ai"
    ;;
esac
