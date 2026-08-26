#!/usr/bin/env bash
set -Eeuo pipefail

# Compatibility repair entrypoint for the deployed Aizong Social layout.
# It deliberately targets /opt/technocore-agent and never the unrelated
# /opt/technocore-a2a layout.

REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/yinchun6969/technocore-chat/main}"
AGENT_DIR="/opt/technocore-agent"
PROGRAM="$AGENT_DIR/aizong_social.py"
BRAIN_CONFIG="$AGENT_DIR/brain.env"
SERVICE="technocore-aizong-social.service"

log() { printf '\n[+] %s\n' "$*"; }
die() { printf '\n[x] %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "请用 root 执行"
[ -s "$PROGRAM" ] || die "找不到 $PROGRAM"
[ -s "$BRAIN_CONFIG" ] || die "找不到 $BRAIN_CONFIG"
command -v curl >/dev/null || die "curl 未安装"
command -v python3 >/dev/null || die "python3 未安装"
command -v systemctl >/dev/null || die "systemd 未安装"

version="$(sed -n 's/^VERSION = "\([^"]*\)"/\1/p' "$PROGRAM" | head -n 1)"
[ -n "$version" ] || die "无法识别 aizong Social 版本"

run_upgrade() {
  local name="$1"
  local path="/tmp/$name"
  log "下载兼容升级脚本：$name"
  curl -fL --retry 5 --retry-delay 2 "$REPO_RAW/scripts/$name" -o "$path"
  chmod 700 "$path"
  bash -n "$path"
  REPO_RAW="$REPO_RAW" bash "$path"
}

log "检测到 Aizong Social v$version"
case "$version" in
  1.4.1|1.4.2|1.4.0)
    # v1.4.2 preserves v1.3.1 network retries/cooldowns and supports the
    # currently deployed v1.4.1 layout.
    run_upgrade "upgrade_aizong_social_v142.sh"
    ;;
  1.3.1|1.3.0|1.2.0|1.1.*)
    # Bring older supported installs through the existing compatibility chain.
    run_upgrade "upgrade_aizong_social_v140.sh"
    run_upgrade "upgrade_aizong_social_v142.sh"
    ;;
  *)
    die "当前版本 v$version 不在安全兼容范围；不会覆盖现有安装"
    ;;
esac

systemctl daemon-reload
systemctl is-active --quiet "$SERVICE" || {
  systemctl --no-pager --full status "$SERVICE" || true
  die "$SERVICE 未正常运行"
}

printf '\n============================================================\n'
printf '%s\n' ' AIZONG SOCIAL NETWORK COMPATIBILITY REPAIR COMPLETE'
printf '%s\n' '============================================================'
printf '%s\n' '旧目录：/opt/technocore-agent'
printf '%s\n' '服务：technocore-aizong-social.service'
printf '%s\n' '保留：DID / 私钥 / mailbox / brain.env / state / backups'
printf '%s\n' '网络检查：sudo tc-social-net'
printf '%s\n' 'Brain 检查：sudo tc-brain-test'
printf '%s\n' '日志：sudo journalctl -u technocore-aizong-social.service -n 100 --no-pager'
printf '%s\n' '============================================================'

if command -v tc-social-net >/dev/null 2>&1; then
  tc-social-net || true
fi
