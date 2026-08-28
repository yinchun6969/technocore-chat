#!/usr/bin/env bash
set -Eeuo pipefail

# R&D v5 progress/delivery repair. Does not replace identity or state.
REPO_RAW="https://raw.githubusercontent.com/yinchun6969/technocore-chat"
SOURCE_REF="70bf99b6ae677a92adbab986f6b8019ec48ea723"
SOURCE_BASE="$REPO_RAW/$SOURCE_REF/deploy/a2a-v5"
AI_ROOT="/opt/technocore-a2a"
COLLAB_ROOT="/opt/technocore-collab"
BACKUP_ROOT="/root/tc-a2a-progress-fix-v3-backups"

die() { echo "[x] $*" >&2; exit 1; }
need_root() { [[ "$EUID" -eq 0 ]] || die "Run as root"; }
is_systemd() { [[ "$(tr -d '\0' </proc/1/comm 2>/dev/null || true)" == "systemd" ]]; }

install_ai2ai() {
  local root="$AI_ROOT"
  local director="$root/rnd-v5/autonomous-rnd-v5.py"
  local telegram="$root/rnd-v5/telegram-control-v1.py"
  local python="$root/venv/bin/python"
  local stamp backup
  [[ -x "$python" && -f "$root/.env" ]] || die "Existing AI2AI runtime not found"
  [[ -f "$director" && -f "$telegram" ]] || die "Existing v5 files not found"
  id tcagent >/dev/null 2>&1 || die "tcagent user not found"

  stamp="$(date -u +%Y%m%d-%H%M%S)"
  backup="$BACKUP_ROOT/ai2ai/$stamp"
  install -d -m 0700 "$backup"
  local items=(
    opt/technocore-a2a/rnd-v5/autonomous-rnd-v5.py
    opt/technocore-a2a/rnd-v5/telegram-control-v1.py
    opt/technocore-a2a/rnd-v5-state/director.json
    opt/technocore-a2a/rnd-v5-state/director.log
    opt/technocore-a2a/rnd-v5-state/notify.json
    etc/systemd/system/technocore-a2a-rnd-v5.service
    etc/systemd/system/technocore-a2a-telegram.service
  )
  local existing=()
  local item
  for item in "${items[@]}"; do [[ -e "/$item" ]] && existing+=( "$item" ); done
  (("${#existing[@]}" > 0)) || die "No existing AI2AI files available for backup"
  tar -C / -czf "$backup/prechange.tgz" --ignore-failed-read "${existing[@]}"
  sha256sum "$backup/prechange.tgz" > "$backup/SHA256SUMS"
  chmod 0600 "$backup/prechange.tgz" "$backup/SHA256SUMS"
  cat > "$backup/MANIFEST" <<EOF
version=progress-delivery-fix-v3
node=ai2ai
host=$(hostname)
utc=$(date -u -Is)
source_ref=$SOURCE_REF
policy=restore-code-only; preserve-identity-and-state
EOF
  chmod 0600 "$backup/MANIFEST"

  cat > /usr/local/bin/tc-a2a-progress-fix-v3-rollback <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
BACKUP="$backup"
if [[ -f "$BACKUP/prechange.tgz" ]]; then
  tar -C / -xzf "$BACKUP/prechange.tgz" \
    opt/technocore-a2a/rnd-v5/autonomous-rnd-v5.py \
    opt/technocore-a2a/rnd-v5/telegram-control-v1.py \
    etc/systemd/system/technocore-a2a-rnd-v5.service \
    etc/systemd/system/technocore-a2a-telegram.service 2>/dev/null || true
fi
systemctl daemon-reload
systemctl restart technocore-a2a-rnd-v5.service technocore-a2a-telegram.service 2>/dev/null || true
echo "rollback=completed"
echo "preserved=identity,mailbox,cursor,provenance,rnd-v5-state"
echo "backup=$BACKUP"
EOF
  chmod 0700 /usr/local/bin/tc-a2a-progress-fix-v3-rollback

  local tmp
  tmp="$(mktemp -d /root/tc-a2a-progress-fix-v3.XXXXXX)"
  trap 'rm -rf "$tmp"' RETURN
  curl -fL --retry 5 --retry-delay 2 "$SOURCE_BASE/autonomous-rnd-v5.py" -o "$tmp/director.py"
  curl -fL --retry 5 --retry-delay 2 "$SOURCE_BASE/telegram-control-v1.py" -o "$tmp/telegram.py"
  grep -Fq "retry_after_delivery_timeout" "$tmp/director.py" || die "delivery retry patch missing"
  grep -Fq "expired_workflows" "$tmp/director.py" || die "expiry dedupe patch missing"
  grep -Fq "discussion_last_error" "$tmp/director.py" || die "room diagnostics patch missing"
  grep -Fq "workflow_active_expired" "$tmp/telegram.py" || die "Telegram dedupe patch missing"
  "$python" -m py_compile "$tmp/director.py" "$tmp/telegram.py"
  install -o root -g tcagent -m 0750 "$tmp/director.py" "$director"
  install -o root -g tcagent -m 0750 "$tmp/telegram.py" "$telegram"
  trap - RETURN
  rm -rf "$tmp"

  systemctl daemon-reload
  systemctl restart technocore-a2a-rnd-v5.service technocore-a2a-telegram.service
  sleep 4
  if ! systemctl is-active --quiet technocore-a2a-rnd-v5.service || ! systemctl is-active --quiet technocore-a2a-telegram.service; then
    echo "[x] A service failed after the update; restoring the backup" >&2
    /usr/local/bin/tc-a2a-progress-fix-v3-rollback || true
    exit 1
  fi
  echo "=== AI2AI PROGRESS/DELIVERY FIX v3 READY ==="
  echo "director=active"
  echo "telegram=active"
  echo "delivery_timeout=1800s; one retry then normal 7200s cadence"
  echo "expiry_notifications=deduplicated"
  echo "backup=$backup"
  echo "rollback=tc-a2a-progress-fix-v3-rollback"
}

