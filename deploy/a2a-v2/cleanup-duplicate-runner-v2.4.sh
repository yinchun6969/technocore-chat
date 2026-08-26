#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/opt/technocore-collab
STATE="$ROOT/state"
PIDFILE="$STATE/runner.pid"
LOGFILE="$STATE/runner.log"
RUNNER="$ROOT/bin/run-forever.sh"
ALT_RUNNER="$ROOT/bin/runner.sh"
APP="$ROOT/bin/collab.py"
PY="$ROOT/venv/bin/python"

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root: bash cleanup-duplicate-runner-v2.4.sh"
  exit 1
fi
[[ -f "$ROOT/.env" ]] || { echo "Missing $ROOT/.env"; exit 1; }
[[ -f "$APP" ]] || { echo "Missing $APP"; exit 1; }
[[ -x "$PY" ]] || { echo "Missing $PY"; exit 1; }
mkdir -p "$STATE"

# Stop the tracked runner first, then clean any orphaned runner/worker left by
# older watchdog versions. This does not touch identity, config, peers or state.
if command -v tc-collab-stop >/dev/null 2>&1; then
  tc-collab-stop || true
fi

for pat in \
  '/opt/technocore-collab/bin/collab.py run' \
  '/opt/technocore-collab/bin/run-forever.sh' \
  '/opt/technocore-collab/bin/runner.sh'; do
  pids=$(pgrep -f "$pat" 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    kill $pids 2>/dev/null || true
  fi
done
sleep 2
for pat in \
  '/opt/technocore-collab/bin/collab.py run' \
  '/opt/technocore-collab/bin/run-forever.sh' \
  '/opt/technocore-collab/bin/runner.sh'; do
  pids=$(pgrep -f "$pat" 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    kill -9 $pids 2>/dev/null || true
  fi
done
rm -f "$PIDFILE"

# Prefer the v2.1+ watchdog. Fall back to the older runner if necessary.
if [[ ! -x "$RUNNER" ]]; then
  [[ -x "$ALT_RUNNER" ]] || { echo "No watchdog runner found"; exit 1; }
  RUNNER="$ALT_RUNNER"
fi

cat > /usr/local/bin/tc-collab-stop <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/opt/technocore-collab
PIDFILE=$ROOT/state/runner.pid
if [[ -s "$PIDFILE" ]]; then
  pid=$(cat "$PIDFILE" 2>/dev/null || true)
  [[ "$pid" =~ ^[0-9]+$ ]] && kill "$pid" 2>/dev/null || true
fi
for pat in \
  '/opt/technocore-collab/bin/collab.py run' \
  '/opt/technocore-collab/bin/run-forever.sh' \
  '/opt/technocore-collab/bin/runner.sh'; do
  pids=$(pgrep -f "$pat" 2>/dev/null || true)
  [[ -n "$pids" ]] && kill $pids 2>/dev/null || true
done
sleep 1
for pat in \
  '/opt/technocore-collab/bin/collab.py run' \
  '/opt/technocore-collab/bin/run-forever.sh' \
  '/opt/technocore-collab/bin/runner.sh'; do
  pids=$(pgrep -f "$pat" 2>/dev/null || true)
  [[ -n "$pids" ]] && kill -9 $pids 2>/dev/null || true
done
rm -f "$PIDFILE"
echo stopped
EOF

cat > /usr/local/bin/tc-collab-start <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/opt/technocore-collab
STATE=$ROOT/state
PIDFILE=$STATE/runner.pid
LOGFILE=$STATE/runner.log
RUNNER=$ROOT/bin/run-forever.sh
[[ -x "$RUNNER" ]] || RUNNER=$ROOT/bin/runner.sh
[[ -x "$RUNNER" ]] || { echo "runner missing"; exit 1; }
mkdir -p "$STATE"
# Refuse to stack a second watchdog on an already-live worker.
workers=$(pgrep -fc '/opt/technocore-collab/bin/collab.py run' 2>/dev/null || true)
if [[ "$workers" -gt 0 ]]; then
  echo "worker already active; refusing duplicate start"
  exit 1
fi
: >> "$LOGFILE"
nohup setsid "$RUNNER" </dev/null >>"$LOGFILE" 2>&1 &
echo $! > "$PIDFILE"
sleep 2
pid=$(cat "$PIDFILE")
kill -0 "$pid" 2>/dev/null || { echo "runner failed"; tail -n 30 "$LOGFILE"; exit 1; }
workers=$(pgrep -fc '/opt/technocore-collab/bin/collab.py run' 2>/dev/null || true)
[[ "$workers" -eq 1 ]] || { echo "expected exactly one worker; got $workers"; exit 1; }
echo "active pid=$pid worker_count=$workers"
EOF
chmod 0755 /usr/local/bin/tc-collab-{start,stop}

# Start a single clean watchdog + worker.
: >> "$LOGFILE"
nohup setsid "$RUNNER" </dev/null >>"$LOGFILE" 2>&1 &
echo $! > "$PIDFILE"
sleep 3

runner_pid=$(cat "$PIDFILE" 2>/dev/null || true)
workers=$(pgrep -fc '/opt/technocore-collab/bin/collab.py run' 2>/dev/null || true)
runners=$(pgrep -fc '/opt/technocore-collab/bin/(run-forever|runner)\.sh' 2>/dev/null || true)

echo "=== SINGLE-WORKER CHECK ==="
echo "runner_pid: $runner_pid"
echo "runner_count: $runners"
echo "worker_count: $workers"
pgrep -af '/opt/technocore-collab/bin/(run-forever|runner)\.sh|/opt/technocore-collab/bin/collab.py run' || true

echo
if [[ "$workers" -ne 1 ]]; then
  echo "ERROR: expected exactly one collab.py worker"
  exit 1
fi
if [[ -z "$runner_pid" ]] || ! kill -0 "$runner_pid" 2>/dev/null; then
  echo "ERROR: runner is not active"
  exit 1
fi

echo "SINGLE_WORKER_OK"
echo "v2.4 applied. DID/key/mailbox/role/AI/peers/provenance unchanged."
