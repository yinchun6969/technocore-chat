#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/technocore-collab"
STATE="$ROOT/state"
ENV_FILE="$ROOT/.env"
PY="$ROOT/venv/bin/python"
APP="$ROOT/bin/collab.py"
RUNNER="$ROOT/bin/run-forever.sh"
PIDFILE="$STATE/runner.pid"
LOCKFILE="$STATE/runner.lock"
LOGFILE="$STATE/runner.log"

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root: bash repair-single-runner-v2.4.sh"
  exit 1
fi
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE"; exit 1; }
[[ -x "$PY" ]] || { echo "Missing $PY"; exit 1; }
[[ -f "$APP" ]] || { echo "Missing $APP"; exit 1; }
command -v flock >/dev/null 2>&1 || { echo "Missing flock (util-linux)"; exit 1; }
mkdir -p "$STATE"

stop_all() {
  if [[ -s "$PIDFILE" ]]; then
    pid=$(cat "$PIDFILE" 2>/dev/null || true)
    if [[ "$pid" =~ ^[0-9]+$ ]]; then
      kill "$pid" 2>/dev/null || true
      for _ in $(seq 1 20); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.25
      done
      kill -9 "$pid" 2>/dev/null || true
    fi
  fi

  # Clean up orphaned runner shells from older v2.1/v2.2 installs.
  for pat in "$ROOT/bin/run-forever.sh" "$ROOT/bin/runner.sh"; do
    while read -r pid; do
      [[ -n "$pid" && "$pid" != "$$" ]] || continue
      kill "$pid" 2>/dev/null || true
    done < <(pgrep -f "$pat" 2>/dev/null || true)
  done

  # Clean up orphaned collab workers left behind when an old runner shell died.
  while read -r pid; do
    [[ -n "$pid" && "$pid" != "$$" ]] || continue
    kill "$pid" 2>/dev/null || true
  done < <(pgrep -f "$ROOT/bin/collab.py run" 2>/dev/null || true)

  sleep 1

  while read -r pid; do
    [[ -n "$pid" && "$pid" != "$$" ]] || continue
    kill -9 "$pid" 2>/dev/null || true
  done < <(pgrep -f "$ROOT/bin/collab.py run" 2>/dev/null || true)

  rm -f "$PIDFILE"
}

stop_all

cat > "$RUNNER" <<'EOF'
#!/usr/bin/env bash
set -u
ROOT=/opt/technocore-collab
STATE=$ROOT/state
ENV_FILE=$ROOT/.env
PY=$ROOT/venv/bin/python
APP=$ROOT/bin/collab.py
LOG=$STATE/runner.log
LOCK=$STATE/runner.lock

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "[$(date -Is)] another collab runner already owns the lock; exiting" >> "$LOG"
  exit 73
fi

child=""
cleanup() {
  trap - TERM INT EXIT
  if [[ -n "${child:-}" ]] && kill -0 "$child" 2>/dev/null; then
    kill "$child" 2>/dev/null || true
    for _ in $(seq 1 20); do
      kill -0 "$child" 2>/dev/null || break
      sleep 0.25
    done
    kill -9 "$child" 2>/dev/null || true
    wait "$child" 2>/dev/null || true
  fi
}
trap cleanup TERM INT EXIT

while true; do
  set -a
  . "$ENV_FILE"
  set +a
  echo "[$(date -Is)] starting collab sidecar" >> "$LOG"
  "$PY" "$APP" run >> "$LOG" 2>&1 &
  child=$!
  wait "$child"
  rc=$?
  child=""
  echo "[$(date -Is)] collab exited rc=$rc; restarting in 5s" >> "$LOG"
  sleep 5
done
EOF
chmod 0700 "$RUNNER"

cat > /usr/local/bin/tc-collab-start <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/opt/technocore-collab
STATE=$ROOT/state
PIDFILE=$STATE/runner.pid
LOGFILE=$STATE/runner.log
RUNNER=$ROOT/bin/run-forever.sh

if [[ -s "$PIDFILE" ]]; then
  pid=$(cat "$PIDFILE" 2>/dev/null || true)
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
    echo "active pid=$pid"
    exit 0
  fi
fi
rm -f "$PIDFILE"

# Refuse to stack a new runner on top of an orphan worker.
if pgrep -f "$ROOT/bin/collab.py run" >/dev/null 2>&1; then
  echo "orphan collab worker detected; run tc-collab-stop first"
  exit 1
fi

: >> "$LOGFILE"
nohup setsid "$RUNNER" </dev/null >>"$LOGFILE" 2>&1 &
echo $! > "$PIDFILE"
sleep 1
pid=$(cat "$PIDFILE")
kill -0 "$pid" 2>/dev/null && echo "active pid=$pid" || { echo "failed"; tail -n 30 "$LOGFILE"; exit 1; }
EOF

cat > /usr/local/bin/tc-collab-stop <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/opt/technocore-collab
PIDFILE=$ROOT/state/runner.pid

if [[ -s "$PIDFILE" ]]; then
  pid=$(cat "$PIDFILE" 2>/dev/null || true)
  if [[ "$pid" =~ ^[0-9]+$ ]]; then
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.25
    done
    kill -9 "$pid" 2>/dev/null || true
  fi
fi
rm -f "$PIDFILE"

# Sweep only this sidecar's exact worker pattern; do not touch other agents.
while read -r pid; do
  [[ -n "$pid" && "$pid" != "$$" ]] || continue
  kill "$pid" 2>/dev/null || true
done < <(pgrep -f "$ROOT/bin/collab.py run" 2>/dev/null || true)
sleep 1
while read -r pid; do
  [[ -n "$pid" && "$pid" != "$$" ]] || continue
  kill -9 "$pid" 2>/dev/null || true
done < <(pgrep -f "$ROOT/bin/collab.py run" 2>/dev/null || true)
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
if [[ -s "$PIDFILE" ]]; then
  pid=$(cat "$PIDFILE" 2>/dev/null || true)
else
  pid=""
fi
if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
  echo "runner: ACTIVE pid=$pid"
  ps -o pid,ppid,etime,cmd -p "$pid" || true
else
  echo "runner: INACTIVE"
fi
mapfile -t workers < <(pgrep -f "$ROOT/bin/collab.py run" 2>/dev/null || true)
echo "workers: ${#workers[@]}"
for w in "${workers[@]}"; do
  ps -o pid,ppid,etime,cmd -p "$w" || true
done
[[ ${#workers[@]} -eq 1 ]] || exit 2
EOF

chmod 0755 /usr/local/bin/tc-collab-{start,stop,restart,process-status}

/usr/local/bin/tc-collab-start
sleep 2

echo "=== V2.4 SINGLE-RUNNER GUARD ==="
tc-collab-status || true
echo
tc-collab-process-status

echo
echo "v2.4 applied. Expected final state: runner ACTIVE, workers: 1"
echo "DID/key/mailbox/role/AI/peer/task-state files were not changed."