install_love8() {
  local root="$COLLAB_ROOT"
  local agent="$root/bin/collab.py"
  local python="$root/venv/bin/python"
  local stamp backup
  [[ -x "$python" && -f "$root/.env" && -f "$agent" ]] || die "Existing Love8 collab runtime not found"
  grep -q 'WORKFLOW_V3_BEGIN' "$agent" || die "Love8 workflow v3 marker missing"
  set -a; source "$root/.env"; set +a
  [[ "${AGENT_NAME:-}" == "love8" && "${ROLE:-}" == "scout" ]] || die "This host is not Love8 Scout"

  stamp="$(date -u +%Y%m%d-%H%M%S)"
  backup="$BACKUP_ROOT/love8/$stamp"
  install -d -m 0700 "$backup"
  local items=(
    opt/technocore-collab/.env
    opt/technocore-collab/bin/collab.py
    opt/technocore-collab/state/scheduler_gate.json
    etc/systemd/system/technocore-collab.service
  )
  local existing=()
  local item
  for item in "${items[@]}"; do [[ -e "/$item" ]] && existing+=( "$item" ); done
  (("${#existing[@]}" > 0)) || die "No existing Love8 files available for backup"
  tar -C / -czf "$backup/prechange.tgz" --ignore-failed-read "${existing[@]}"
  sha256sum "$backup/prechange.tgz" > "$backup/SHA256SUMS"
  chmod 0600 "$backup/prechange.tgz" "$backup/SHA256SUMS"
  cat > "$backup/MANIFEST" <<EOF
version=progress-delivery-fix-v3
node=love8
host=$(hostname)
utc=$(date -u -Is)
policy=restore-code-only; preserve-identity-and-state
EOF
  chmod 0600 "$backup/MANIFEST"

  cat > /usr/local/bin/tc-collab-progress-fix-v3-rollback <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
BACKUP="$backup"
ROOT="$root"
if [[ -f "$BACKUP/prechange.tgz" ]]; then
  tar -C / -xzf "$BACKUP/prechange.tgz" \
    opt/technocore-collab/.env \
    opt/technocore-collab/bin/collab.py \
    opt/technocore-collab/state/scheduler_gate.json \
    etc/systemd/system/technocore-collab.service 2>/dev/null || true
fi
if [[ "$(tr -d '\0' </proc/1/comm 2>/dev/null || true)" == "systemd" ]]; then
  systemctl daemon-reload
  systemctl restart technocore-collab
elif command -v tc-collab-stop >/dev/null 2>&1 && command -v tc-collab-start >/dev/null 2>&1; then
  tc-collab-stop || true
  tc-collab-start
fi
echo "rollback=completed"
echo "preserved=identity,mailbox,cursor,provenance"
echo "backup=$BACKUP"
EOF
  chmod 0700 /usr/local/bin/tc-collab-progress-fix-v3-rollback

  python3 - "$agent" <<'PY'
from pathlib import Path
import sys

p = Path(sys.argv[1])
s = p.read_text(encoding="utf-8")
start = s.find("# AUTONOMOUS_SCHEDULER_GATE_V29")
if start < 0:
    if "# AUTONOMOUS_SCHEDULER_GATE_V30" in s:
        print("Love8 scheduler gate v3 already installed")
        raise SystemExit(0)
    raise SystemExit("scheduler gate v2.9 block missing; no changes made")
end_marker = "# AUTONOMOUS_SCHEDULER_GATE_V29_END"
end = s.find(end_marker, start)
if end < 0:
    raise SystemExit("scheduler gate end marker missing; no changes made")
end += len(end_marker)

block = r'''# AUTONOMOUS_SCHEDULER_GATE_V30
SCHEDULER_GATE_PATH = STATE / 'scheduler_gate.json'
SCHEDULER_REQUEST_TYPE = 'SCHEDULER_REQUEST'
SCHEDULER_GATE_MAX_ACTIVE_SECONDS = 5400

def scheduler_gate_load():
    return loadj(SCHEDULER_GATE_PATH,{})

def scheduler_gate_save(value):
    savej(SCHEDULER_GATE_PATH,value)

def scheduler_gate_clear():
    try:
        SCHEDULER_GATE_PATH.unlink()
    except FileNotFoundError:
        pass

def scheduler_gate_expired(gate):
    try:
        started=float(gate.get('started_at',0) or 0)
    except (TypeError,ValueError):
        return True
    return not started or time.time()-started >= SCHEDULER_GATE_MAX_ACTIVE_SECONDS

def scheduler_request_handle(sender,x):
    if x.get('type') != SCHEDULER_REQUEST_TYPE:
        return False
    k=wf_key(sender,x)
    if k in wf_seen():
        return True
    if sender != AI2AI_DID or x.get('origin') != 'ai2ai-scheduler':
        ledger('scheduler_request_rejected',peer_did=sender,request_id=x.get('task_id',''))
        wf_mark(k)
        return True
    goal=' '.join(str(x.get('goal','')).splitlines()).strip()[:1400]
    request_id=str(x.get('task_id','')).strip()
    if not goal or not request_id:
        ledger('scheduler_request_invalid',peer_did=sender,request_id=request_id)
        wf_mark(k)
        return True
    gate=scheduler_gate_load()
    if not isinstance(gate,dict):
        gate={}
    if gate.get('workflow_id') and not scheduler_gate_expired(gate):
        ledger('scheduler_request_busy',peer_did=sender,request_id=request_id,active_workflow_id=gate.get('workflow_id'))
        return True
    tid=f'wf-{int(time.time())}-{hashlib.sha256((DID+goal+request_id).encode()).hexdigest()[:10]}'
    wf_send(AIZONG_DID,'WORKFLOW_TASK',tid,goal=goal,
            scout_did=LOVE8_DID,builder_did=AIZONG_DID,reviewer_did=AI2AI_DID,
            origin='ai2ai-scheduler',scheduler_request_id=request_id)
    scheduler_gate_save({'workflow_id':tid,'request_id':request_id,
                         'started_at':time.time(),'gate_version':'v30'})
    ledger('workflow_started',workflow_id=tid,peer_did=AIZONG_DID,origin='ai2ai-scheduler',
           scheduler_request_id=request_id,goal_sha256=hashlib.sha256(goal.encode()).hexdigest())
    wf_mark(k)
    return True
# AUTONOMOUS_SCHEDULER_GATE_V30_END

'''
s = s[:start] + block + s[end:]
needle = "    if not x or not trusted(sender): return\n"
if "if scheduler_request_handle(sender,x): return" not in s:
    if needle not in s:
        raise SystemExit("workflow dispatch marker missing; no changes made")
    s = s.replace(needle, needle + "    if scheduler_request_handle(sender,x): return\n", 1)
p.write_text(s, encoding="utf-8")
print("Love8 scheduler gate v3 patched")
PY

  "$python" -m py_compile "$agent"
  if is_systemd; then
    systemctl daemon-reload
    systemctl restart technocore-collab
  elif command -v tc-collab-stop >/dev/null 2>&1 && command -v tc-collab-start >/dev/null 2>&1; then
    tc-collab-stop || true
    tc-collab-start
  else
    die "Love8 has neither systemd nor collab runner; files were not restarted"
  fi
  sleep 3
  if is_systemd; then
    systemctl is-active --quiet technocore-collab || die "Love8 service failed; run tc-collab-progress-fix-v3-rollback"
  elif command -v tc-collab-process-status >/dev/null 2>&1; then
    tc-collab-process-status | grep -q "runner: ACTIVE" || die "Love8 runner failed; run tc-collab-progress-fix-v3-rollback"
  fi
  echo "=== LOVE8 SCHEDULER GATE v3 READY ==="
  echo "gate_max_active=5400s"
  echo "stale_gate_is_released=1"
  echo "backup=$backup"
  echo "rollback=tc-collab-progress-fix-v3-rollback"
}

need_root
if [[ -f "$AI_ROOT/.env" ]]; then
  set -a; source "$AI_ROOT/.env"; set +a
  [[ "${AGENT_NAME:-}" == "ai2ai" ]] && { install_ai2ai; exit 0; }
fi
if [[ -f "$COLLAB_ROOT/.env" ]]; then
  set -a; source "$COLLAB_ROOT/.env"; set +a
  [[ "${AGENT_NAME:-}" == "love8" ]] && { install_love8; exit 0; }
fi
die "Unknown existing node; no identity or installation was created"
