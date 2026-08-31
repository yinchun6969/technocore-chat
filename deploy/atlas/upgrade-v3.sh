#!/usr/bin/env bash
# Upgrade only an existing isolated Atlas deployment to the v3.9 pixel UI.
# Uses the A2A v5.5.2 evidence contract. Never restarts or changes A2A/TG.
set -Eeuo pipefail
umask 077
SOURCE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
fail() { echo "STOP: $*" >&2; exit 1; }
compile_files() {
  /usr/bin/python3 - "$@" <<'PY'
from pathlib import Path
import sys
for name in sys.argv[1:]:
    compile(Path(name).read_text(), name, 'exec')
PY
}
wait_for_dashboard() {
  local marker="$1" page
  for _attempt in $(seq 1 50); do
    if page="$(curl -fsS --max-time 2 http://127.0.0.1:8787/ 2>/dev/null)" && \
      grep -Fq "$marker" <<< "$page"; then
      return 0
    fi
    sleep 0.2
  done
  return 1
}
[[ $EUID -eq 0 ]] || fail 'Run with sudo on the AI2AI VPS.'
systemctl is-active --quiet technocore-a2a-rnd-v5.service || fail 'AI2AI v5 Director is not active.'
for target in /opt/technocore-atlas/tools /etc/technocore-atlas.conf /usr/local/bin/tc-atlas; do
  [[ -e "$target" && ! -L "$target" ]] || fail "Existing Atlas v2 target is absent or unsafe: $target"
done
grep -q '^ATLAS_WORKFLOW_ROOMS=' /etc/technocore-atlas.conf || fail 'Atlas v2 workflow configuration is absent.'
for source in tools/atlas_dashboard.py tools/atlas_observer.py tools/atlas_evidence_v552.py tools/technocore_atlas.py; do
  [[ -f "$SOURCE_ROOT/$source" && ! -L "$SOURCE_ROOT/$source" ]] || fail "Missing v3 source: $source"
done
[[ -f "$SOURCE_ROOT/deploy/atlas/tc-atlas" && ! -L "$SOURCE_ROOT/deploy/atlas/tc-atlas" ]] || fail 'Missing v3 Atlas CLI.'
grep -q 'TECHNOCORE // PIXEL QUEST' "$SOURCE_ROOT/tools/atlas_dashboard.py" || fail 'Source checkout is not Atlas v3.'
compile_files "$SOURCE_ROOT/tools/atlas_dashboard.py" "$SOURCE_ROOT/tools/atlas_observer.py" "$SOURCE_ROOT/tools/atlas_evidence_v552.py" "$SOURCE_ROOT/tools/technocore_atlas.py"
bash -n "$SOURCE_ROOT/deploy/atlas/tc-atlas"
if cmp -s "$SOURCE_ROOT/tools/atlas_dashboard.py" /opt/technocore-atlas/tools/atlas_dashboard.py && \
  cmp -s "$SOURCE_ROOT/tools/atlas_observer.py" /opt/technocore-atlas/tools/atlas_observer.py && \
  cmp -s "$SOURCE_ROOT/tools/atlas_evidence_v552.py" /opt/technocore-atlas/tools/atlas_evidence_v552.py && \
  cmp -s "$SOURCE_ROOT/tools/technocore_atlas.py" /opt/technocore-atlas/tools/technocore_atlas.py && \
  cmp -s "$SOURCE_ROOT/deploy/atlas/tc-atlas" /usr/local/bin/tc-atlas; then
  echo 'ATLAS_V3_CURRENT_RELEASE_ALREADY_INSTALLED'
  exit 0
fi
if grep -q 'TECHNOCORE // PIXEL QUEST' /opt/technocore-atlas/tools/atlas_dashboard.py; then
  PREVIOUS_RELEASE='Atlas v3'
  ROLLBACK_MARKER='TECHNOCORE // PIXEL QUEST'
  BACKUP_KIND='v3-to-v3.9'
elif grep -q 'Atlas v2 workflow dashboard' /opt/technocore-atlas/tools/atlas_dashboard.py; then
  PREVIOUS_RELEASE='Atlas v2'
  ROLLBACK_MARKER='TECHNOCORE // ATLAS v2'
  BACKUP_KIND='v2-to-v3'
