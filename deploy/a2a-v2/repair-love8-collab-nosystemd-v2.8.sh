#!/usr/bin/env bash
set -Eeuo pipefail

# Restore the existing Love8 A2A sidecar where PID 1 is not systemd.
# No DID, private key, mailbox, peer map, cursor or workflow state is changed.

ROOT="/opt/technocore-collab"
ENV_FILE="$ROOT/.env"
AGENT="$ROOT/bin/collab.py"
PYTHON="$ROOT/venv/bin/python"
RUNNER="$ROOT/bin/runner.sh"
STARTER="/usr/local/bin/tc-collab-start"
STOPPER="/usr/local/bin/tc-collab-stop"
STATUS="/usr/local/bin/tc-collab-process-status"
LOG_CMD="/usr/local/bin/tc-collab-log"
PIDFILE="$ROOT/state/runner.pid"
LOGFILE="$ROOT/state/runner.log"
LOCKFILE="$ROOT/state/runner.lock"
CRONFILE="/etc/cron.d/technocore-collab"
STAMP="$(date -u +%Y%m%d-%H%M%S)"

die() { printf '\n[x] %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "请用 root 执行"
[ -f "$ENV_FILE" ] || die "找不到 $ENV_FILE；不会创建新身份"
[ -f "$AGENT" ] || die "找不到 $AGENT；不会重装 sidecar"
[ -x "$PYTHON" ] || die "找不到 sidecar Python runtime：$PYTHON；不会覆盖现有配置"
command -v flock >/dev/null 2>&1 || die "系统缺少 flock，无法防止重复启动"

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
[ "${AGENT_NAME:-}" = "love8" ] || die "当前 sidecar 不是 love8：${AGENT_NAME:-unknown}"
[ "${ROLE:-}" = "scout" ] || die "当前角色不是 scout：${ROLE:-unknown}"

"$PYTHON" -m py_compile "$AGENT"
install -d -m 0700 "$ROOT/state" "$ROOT/bin"

process_is_runner() {
  local pid="${1:-}"
  [ -n "$pid" ] || return 1
  [ -r "/proc/$pid/cmdline" ] || return 1
  tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null | grep -Fq "$RUNNER"
}

stop_existing_runner() {
  local old=""
  [ -f "$PIDFILE" ] && old="$(cat "$PIDFILE" 2>/dev/null || true)"
  if process_is_runner "$old"; then
    kill -TERM -- "-$old" 2>/dev/null || kill -TERM "$old" 2>/dev/null || true
    for _ in 1 2 3 4 5; do
      process_is_runner "$old" || break
      sleep 1
    done
    process_is_runner "$old" && kill -KILL -- "-$old" 2>/dev/null || true
  fi
  rm -f "$PIDFILE"
}

if [ -f "$RUNNER" ]; then
  cp -a "$RUNNER" "$RUNNER.before-v2.8-$STAMP"
fi
stop_existing_runner

cat >"$RUNNER" <<'RUNNER_EOF'
#!/usr/bin/env bash
set -u
ROOT="/opt/technocore-collab"
ENV_FILE="$ROOT/.env"
PYTHON="$ROOT/venv/bin/python"
AGENT="$ROOT/bin/collab.py"
PIDFILE="$ROOT/state/runner.pid"
LOGFILE="$ROOT/state/runner.log"
LOCKFILE="$ROOT/state/runner.lock"

mkdir -p "$ROOT/state"
exec 9>"$LOCKFILE"
flock -n 9 || exit 0
printf '%s\n' "$$" >"$PIDFILE"
cleanup() { rm -f "$PIDFILE"; }
shutdown() { cleanup; exit 143; }
trap cleanup EXIT
trap shutdown HUP INT TERM

while true; do
  set -a
  . "$ENV_FILE"
  set +a
  printf '[%s] starting Love8 collab sidecar\n' "$(date -Is)" >>"$LOGFILE"
  "$PYTHON" "$AGENT" run >>"$LOGFILE" 2>&1
  rc=$?
  printf '[%s] collab exited rc=%s; restarting in 5s\n' "$(date -Is)" "$rc" >>"$LOGFILE"
  sleep 5
done
RUNNER_EOF
chmod 0700 "$RUNNER"

if [ -f "$STARTER" ]; then cp -a "$STARTER" "$STARTER.before-v2.8-$STAMP"; fi
cat >"$STARTER" <<'START_EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
RUNNER="/opt/technocore-collab/bin/runner.sh"
PIDFILE="/opt/technocore-collab/state/runner.pid"
LOGFILE="/opt/technocore-collab/state/runner.log"

if [ -f "$PIDFILE" ]; then
  pid=$(cat "$PIDFILE" 2>/dev/null || true)
  if [ -n "$pid" ] && [ -r "/proc/$pid/cmdline" ] && tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null | grep -Fq "$RUNNER"; then
    echo "Love8 collab runner already active: pid=$pid"
    exit 0
  fi
fi
rm -f "$PIDFILE"
if command -v setsid >/dev/null 2>&1; then
  nohup setsid "$RUNNER" >/dev/null 2>&1 &
else
  nohup "$RUNNER" >/dev/null 2>&1 &
fi
sleep 2
pid=$(cat "$PIDFILE" 2>/dev/null || true)
if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
  echo "Love8 collab runner ACTIVE: pid=$pid"
else
  echo "Love8 collab runner failed to start" >&2
  tail -n 40 "$LOGFILE" 2>/dev/null || true
  exit 1
fi
START_EOF
chmod 0755 "$STARTER"

if [ -f "$STOPPER" ]; then cp -a "$STOPPER" "$STOPPER.before-v2.8-$STAMP"; fi
cat >"$STOPPER" <<'STOP_EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
PIDFILE="/opt/technocore-collab/state/runner.pid"
RUNNER="/opt/technocore-collab/bin/runner.sh"
pid=$(cat "$PIDFILE" 2>/dev/null || true)
if [ -z "$pid" ] || [ ! -r "/proc/$pid/cmdline" ] || ! tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null | grep -Fq "$RUNNER"; then
  rm -f "$PIDFILE"
  echo "Love8 collab runner is not active"
  exit 0
fi
kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
sleep 2
rm -f "$PIDFILE"
echo "Love8 collab runner stopped"
STOP_EOF
chmod 0755 "$STOPPER"

if [ -f "$STATUS" ]; then cp -a "$STATUS" "$STATUS.before-v2.8-$STAMP"; fi
cat >"$STATUS" <<'STATUS_EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
PIDFILE="/opt/technocore-collab/state/runner.pid"
RUNNER="/opt/technocore-collab/bin/runner.sh"
LOGFILE="/opt/technocore-collab/state/runner.log"
pid=$(cat "$PIDFILE" 2>/dev/null || true)
if [ -n "$pid" ] && [ -r "/proc/$pid/cmdline" ] && tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null | grep -Fq "$RUNNER"; then
  echo "runner: ACTIVE pid=$pid"
  ps -o pid,ppid,stat,etime,cmd -p "$pid" 2>/dev/null || true
else
  echo "runner: INACTIVE"
fi
echo "log: $LOGFILE"
tail -n 20 "$LOGFILE" 2>/dev/null || true
STATUS_EOF
chmod 0755 "$STATUS"

if [ -f "$LOG_CMD" ]; then cp -a "$LOG_CMD" "$LOG_CMD.before-v2.8-$STAMP"; fi
cat >"$LOG_CMD" <<'LOG_EOF'
#!/usr/bin/env bash
exec tail -f /opt/technocore-collab/state/runner.log
LOG_EOF
chmod 0755 "$LOG_CMD"

if [ -d /etc/cron.d ]; then
  cat >"$CRONFILE" <<EOF
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
@reboot root $STARTER >>$ROOT/state/cron-start.log 2>&1
EOF
  chmod 0644 "$CRONFILE"
fi

PID1_COMM="$(tr -d '\0' </proc/1/comm 2>/dev/null || true)"
if [ "$PID1_COMM" = "systemd" ] && command -v systemctl >/dev/null 2>&1; then
  systemctl daemon-reload
  systemctl enable --now technocore-collab
  echo "startup_mode=systemd"
else
  "$STARTER"
  echo "startup_mode=no-systemd"
  if [ -d /etc/cron.d ]; then
    cron_alive=0
    if command -v pgrep >/dev/null 2>&1 && (pgrep -x cron >/dev/null 2>&1 || pgrep -x crond >/dev/null 2>&1); then
      cron_alive=1
    fi
    if [ "$cron_alive" = "1" ]; then
      echo "boot_autostart=cron_detected"
    else
      echo "boot_autostart=cron_file_installed_but_cron_not_detected"
    fi
  fi
fi

echo "=== LOVE8 A2A READY ==="
echo "agent=$AGENT_NAME"
echo "role=$ROLE"
echo "pid1=$PID1_COMM"
"$PYTHON" "$AGENT" status
"$STATUS"
echo "identity, .env, peers, cursor and workflow state were not replaced."
