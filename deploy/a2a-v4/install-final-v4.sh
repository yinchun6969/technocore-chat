#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="4.0-final"
PINNED_COLLAB="60dc38edfad959adf24cf970477282a202138a8a"
PINNED_CURATOR="219f26732e6d3ad6afb84f33ff21e2ea075ffa85"
REPO_RAW="https://raw.githubusercontent.com/yinchun6969/technocore-chat"

fail(){ echo "[x] $*" >&2; exit 1; }
run_remote(){ local url="$1"; local out="$2"; curl -fL --retry 5 --retry-delay 2 "$url" -o "$out"; bash "$out"; }

[[ ${EUID} -eq 0 ]] || fail "Run as root"
command -v curl >/dev/null 2>&1 || fail "curl is required"

install_ai2ai(){
  local root=/opt/technocore-a2a
  local env="$root/.env"
  local runtime="$root/bin/agent.py"
  local curator="$root/bin/artifact_curator_v4.py"
  local unit=/etc/systemd/system/technocore-a2a-curator.service
  local stamp="$(date -u +%Y%m%d-%H%M%S)"

  [[ -f "$env" && -f "$runtime" ]] || fail "Missing existing ai2ai runtime"
  id tcagent >/dev/null 2>&1 || fail "Missing tcagent user"
  grep -q 'WORKFLOW_V3_REVIEWER_BEGIN' "$runtime" || fail "Install Workflow v3 Reviewer first"
  grep -q 'A2A_WIRE_GUARD_V20' "$runtime" || fail "Install ai2ai envelope guard/recovery v2.0 first"
  [[ "$(tr -d '\0' </proc/1/comm 2>/dev/null || true)" == systemd ]] || fail "ai2ai final v4 requires systemd"

  install -d -m 0700 /root/tc-a2a-final-v4-backups
  tar -C "$root" -czf "/root/tc-a2a-final-v4-backups/ai2ai-$stamp.tgz" .env bin state 2>/dev/null || true

  echo "[1/4] Installing guarded autonomous research scheduler..."
  run_remote \
    "$REPO_RAW/$PINNED_COLLAB/deploy/a2a-v3/install-autonomous-scheduler-v2.9.sh" \
    /tmp/tc-autonomous-v29.sh

  echo "[2/4] Applying low-noise final policy: 8h interval, max 2 cycles/day..."
  install -d /etc/systemd/system/technocore-a2a-scheduler.service.d
  cat >/etc/systemd/system/technocore-a2a-scheduler.service.d/40-rnd-v4.conf <<'EOF'
[Service]
Environment=RND_FINAL_POLICY=1
Environment=SCHEDULER_INTERVAL_SECONDS=28800
Environment=SCHEDULER_MAX_DAILY=2
Environment=SCHEDULER_MAX_ACTIVE_SECONDS=21600
Environment=SCHEDULER_TICK_SECONDS=90
Environment=SCHEDULER_START_DELAY_SECONDS=300
EOF

  echo "[3/4] Installing evidence-backed artifact curator..."
  curl -fL --retry 5 --retry-delay 2 \
    "$REPO_RAW/$PINNED_CURATOR/deploy/a2a-v4/artifact-curator-v4.py" \
    -o /tmp/artifact-curator-v4.py
  "$root/venv/bin/python" -m py_compile /tmp/artifact-curator-v4.py
  install -o root -g tcagent -m 0750 /tmp/artifact-curator-v4.py "$curator"
  install -d -o tcagent -g tcagent -m 2770 "$root/artifacts" "$root/state"
  chown -R tcagent:tcagent "$root/artifacts" "$root/state"

  cat >"$unit" <<EOF
[Unit]
Description=Technocore autonomous R&D artifact curator v4
After=network-online.target technocore-a2a.service technocore-a2a-scheduler.service
Wants=network-online.target

[Service]
Type=simple
User=tcagent
Group=tcagent
EnvironmentFile=$env
Environment=CURATOR_POLL_SECONDS=120
Environment=CURATOR_PUBLISH_RECEIPTS=1
ExecStart=$root/venv/bin/python $curator run
Restart=always
RestartSec=20
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$root/state $root/artifacts $root/identity

[Install]
WantedBy=multi-user.target
EOF

  cat >/usr/local/bin/tc-a2a-rnd-status <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
set -a; source "$env"; set +a
echo '=== RESEARCH SCHEDULER ==='
"$root/venv/bin/python" "$root/bin/autonomous_scheduler.py" status
echo
echo '=== ARTIFACT CURATOR ==='
"$root/venv/bin/python" "$curator" status
echo
echo '=== SERVICES ==='
systemctl is-active technocore-a2a technocore-a2a-scheduler technocore-a2a-curator || true
EOF
  cat >/usr/local/bin/tc-a2a-rnd-pause <<'EOF'
#!/usr/bin/env bash
exec tc-a2a-scheduler-pause
EOF
  cat >/usr/local/bin/tc-a2a-rnd-resume <<'EOF'
#!/usr/bin/env bash
exec tc-a2a-scheduler-resume
EOF
  cat >/usr/local/bin/tc-a2a-rnd-artifacts <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
ls -lah "$root/artifacts"
EOF
  chmod 0755 /usr/local/bin/tc-a2a-rnd-{status,pause,resume,artifacts}

  echo "[4/4] Starting final autonomous R&D services..."
  systemctl daemon-reload
  systemctl restart technocore-a2a-scheduler.service
  systemctl enable --now technocore-a2a-curator.service
  sleep 4
  systemctl is-active --quiet technocore-a2a.service || fail "ai2ai reviewer is not active"
  systemctl is-active --quiet technocore-a2a-scheduler.service || fail "research scheduler is not active"
  systemctl is-active --quiet technocore-a2a-curator.service || fail "artifact curator is not active"

  echo "=== AI2AI AUTONOMOUS R&D v4 FINAL READY ==="
  tc-a2a-rnd-status
  echo "backup=/root/tc-a2a-final-v4-backups/ai2ai-$stamp.tgz"
}