else
  fail 'Existing dashboard is not an expected Atlas v2/v3 release.'
fi

BACKUP="/opt/technocore-atlas/backups/${BACKUP_KIND}-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP/tools" "$BACKUP/bin"
cp -a /opt/technocore-atlas/tools/atlas_dashboard.py "$BACKUP/tools/"
cp -a /opt/technocore-atlas/tools/atlas_observer.py "$BACKUP/tools/"
cp -a /opt/technocore-atlas/tools/technocore_atlas.py "$BACKUP/tools/"
if [[ -f /opt/technocore-atlas/tools/atlas_evidence_v552.py ]]; then
  cp -a /opt/technocore-atlas/tools/atlas_evidence_v552.py "$BACKUP/tools/"
else
  : > "$BACKUP/atlas_evidence_v552.absent"
fi
cp -a /usr/local/bin/tc-atlas "$BACKUP/bin/"

rollback() {
  local exit_code=$?
  trap - ERR
  set +e
  systemctl stop technocore-atlas-refresh.timer technocore-atlas-web.service technocore-atlas-refresh.service >/dev/null 2>&1 || true
  install -d -m 0755 /opt/technocore-atlas /opt/technocore-atlas/tools
  cp -a "$BACKUP/tools/." /opt/technocore-atlas/tools/
  [[ ! -f "$BACKUP/atlas_evidence_v552.absent" ]] || rm -f /opt/technocore-atlas/tools/atlas_evidence_v552.py
  cp -a "$BACKUP/bin/tc-atlas" /usr/local/bin/tc-atlas
  chmod 0755 /opt/technocore-atlas /opt/technocore-atlas/tools
  chmod 0644 /opt/technocore-atlas/tools/*.py
  chmod 0755 /usr/local/bin/tc-atlas
  systemctl enable --now technocore-atlas-web.service technocore-atlas-refresh.timer >/dev/null 2>&1 || true
  systemctl start --no-block technocore-atlas-refresh.service >/dev/null 2>&1 || true
  if wait_for_dashboard "$ROLLBACK_MARKER"; then
    echo "UPGRADE_FAILED: $PREVIOUS_RELEASE restored and listening from $BACKUP; A2A/TG untouched." >&2
  else
    echo "UPGRADE_FAILED: $PREVIOUS_RELEASE files restored from $BACKUP, but its web service needs inspection; A2A/TG untouched." >&2
  fi
  exit "$exit_code"
}
trap rollback ERR
systemctl stop technocore-atlas-refresh.timer technocore-atlas-web.service technocore-atlas-refresh.service
install -d -m 0755 /opt/technocore-atlas /opt/technocore-atlas/tools
install -m 0644 "$SOURCE_ROOT/tools/atlas_dashboard.py" "$SOURCE_ROOT/tools/atlas_observer.py" "$SOURCE_ROOT/tools/atlas_evidence_v552.py" "$SOURCE_ROOT/tools/technocore_atlas.py" /opt/technocore-atlas/tools/
install -m 0755 "$SOURCE_ROOT/deploy/atlas/tc-atlas" /usr/local/bin/tc-atlas
chmod 0755 /opt/technocore-atlas /opt/technocore-atlas/tools
compile_files \
  /opt/technocore-atlas/tools/atlas_dashboard.py \
  /opt/technocore-atlas/tools/atlas_observer.py \
  /opt/technocore-atlas/tools/atlas_evidence_v552.py \
  /opt/technocore-atlas/tools/technocore_atlas.py
(
  cd /opt/technocore-atlas
  PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -c 'import tools.atlas_observer'
)
systemctl enable --now technocore-atlas-web.service technocore-atlas-refresh.timer
systemctl start --no-block technocore-atlas-refresh.service
systemctl is-active --quiet technocore-atlas-web.service
systemctl is-active --quiet technocore-atlas-refresh.timer
wait_for_dashboard 'TECHNOCORE // PIXEL QUEST'
trap - ERR
echo 'ATLAS_V3_9_UPGRADED: original audio-synced relay dashboard=127.0.0.1:8787; A2A-v5.5.2 evidence/receipt compatible; live polling=10s; collection=30s'
echo "backup=$BACKUP; snapshot schema=v3; A2A/TG not restarted"
