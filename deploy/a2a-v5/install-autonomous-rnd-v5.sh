#!/usr/bin/env bash
set -Eeuo pipefail

# Autonomous R&D v5 installer.
# The existing identity, mailbox, peer map, cursor and provenance are never
# replaced.  v5 adds independent services and a signed Love8 request gate.

VERSION="5.4.0"
REPO_RAW="https://raw.githubusercontent.com/yinchun6969/technocore-chat"
# Release tooling replaces this marker with an immutable reviewed commit.
V5_REF="7f159d8c5129a30e801d8f8c121d4b369f1ee702"
V5_RAW="$REPO_RAW/$V5_REF/deploy/a2a-v5"
# This is the already-reviewed scheduler-gate patch.  Pinning a commit keeps
# a later branch move from silently changing the gate used by this installer.
GATE_RAW="$REPO_RAW/60dc38edfad959adf24cf970477282a202138a8a/deploy/a2a-v3/install-autonomous-scheduler-v2.9.sh"
AI_ROOT="/opt/technocore-a2a"
COLLAB_ROOT="/opt/technocore-collab"
BACKUP_ROOT="/root/tc-a2a-autonomous-rnd-v5-backups"

die() { echo "[x] $*" >&2; exit 1; }
need_root() { [[ ${EUID} -eq 0 ]] || die "Run as root"; }
is_systemd() { [[ "$(tr -d '\0' </proc/1/comm 2>/dev/null || true)" == "systemd" ]]; }

backup_path() {
  local node="$1"
  local stamp
  stamp="$(date -u +%Y%m%d-%H%M%S)"
  local out="$BACKUP_ROOT/$node/$stamp"
  install -d -m 0700 "$out"
  echo "$out"
}

write_manifest() {
  local out="$1"; shift
  {
    echo "version=$VERSION"
    echo "node=$1"
    echo "host=$(hostname)"
    echo "utc=$(date -u -Is)"
    echo "rollback_policy=restore-added-code-and-units; preserve-existing-agent-state"
    echo "preserved=identity,private-key,mailbox,room,peers,cursor,provenance"
  } >"$out/MANIFEST"
  chmod 0600 "$out/MANIFEST"
}

backup_ai2ai() {
  local out="$1"
  tar -C / -czf "$out/prechange.tgz" --ignore-failed-read \
    opt/technocore-a2a/.env \
    opt/technocore-a2a/bin/agent.py \
    opt/technocore-a2a/rnd-v5 \
    opt/technocore-a2a/rnd-v5-state \
    opt/technocore-a2a/rnd-v5-artifacts \
    etc/systemd/system/technocore-a2a-rnd-v5.service \
    etc/systemd/system/technocore-a2a-rnd-curator-v5.service \
    etc/systemd/system/technocore-a2a-scheduler.service \
    etc/systemd/system/technocore-a2a-curator.service \
    usr/local/bin/tc-a2a-rnd-v5-status \
    usr/local/bin/tc-a2a-rnd-v5-pause \
    usr/local/bin/tc-a2a-rnd-v5-resume \
    usr/local/bin/tc-a2a-rnd-v5-reset \
    usr/local/bin/tc-a2a-rnd-v5-artifacts \
    usr/local/bin/tc-a2a-rnd-v5-room \
    usr/local/bin/tc-a2a-rnd-v5-rollback
  sha256sum "$out/prechange.tgz" >"$out/SHA256SUMS"
  chmod 0600 "$out/prechange.tgz" "$out/SHA256SUMS"
}

backup_love8() {
  local out="$1"
  tar -C / -czf "$out/prechange.tgz" --ignore-failed-read \
    opt/technocore-collab/.env \
    opt/technocore-collab/bin/collab.py \
    etc/systemd/system/technocore-collab.service \
    usr/local/bin/tc-collab-rnd-v5-rollback \
    usr/local/bin/tc-collab-autonomous-rollback
  sha256sum "$out/prechange.tgz" >"$out/SHA256SUMS"
  chmod 0600 "$out/prechange.tgz" "$out/SHA256SUMS"
}

