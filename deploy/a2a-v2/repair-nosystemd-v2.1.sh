#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/technocore-collab"
ENV_FILE="$ROOT/.env"
PY="$ROOT/venv/bin/python"
APP="$ROOT/bin/collab.py"
STATE="$ROOT/state"
RUNNER="$ROOT/bin/run-forever.sh"
PIDFILE="$STATE/runner.pid"
LOGFILE="$STATE/runner.log"

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root: bash repair-nosystemd-v2.1.sh"
  exit 1
fi

[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE"; exit 1; }
[[ -x "$PY" ]] || { echo "Missing $PY"; exit 1; }
[[ -f "$APP" ]] || { echo "Missing $APP"; exit 1; }
mkdir -p "$STATE"
chmod 0700 "$STATE"

cat > "$RUNNER" <<'EOF'
#!/usr/bin/env bash
set -u
ROOT="/opt/technocore-collab"
ENV_FILE="$ROOT/.env"
PY="$ROOT/venv/bin/python"
APP="$ROOT/bin/collab.py"
LOG="$ROOT/state/runner.log"

while true; do
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
  printf '[%s] starting collab.py\n' "$(date -u +%FT%TZ)" >> "$LOG"
  "$PY" "$APP" run >> "$LOG" 2>&1
  rc=$?
  printf '[%s] collab.py exited rc=%s; restarting in 5s\n' "$(date -u +%FT%TZ)" "$rc" >> "$LOG"
  sleep 5
done
EOF
chmod 0700 "$RUNNER"

is_running() {
  [[ -s "$PIDFILE" ]] || return 1
  local pid
  pid=$(cat "$PIDFILE" 2>/dev/null || true)
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null
}

stop_runner() {
  if is_running; then
    pid=$(cat "$PIDFILE")
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.25
    done
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$PIDFILE"
}

start_runner() {
  if is_running; then
    echo "runner already active pid=$(cat "$PIDFILE")"
    return 0
  fi
  : >> "$LOGFILE"
  nohup setsid "$RUNNER" </dev/null >>"$LOGFILE" 2>&1 &
  echo $! > "$PIDFILE"
  sleep 1
  if ! is_running; then
    echo "runner failed to stay up; tail follows:"
    tail -n 30 "$LOGFILE" || true
    exit 1
  fi
  echo "runner active pid=$(cat "$PIDFILE")"
}

cat > /usr/local/bin/tc-collab-start <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/opt/technocore-collab
PIDFILE=$ROOT/state/runner.pid
LOGFILE=$ROOT/state/runner.log
RUNNER=$ROOT/bin/run-forever.sh
if [[ -s "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "active pid=$(cat "$PIDFILE")"
  exit 0
fi
rm -f "$PIDFILE"
: >> "$LOGFILE"
nohup setsid "$RUNNER" </dev/null >>"$LOGFILE" 2>&1 &
echo $! > "$PIDFILE"
sleep 1
kill -0 "$(cat "$PIDFILE")" 2>/dev/null && echo "active pid=$(cat "$PIDFILE")" || { echo "failed"; tail -n 30 "$LOGFILE"; exit 1; }
EOF

cat > /usr/local/bin/tc-collab-stop <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/opt/technocore-collab
PIDFILE=$ROOT/state/runner.pid
if [[ -s "$PIDFILE" ]]; then
  pid=$(cat "$PIDFILE")
  kill "$pid" 2>/dev/null || true
  sleep 1
  kill -9 "$pid" 2>/dev/null || true
fi
rm -f "$PIDFILE"
echo stopped
EOF

cat > /usr/local/bin/tc-collab-restart <<'EOF'
#!/usr/bin/env bash
set -e
/usr/local/bin/tc-collab-stop
/usr/local/bin/tc-collab-start
EOF

cat > /usr/local/bin/tc-collab-process-status <<'EOF'
#!/usr/bin/env bash
ROOT=/opt/technocore-collab
PIDFILE=$ROOT/state/runner.pid
if [[ -s "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  pid=$(cat "$PIDFILE")
  echo "runner: ACTIVE pid=$pid"
  ps -o pid,ppid,etime,cmd -p "$pid" || true
  pgrep -af '/opt/technocore-collab/bin/collab.py run' || true
else
  echo "runner: INACTIVE"
  exit 1
fi
EOF

cat > /usr/local/bin/tc-collab-log <<'EOF'
#!/usr/bin/env bash
exec tail -F /opt/technocore-collab/state/runner.log
EOF

chmod 0755 /usr/local/bin/tc-collab-{start,stop,restart,process-status,log}

# Remove a stale PID from an earlier attempt, but do not touch the existing DID/key/mailbox config.
if is_running; then
  echo "existing non-systemd runner detected; restarting cleanly"
  stop_runner
fi

# The original installer already primed the cursor. Do not prime again and do not replay old mail.
set -a
source "$ENV_FILE"
set +a
printf 'Model recheck...\n'
"$PY" "$APP" ai-test

start_runner

printf '\n=== IDENTITY / COLLAB CONFIG ===\n'
tc-collab-status
printf '\n=== PROCESS ===\n'
tc-collab-process-status
printf '\n=== LAST LOGS ===\n'
tail -n 15 "$LOGFILE" || true
printf '\nNon-systemd watchdog installed. Existing DID/private key/mailbox preserved.\n'
printf 'Commands: tc-collab-start | tc-collab-stop | tc-collab-restart | tc-collab-process-status | tc-collab-log\n'