install_love8(){
  local root=/opt/technocore-collab
  local env="$root/.env"
  local runtime="$root/bin/collab.py"
  [[ -f "$env" && -f "$runtime" ]] || fail "Missing Love8 collab runtime"
  set -a; source "$env"; set +a
  [[ "${AGENT_NAME:-}" == love8 && "${ROLE:-}" == scout ]] || fail "This host is not love8 Scout"
  grep -q 'WORKFLOW_V3_BEGIN' "$runtime" || fail "Install Workflow v3 first"
  grep -q 'A2A_WIRE_GUARD_V33' "$runtime" || fail "Install envelope guard v3.3 first"

  echo "[1/2] Installing autonomous scheduler gate on Love8..."
  run_remote \
    "$REPO_RAW/$PINNED_COLLAB/deploy/a2a-v3/install-autonomous-scheduler-v2.9.sh" \
    /tmp/tc-autonomous-v29.sh
  echo "[2/2] Installing endgame recovery helper..."
  run_remote \
    "$REPO_RAW/$PINNED_COLLAB/deploy/a2a-v3/install-workflow-endgame-recovery-v3.4.sh" \
    /tmp/tc-endgame-v34.sh

  echo "=== LOVE8 AUTONOMOUS R&D v4 FINAL READY ==="
  tc-collab-status
  command -v tc-collab-process-status >/dev/null 2>&1 && tc-collab-process-status || true
  echo "scheduler_gate: installed"
  echo "endgame_recovery: installed"
}

install_aizong(){
  local root=/opt/technocore-collab
  local env="$root/.env"
  local runtime="$root/bin/collab.py"
  [[ -f "$env" && -f "$runtime" ]] || fail "Missing Aizong collab runtime"
  set -a; source "$env"; set +a
  [[ "${AGENT_NAME:-}" == aizong && "${ROLE:-}" == builder ]] || fail "This host is not aizong Builder"
  grep -q 'WORKFLOW_V3_BEGIN' "$runtime" || fail "Install Workflow v3 first"
  grep -q 'A2A_WIRE_GUARD_V33' "$runtime" || fail "Install envelope guard v3.3 first"

  echo "Installing final endgame recovery helper..."
  run_remote \
    "$REPO_RAW/$PINNED_COLLAB/deploy/a2a-v3/install-workflow-endgame-recovery-v3.4.sh" \
    /tmp/tc-endgame-v34.sh

  echo "=== AIZONG AUTONOMOUS R&D v4 FINAL READY ==="
  tc-collab-status
  echo "builder_listener: active"
  echo "endgame_recovery: installed"
}

if [[ -f /opt/technocore-a2a/.env ]]; then
  set -a; source /opt/technocore-a2a/.env; set +a
  if [[ "${AGENT_NAME:-}" == ai2ai ]]; then install_ai2ai; exit 0; fi
fi

if [[ -f /opt/technocore-collab/.env ]]; then
  set -a; source /opt/technocore-collab/.env; set +a
  case "${AGENT_NAME:-}" in
    love8) install_love8; exit 0 ;;
    aizong) install_aizong; exit 0 ;;
  esac
fi

fail "Unknown host. Expected existing ai2ai, love8, or aizong installation."