install_ai2ai() {
  local root="$AI_ROOT"
  local py="$root/venv/bin/python"
  local env="$root/.env"
  local stamp_dir
  local director="$root/rnd-v5/autonomous-rnd-v5.py"
  local curator="$root/rnd-v5/autonomous-curator-v5.py"
  local director_unit=/etc/systemd/system/technocore-a2a-rnd-v5.service
  local curator_unit=/etc/systemd/system/technocore-a2a-rnd-curator-v5.service

  [[ -f "$env" && -f "$root/bin/agent.py" ]] || die "Missing existing AI2AI runtime"
  [[ -x "$py" ]] || die "Missing AI2AI venv Python: $py"
  id tcagent >/dev/null 2>&1 || die "Missing tcagent user"
  is_systemd || die "AI2AI v5 requires systemd; existing Reviewer was not changed"
  grep -q 'WORKFLOW_V3_REVIEWER_BEGIN' "$root/bin/agent.py" || die "AI2AI workflow v3 Reviewer marker missing"
  grep -q 'A2A_WIRE_GUARD_V20' "$root/bin/agent.py" || die "AI2AI wire guard marker missing"

  # v5 services run as tcagent.  The pre-existing Reviewer runtime may have
  # been installed as root-only; grant tcagent read-only access without making
  # the runtime writable by the service account.
  chgrp tcagent "$root/bin/agent.py" || die "Cannot assign tcagent read group to agent.py"
  chmod 0640 "$root/bin/agent.py"
  # The legacy bin directory is root-only.  Grant tcagent traverse-only access;
  # it still cannot list or modify the directory or any other runtime file.
  chgrp tcagent "$root/bin" || die "Cannot assign tcagent traverse group to bin"
  chmod 0710 "$root/bin"

  stamp_dir="$(backup_path ai2ai)"
  backup_ai2ai "$stamp_dir"
  write_manifest "$stamp_dir" ai2ai

  local old_scheduler_active old_scheduler_enabled old_curator_active old_curator_enabled
  old_scheduler_active="$(systemctl is-active technocore-a2a-scheduler.service 2>/dev/null || true)"
  old_scheduler_enabled="$(systemctl is-enabled technocore-a2a-scheduler.service 2>/dev/null || true)"
  old_curator_active="$(systemctl is-active technocore-a2a-curator.service 2>/dev/null || true)"
  old_curator_enabled="$(systemctl is-enabled technocore-a2a-curator.service 2>/dev/null || true)"

  install -d -o tcagent -g tcagent -m 0750 "$root/rnd-v5" "$root/rnd-v5-state" "$root/rnd-v5-artifacts"
  local tmp_director tmp_curator
  tmp_director="$(mktemp)"
  tmp_curator="$(mktemp)"
  trap 'rm -f "$tmp_director" "$tmp_curator"' RETURN
  curl -fL --retry 5 --retry-delay 2 "$V5_RAW/autonomous-rnd-v5.py" -o "$tmp_director"
  curl -fL --retry 5 --retry-delay 2 "$V5_RAW/autonomous-curator-v5.py" -o "$tmp_curator"
  grep -q 'A2A_RND_DISCUSSION_V1' "$tmp_director" || die "dedicated research-room marker missing"
  "$py" -m py_compile "$tmp_director" "$tmp_curator"
  install -o root -g tcagent -m 0750 "$tmp_director" "$director"
  install -o root -g tcagent -m 0750 "$tmp_curator" "$curator"
  rm -f "$tmp_director" "$tmp_curator"
  trap - RETURN

  cat >"$director_unit" <<EOF
[Unit]
Description=Technocore autonomous R&D director v5
After=network-online.target technocore-a2a.service
Wants=network-online.target

[Service]
Type=simple
User=tcagent
Group=tcagent
EnvironmentFile=$env
Environment=RND_V5_TICK_SECONDS=90
Environment=RND_V5_START_DELAY_SECONDS=180
Environment=RND_V5_MIN_GAP_SECONDS=7200
Environment=RND_V5_MAX_DAILY=4
Environment=RND_V5_MAX_ACTIVE_SECONDS=5400
Environment=RND_V5_SOURCE_REPO=yinchun6969/technocore-chat
Environment=RND_V5_UPSTREAM_REPO=flop-labs/technocore-chat
Environment=RND_V5_SOURCE_LOOKBACK=8
Environment=RND_V5_DISCUSSION_ROOM=yinchun-a2a-rnd-v5
Environment=RND_V5_DISCUSSION_ENABLED=1
Environment=RND_V5_DISCUSSION_MAX_DAILY=8
ExecStart=$py $director run
Restart=always
RestartSec=20
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$root/state $root/identity $root/rnd-v5 $root/rnd-v5-state $root/rnd-v5-artifacts

[Install]
WantedBy=multi-user.target
EOF

  cat >"$curator_unit" <<EOF
[Unit]
Description=Technocore autonomous R&D evidence curator v5
After=network-online.target technocore-a2a.service technocore-a2a-rnd-v5.service
Wants=network-online.target

[Service]
Type=simple
User=tcagent
Group=tcagent
EnvironmentFile=$env
Environment=RND_V5_CURATOR_POLL_SECONDS=30
Environment=RND_V5_PUBLISH_RECEIPTS=1
ExecStart=$py $curator run
Restart=always
RestartSec=20
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$root/state $root/identity $root/rnd-v5 $root/rnd-v5-state $root/rnd-v5-artifacts

[Install]
WantedBy=multi-user.target
EOF

  cat > /usr/local/bin/tc-a2a-rnd-v5-status <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
PY="$py"
ROOT="$root"
set -a; source "$root/.env"; set +a
echo '=== AI2AI AUTONOMOUS R&D v5 ==='
"\$PY" "$director" status
echo
echo '=== CURATOR ==='
"\$PY" "$curator" status
echo
echo '=== SERVICES ==='
systemctl is-active technocore-a2a.service technocore-a2a-rnd-v5.service technocore-a2a-rnd-curator-v5.service || true
EOF
  cat > /usr/local/bin/tc-a2a-rnd-v5-pause <<EOF
#!/usr/bin/env bash
set -a; source "$root/.env"; set +a
exec "$py" "$director" pause
EOF
  cat > /usr/local/bin/tc-a2a-rnd-v5-resume <<EOF
#!/usr/bin/env bash
set -a; source "$root/.env"; set +a
exec "$py" "$director" resume
EOF
  cat > /usr/local/bin/tc-a2a-rnd-v5-reset <<EOF
#!/usr/bin/env bash
set -a; source "$root/.env"; set +a
exec "$py" "$director" reset-active
EOF
  cat > /usr/local/bin/tc-a2a-rnd-v5-artifacts <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
ls -lah "$root/rnd-v5-artifacts"
EOF
  cat > /usr/local/bin/tc-a2a-rnd-v5-room <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
set -a
source /opt/technocore-a2a/.env
set +a
ROOM="${RND_V5_DISCUSSION_ROOM:-yinchun-a2a-rnd-v5}"
BASE="${BASE:-https://technocore.chat}"
echo "room=$ROOM"
echo "url=$BASE/r/$ROOM"
exec curl -fsS --retry 3 --connect-timeout 10 --max-time 30   "$BASE/r/$ROOM?format=json&limit=80"
EOF
  chmod 0755 /usr/local/bin/tc-a2a-rnd-v5-{status,pause,resume,reset,artifacts,room}

  cat > /usr/local/bin/tc-a2a-rnd-v5-rollback <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
BACKUP="$stamp_dir"
ROOT="$root"
DIRECTOR_UNIT="$director_unit"
CURATOR_UNIT="$curator_unit"
OLD_SCHEDULER_ACTIVE="$old_scheduler_active"
OLD_SCHEDULER_ENABLED="$old_scheduler_enabled"
OLD_CURATOR_ACTIVE="$old_curator_active"
OLD_CURATOR_ENABLED="$old_curator_enabled"

systemctl disable --now technocore-a2a-rnd-v5.service technocore-a2a-rnd-curator-v5.service 2>/dev/null || true
rm -f "\$DIRECTOR_UNIT" "\$CURATOR_UNIT"
rm -rf "\$ROOT/rnd-v5"
  rm -f /usr/local/bin/tc-a2a-rnd-v5-room
if [ -f "\$BACKUP/prechange.tgz" ]; then
  tar -C / -xzf "\$BACKUP/prechange.tgz" \
    opt/technocore-a2a/rnd-v5 \
    etc/systemd/system/technocore-a2a-rnd-v5.service \
    etc/systemd/system/technocore-a2a-rnd-curator-v5.service \
    usr/local/bin/tc-a2a-rnd-v5-status \
    usr/local/bin/tc-a2a-rnd-v5-pause \
    usr/local/bin/tc-a2a-rnd-v5-resume \
    usr/local/bin/tc-a2a-rnd-v5-reset \
    usr/local/bin/tc-a2a-rnd-v5-artifacts \
    usr/local/bin/tc-a2a-rnd-v5-rollback 2>/dev/null || true
fi
systemctl daemon-reload
if [ "\$OLD_SCHEDULER_ENABLED" = enabled ]; then systemctl enable technocore-a2a-scheduler.service; else systemctl disable technocore-a2a-scheduler.service 2>/dev/null || true; fi
if [ "\$OLD_CURATOR_ENABLED" = enabled ]; then systemctl enable technocore-a2a-curator.service; else systemctl disable technocore-a2a-curator.service 2>/dev/null || true; fi
if [ "\$OLD_SCHEDULER_ACTIVE" = active ]; then systemctl start technocore-a2a-scheduler.service; else systemctl stop technocore-a2a-scheduler.service 2>/dev/null || true; fi
if [ "\$OLD_CURATOR_ACTIVE" = active ]; then systemctl start technocore-a2a-curator.service; else systemctl stop technocore-a2a-curator.service 2>/dev/null || true; fi
systemctl restart technocore-a2a.service
echo "AI2AI R&D v5 rolled back; live state/artifacts and existing identity/mailbox/cursor/provenance were preserved"
echo "backup=\$BACKUP"
EOF
  chmod 0700 /usr/local/bin/tc-a2a-rnd-v5-rollback

  systemctl disable --now technocore-a2a-scheduler.service technocore-a2a-curator.service 2>/dev/null || true
  systemctl daemon-reload
  # --now only starts an inactive unit; it does not reload an already-running
  # process after its Python files have been replaced.  Explicitly restart
  # both v5 units so an upgrade cannot leave the old director in memory.
  systemctl enable technocore-a2a-rnd-v5.service technocore-a2a-rnd-curator-v5.service
  systemctl restart technocore-a2a-rnd-v5.service technocore-a2a-rnd-curator-v5.service
  sleep 4
  systemctl is-active --quiet technocore-a2a.service || die "existing AI2AI Reviewer stopped; run tc-a2a-rnd-v5-rollback"
  systemctl is-active --quiet technocore-a2a-rnd-v5.service || die "v5 director failed; run tc-a2a-rnd-v5-rollback"
  systemctl is-active --quiet technocore-a2a-rnd-curator-v5.service || die "v5 curator failed; run tc-a2a-rnd-v5-rollback"
  echo "v5_services_restarted=1"
  echo "=== AI2AI AUTONOMOUS R&D v5 READY ==="
  tc-a2a-rnd-v5-status
  echo "backup=$stamp_dir"
  echo "rollback=tc-a2a-rnd-v5-rollback"
}

