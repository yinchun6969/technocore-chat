9afb36f3a370c6f420f9b2ff6981e7be5edf00ed9ec19034cd9acb21614d42d1  install-autonomous-scheduler-v2_9.sh
516a4b41705f0f29fc6b58d273ba2e1d25044aa4ab9249ba105ec41ceb64e55b  autonomous-scheduler-v2_9.py
#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="autonomous-v2.9"
BACKUP_ROOT="/root/tc-a2a-autonomous-v2.9-backups"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
BRANCH="a2a-autonomous-v2.9"
SCHEDULER_URL="https://raw.githubusercontent.com/yinchun6969/technocore-chat/$BRANCH/deploy/a2a-v3/autonomous-scheduler-v2.9.py"
SCHEDULER_SHA256="516a4b41705f0f29fc6b58d273ba2e1d25044aa4ab9249ba105ec41ceb64e55b"

die() { printf '\n[x] %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "请用 root 执行"
command -v python3 >/dev/null 2>&1 || die "缺少 python3"
command -v curl >/dev/null 2>&1 || die "缺少 curl"
command -v sha256sum >/dev/null 2>&1 || die "缺少 sha256sum"

make_backup() {
  local root="$1"
  local role="$2"
  local code_rel="$3"
  local unit="$4"
  local out="$BACKUP_ROOT/$role/$STAMP"
  install -d -m 0700 "$out"
  tar -C "$root" -czf "$out/root-code-config-state.tgz" .env "$code_rel" state
  if [ -f "$unit" ]; then
    cp -a "$unit" "$out/service.unit"
  fi
  sha256sum "$out/root-code-config-state.tgz" >"$out/SHA256SUMS"
  {
    echo "version=$VERSION"
    echo "role=$role"
    echo "host=$(hostname)"
    echo "utc=$(date -u -Is)"
    echo "root=$root"
    echo "code=$code_rel"
    echo "unit=$unit"
    echo "state_restore_policy=code_and_unit_only; current cursor/provenance state is preserved on rollback"
  } >"$out/MANIFEST"
  chmod 0600 "$out/root-code-config-state.tgz" "$out/SHA256SUMS" "$out/MANIFEST"
  printf '%s\n' "$out"
}

install_ai2ai() {
  local root="/opt/technocore-a2a"
  local env_file="$root/.env"
  local agent="$root/bin/agent.py"
  local scheduler="$root/bin/autonomous_scheduler.py"
  local service_unit="/etc/systemd/system/technocore-a2a-scheduler.service"
  local backup
  local tmp

  [ -f "$env_file" ] || die "AI2AI 缺少 $env_file"
  [ -f "$agent" ] || die "AI2AI 缺少 $agent"
  id tcagent >/dev/null 2>&1 || die "AI2AI 缺少 tcagent 用户"
  grep -q 'WORKFLOW_V3_REVIEWER_BEGIN' "$agent" || die "AI2AI 尚未安装 workflow v3 Reviewer"
  grep -q 'A2A_WIRE_GUARD_V20' "$agent" || die "AI2AI 尚未安装 wire guard v2.0"
  [ -x "$root/venv/bin/python" ] || die "AI2AI 缺少 venv Python"
  [ "$(tr -d '\0' </proc/1/comm 2>/dev/null || true)" = "systemd" ] || die "AI2AI 不是 systemd 主机，暂不覆盖现有 Reviewer"

  backup="$(make_backup "$root" "ai2ai" "bin/agent.py" "$service_unit")"
  if [ -f "$scheduler" ]; then
    cp -a "$scheduler" "$backup/existing-autonomous_scheduler.py"
  fi
  for cmd in tc-a2a-scheduler-status tc-a2a-scheduler-pause tc-a2a-scheduler-resume tc-a2a-scheduler-reset; do
    if [ -f "/usr/local/bin/$cmd" ]; then
      cp -a "/usr/local/bin/$cmd" "$backup/$cmd.before"
    fi
  done

  systemctl stop technocore-a2a-scheduler.service 2>/dev/null || true
  tmp="$(mktemp)"
  trap 'rm -f "$tmp"' RETURN
  curl -fL --retry 5 --retry-delay 2 "$SCHEDULER_URL" -o "$tmp"
  echo "$SCHEDULER_SHA256  $tmp" | sha256sum -c -
  install -o root -g tcagent -m 0750 "$tmp" "$scheduler"
  rm -f "$tmp"
  trap - RETURN

  cat >"$service_unit" <<EOF
[Unit]
Description=Technocore AI2AI autonomous research scheduler v2.9
After=network-online.target technocore-a2a.service
Wants=network-online.target

[Service]
Type=simple
User=tcagent
Group=tcagent
EnvironmentFile=$env_file
Environment=SCHEDULER_INTERVAL_SECONDS=21600
Environment=SCHEDULER_MAX_DAILY=4
Environment=SCHEDULER_MAX_ACTIVE_SECONDS=14400
Environment=SCHEDULER_TICK_SECONDS=60
Environment=SCHEDULER_START_DELAY_SECONDS=180
ExecStart=$root/venv/bin/python $scheduler run
Restart=always
RestartSec=15
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=$root/state $root/identity
ProtectHome=true

[Install]
WantedBy=multi-user.target
EOF

  cat > /usr/local/bin/tc-a2a-scheduler-status <<EOF
#!/usr/bin/env bash
set -a
source $env_file
set +a
exec $root/venv/bin/python $scheduler status
EOF
  cat > /usr/local/bin/tc-a2a-scheduler-pause <<EOF
#!/usr/bin/env bash
set -a
source $env_file
set +a
exec $root/venv/bin/python $scheduler pause
EOF
  cat > /usr/local/bin/tc-a2a-scheduler-resume <<EOF
#!/usr/bin/env bash
set -a
source $env_file
set +a
exec $root/venv/bin/python $scheduler resume
EOF
  cat > /usr/local/bin/tc-a2a-scheduler-reset <<EOF
#!/usr/bin/env bash
set -a
source $env_file
set +a
exec $root/venv/bin/python $scheduler reset-active
EOF
  chmod 0755 /usr/local/bin/tc-a2a-scheduler-{status,pause,resume,reset}

  cat > /usr/local/bin/tc-a2a-autonomous-rollback <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$root"
BACKUP="$backup"
UNIT="$service_unit"
SCHEDULER="$scheduler"

systemctl stop technocore-a2a-scheduler.service 2>/dev/null || true
if [ -f "\$BACKUP/root-code-config-state.tgz" ]; then
  tar -C "\$ROOT" -xzf "\$BACKUP/root-code-config-state.tgz" .env bin/agent.py
fi
if [ -f "\$BACKUP/service.unit" ]; then
  cp -a "\$BACKUP/service.unit" "\$UNIT"
else
  rm -f "\$UNIT"
fi
if [ -f "\$BACKUP/existing-autonomous_scheduler.py" ]; then
  cp -a "\$BACKUP/existing-autonomous_scheduler.py" "\$SCHEDULER"
else
  rm -f "\$SCHEDULER"
fi
for cmd in tc-a2a-scheduler-status tc-a2a-scheduler-pause tc-a2a-scheduler-resume tc-a2a-scheduler-reset; do
  if [ -f "\$BACKUP/\$cmd.before" ]; then
    cp -a "\$BACKUP/\$cmd.before" "/usr/local/bin/\$cmd"
  else
    rm -f "/usr/local/bin/\$cmd"
  fi
done
rm -f "\$ROOT/state/autonomous_scheduler.json" "\$ROOT/state/autonomous_scheduler.log" "\$ROOT/state/autonomous_scheduler.lock"
systemctl daemon-reload
systemctl restart technocore-a2a.service
echo "AI2AI autonomous scheduler rolled back"
systemctl is-active technocore-a2a.service
echo "Backup: \$BACKUP"
EOF
  chmod 0700 /usr/local/bin/tc-a2a-autonomous-rollback

  chown root:tcagent "$scheduler"
  chmod 0750 "$scheduler"
  chown -R tcagent:tcagent "$root/state"
  systemctl daemon-reload
  systemctl enable --now technocore-a2a-scheduler.service
  sleep 3
  systemctl is-active --quiet technocore-a2a-scheduler.service || {
    systemctl --no-pager --full status technocore-a2a-scheduler.service || true
    die "AI2AI autonomous scheduler 启动失败；回退命令：tc-a2a-autonomous-rollback"
  }
  echo "=== AI2AI AUTONOMOUS SCHEDULER v2.9 READY ==="
  echo "service=$(systemctl is-active technocore-a2a-scheduler.service)"
  "$root/venv/bin/python" "$scheduler" status
  echo "backup=$backup"
  echo "rollback=tc-a2a-autonomous-rollback"
}

install_love8() {
  local root="/opt/technocore-collab"
  local env_file="$root/.env"
  local agent="$root/bin/collab.py"
  local unit="/etc/systemd/system/technocore-collab.service"
  local backup
  local pid1

  [ -f "$env_file" ] || die "Love8 缺少 $env_file"
  [ -f "$agent" ] || die "Love8 缺少 $agent"
  grep -q 'WORKFLOW_V3_BEGIN' "$agent" || die "Love8 尚未安装 workflow v3"
  [ -x "$root/venv/bin/python" ] || die "Love8 缺少 venv Python"
  set -a
  # shellcheck disable=SC1090
  source "$env_file"
  set +a
  [ "$AGENT_NAME" = "love8" ] || die "当前不是 Love8：$AGENT_NAME"
  [ "$ROLE" = "scout" ] || die "Love8 角色不是 scout：$ROLE"

  backup="$(make_backup "$root" "love8" "bin/collab.py" "$unit")"
  python3 - "$agent" <<'PY'
from pathlib import Path
import sys

p = Path(sys.argv[1])
s = p.read_text()
marker = "# AUTONOMOUS_SCHEDULER_GATE_V29"
if marker in s:
    print("autonomous scheduler gate already installed")
    raise SystemExit(0)
if "# WORKFLOW_V3_BEGIN" not in s:
    raise SystemExit("workflow v3 marker missing; no changes made")

insert_at = s.find("def workflow_handle(sender,x):\n")
if insert_at < 0:
    raise SystemExit("workflow_handle marker missing; no changes made")

block = r'''# AUTONOMOUS_SCHEDULER_GATE_V29
SCHEDULER_GATE_PATH = STATE / 'scheduler_gate.json'
SCHEDULER_REQUEST_TYPE = 'SCHEDULER_REQUEST'

def scheduler_gate_load():
    return loadj(SCHEDULER_GATE_PATH,{})

def scheduler_gate_save(value):
    savej(SCHEDULER_GATE_PATH,value)

def scheduler_gate_clear():
    try:
        SCHEDULER_GATE_PATH.unlink()
    except FileNotFoundError:
        pass

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
    started=float(gate.get('started_at',0) or 0)
    if gate.get('workflow_id') and started and time.time()-started < 21600:
        ledger('scheduler_request_busy',peer_did=sender,request_id=request_id,active_workflow_id=gate.get('workflow_id'))
        wf_mark(k)
        return True
    tid=f'wf-{int(time.time())}-{hashlib.sha256((DID+goal+request_id).encode()).hexdigest()[:10]}'
    wf_send(AIZONG_DID,'WORKFLOW_TASK',tid,goal=goal,
            scout_did=LOVE8_DID,builder_did=AIZONG_DID,reviewer_did=AI2AI_DID,
            origin='ai2ai-scheduler',scheduler_request_id=request_id)
    scheduler_gate_save({'workflow_id':tid,'request_id':request_id,'started_at':time.time()})
    ledger('workflow_started',workflow_id=tid,peer_did=AIZONG_DID,origin='ai2ai-scheduler',
           scheduler_request_id=request_id,goal_sha256=hashlib.sha256(goal.encode()).hexdigest())
    wf_mark(k)
    return True
# AUTONOMOUS_SCHEDULER_GATE_V29_END

'''
s = s[:insert_at] + block + s[insert_at:]

needle = "    if not x or not trusted(sender): return\n    if workflow_handle(sender,x): return\n"
replacement = "    if not x or not trusted(sender): return\n    if scheduler_request_handle(sender,x): return\n    if workflow_handle(sender,x): return\n"
if needle not in s:
    raise SystemExit("workflow dispatch marker missing; no changes made")
s = s.replace(needle, replacement, 1)

complete_needle = "        wf_send(AI2AI_DID,'COMPLETE',tid,status='complete',final_summary=summary)\n"
if complete_needle not in s:
    raise SystemExit("workflow completion marker missing; no changes made")
s = s.replace(complete_needle, complete_needle + "        scheduler_gate_clear()\n", 1)

p.write_text(s)
print("patched:", p)
PY

  "$root/venv/bin/python" -m py_compile "$agent"
  cat > /usr/local/bin/tc-collab-autonomous-rollback <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$root"
BACKUP="$backup"
AGENT="$agent"
UNIT="$unit"

if [ -f "\$BACKUP/root-code-config-state.tgz" ]; then
  tar -C "\$ROOT" -xzf "\$BACKUP/root-code-config-state.tgz" .env bin/collab.py
fi
if [ -f "\$BACKUP/service.unit" ]; then
  cp -a "\$BACKUP/service.unit" "\$UNIT"
fi
rm -f "\$ROOT/state/scheduler_gate.json"
PID1="\$(tr -d '\\0' </proc/1/comm 2>/dev/null || true)"
if [ "\$PID1" = "systemd" ]; then
  systemctl daemon-reload
  systemctl restart technocore-collab
elif command -v tc-collab-stop >/dev/null 2>&1 && command -v tc-collab-start >/dev/null 2>&1; then
  tc-collab-stop || true
  tc-collab-start
else
  echo "Love8 文件已回退；请手动启动 collab runner"
fi
echo "Love8 autonomous scheduler gate rolled back"
echo "Backup: \$BACKUP"
EOF
  chmod 0700 /usr/local/bin/tc-collab-autonomous-rollback

  pid1="$(tr -d '\0' </proc/1/comm 2>/dev/null || true)"
  if [ "$pid1" = "systemd" ]; then
    systemctl daemon-reload
    systemctl restart technocore-collab
  elif command -v tc-collab-stop >/dev/null 2>&1 && command -v tc-collab-start >/dev/null 2>&1; then
    tc-collab-stop || true
    tc-collab-start
  else
    die "Love8 没有可用的 systemd 或 collab runner；文件已修改但未重启"
  fi
  sleep 3
  echo "=== LOVE8 SCHEDULER GATE v2.9 READY ==="
  "$root/venv/bin/python" "$agent" status
  if command -v tc-collab-process-status >/dev/null 2>&1; then
    tc-collab-process-status
  fi
  echo "backup=$backup"
  echo "rollback=tc-collab-autonomous-rollback"
}

ai2ai_env="/opt/technocore-a2a/.env"
if [ -f "$ai2ai_env" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ai2ai_env"
  set +a
  if [ "$AGENT_NAME" = "ai2ai" ]; then
    install_ai2ai
    exit 0
  fi
fi

love8_env="/opt/technocore-collab/.env"
if [ -f "$love8_env" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$love8_env"
  set +a
  if [ "$AGENT_NAME" = "love8" ]; then
    install_love8
    exit 0
  fi
fi

die "未识别为 AI2AI 或 Love8；Aizong 不执行此 v2.9 安装器"