install_love8() {
  local root="$COLLAB_ROOT"
  local env="$root/.env"
  local runtime="$root/bin/collab.py"
  [[ -f "$env" && -f "$runtime" ]] || die "Missing existing Love8 collab runtime"
  grep -q 'WORKFLOW_V3_BEGIN' "$runtime" || die "Love8 workflow v3 marker missing"
  grep -q 'A2A_WIRE_GUARD_V33' "$runtime" || die "Love8 wire guard marker missing"
  set -a; source "$env"; set +a
  [[ "${AGENT_NAME:-}" == love8 && "${ROLE:-}" == scout ]] || die "This host is not Love8 Scout"

  local stamp_dir="$(backup_path love8)"
  backup_love8 "$stamp_dir"
  write_manifest "$stamp_dir" love8
  local gate_version
  if grep -q 'AUTONOMOUS_SCHEDULER_GATE_V30' "$runtime"; then
    # Progress-delivery v3 upgrades the signed v2.9 gate in place.  Do not run
    # the older patcher again: its exact dispatch needle intentionally does
    # not match a runtime that already dispatches scheduler requests.
    gate_version="v30-existing"
    echo "Love8 scheduler gate v3 already installed; legacy v2.9 patch skipped"
  else
    local tmp_gate="$(mktemp)"
    trap 'rm -f "$tmp_gate"' RETURN
    curl -fL --retry 5 --retry-delay 2 "$GATE_RAW" -o "$tmp_gate"
    bash -n "$tmp_gate"
    bash "$tmp_gate"
    rm -f "$tmp_gate"
    trap - RETURN
    gate_version="v29-installed"
  fi
  "$root/venv/bin/python" -m py_compile "$runtime"
  grep -Eq 'AUTONOMOUS_SCHEDULER_GATE_V(29|30)' "$runtime" || die "signed scheduler gate was not installed"
  grep -q 'def scheduler_request_handle' "$runtime" || die "scheduler request handler was not installed"
  grep -q 'if scheduler_request_handle(sender,x): return' "$runtime" || die "scheduler request dispatch was not installed"

  local old_unit_exists=0
  [[ -f /etc/systemd/system/technocore-collab.service ]] && old_unit_exists=1
  cat > /usr/local/bin/tc-collab-rnd-v5-rollback <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
BACKUP="$stamp_dir"
ROOT="$root"
OLD_UNIT_EXISTS="$old_unit_exists"

if command -v tc-collab-stop >/dev/null 2>&1; then tc-collab-stop || true; fi
if [ -f "\$BACKUP/prechange.tgz" ]; then
  tar -C / -xzf "\$BACKUP/prechange.tgz" opt/technocore-collab/.env opt/technocore-collab/bin/collab.py 2>/dev/null || true
  if [ "\$OLD_UNIT_EXISTS" = 1 ]; then
    tar -C / -xzf "\$BACKUP/prechange.tgz" etc/systemd/system/technocore-collab.service 2>/dev/null || true
  else
    rm -f /etc/systemd/system/technocore-collab.service
  fi
fi
rm -f "\$ROOT/state/scheduler_gate.json"
if [ "\$(tr -d '\0' </proc/1/comm 2>/dev/null || true)" = systemd ]; then
  systemctl daemon-reload
  systemctl restart technocore-collab
elif command -v tc-collab-start >/dev/null 2>&1; then
  tc-collab-start
fi
echo "Love8 R&D v5 scheduler gate rolled back; existing identity/mailbox/cursor/provenance were preserved"
echo "backup=\$BACKUP"
EOF
  chmod 0700 /usr/local/bin/tc-collab-rnd-v5-rollback
  if command -v tc-collab-process-status >/dev/null 2>&1; then
    tc-collab-process-status || true
  fi
  echo "=== LOVE8 AUTONOMOUS R&D v5 GATE READY ==="
  echo "signed_scheduler_gate=$gate_version"
  echo "backup=$stamp_dir"
  echo "rollback=tc-collab-rnd-v5-rollback"
}

install_aizong() {
  local root="$COLLAB_ROOT"
  local env="$root/.env"
  local runtime="$root/bin/collab.py"
  [[ -f "$env" && -f "$runtime" ]] || die "Missing existing Aizong collab runtime"
  grep -q 'WORKFLOW_V3_BEGIN' "$runtime" || die "Aizong workflow v3 marker missing"
  grep -q 'A2A_WIRE_GUARD_V33' "$runtime" || die "Aizong wire guard marker missing"
  set -a; source "$env"; set +a
  [[ "${AGENT_NAME:-}" == aizong && "${ROLE:-}" == builder ]] || die "This host is not Aizong Builder"
  "$root/venv/bin/python" -m py_compile "$runtime"
  echo "=== AIZONG BUILDER v5 COMPATIBILITY VERIFIED ==="
  echo "builder_code=unchanged"
  echo "policy=receives signed research tasks; analyses and revisions remain read-only"
  echo "No new daemon is required on Aizong; the existing Builder is part of every v5 workflow."
}

need_root
command -v curl >/dev/null 2>&1 || die "curl is required"

if [[ -f "$AI_ROOT/.env" ]]; then
  set -a; source "$AI_ROOT/.env"; set +a
  [[ "${AGENT_NAME:-}" == ai2ai ]] && { install_ai2ai; exit 0; }
fi
if [[ -f "$COLLAB_ROOT/.env" ]]; then
  set -a; source "$COLLAB_ROOT/.env"; set +a
  case "${AGENT_NAME:-}" in
    love8) install_love8; exit 0 ;;
    aizong) install_aizong; exit 0 ;;
  esac
fi
die "Unknown existing node; no new identity or installation was created"
