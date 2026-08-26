#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="/opt/technocore-a2a"
AGENT_PY="$ROOT_DIR/bin/agent.py"
ENV_FILE="$ROOT_DIR/.env"
SERVICE="technocore-a2a"

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root: sudo bash repair-auth-v1.2.sh"
  exit 1
fi

[[ -f "$AGENT_PY" ]] || { echo "Missing $AGENT_PY"; exit 1; }
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE"; exit 1; }

systemctl stop "$SERVICE" 2>/dev/null || true

python3 - <<'PY'
from pathlib import Path
p = Path('/opt/technocore-a2a/bin/agent.py')
s = p.read_text()
old = 'AI_HEADER: AI_PREFIX + AI_KEY'
new = 'AI_HEADER: ((AI_PREFIX.strip() + " ") if AI_PREFIX.strip() else "") + AI_KEY'
if old in s:
    s = s.replace(old, new)
elif new not in s:
    raise SystemExit('Could not find expected auth-header expression; refusing blind patch')
p.write_text(s)
PY

python3 -m py_compile "$AGENT_PY"

python3 - <<'PY'
from pathlib import Path
p = Path('/opt/technocore-a2a/.env')
vals = {}
for raw in p.read_text().splitlines():
    if not raw or raw.lstrip().startswith('#') or '=' not in raw:
        continue
    k, v = raw.split('=', 1)
    vals[k] = v
required = ['AGENT_NAME','AI_BASE_URL','AI_MODEL','AI_API_KEY','AI_KEY_HEADER','AI_KEY_PREFIX','A2A_TRUST_MODE']
missing = [k for k in required if not vals.get(k)]
if missing:
    raise SystemExit('Missing required config: ' + ', '.join(missing))
print('Config OK')
print('agent:', vals['AGENT_NAME'])
print('ai_endpoint:', vals['AI_BASE_URL'])
print('ai_model:', vals['AI_MODEL'])
print('auth:', vals['AI_KEY_HEADER'] + ': ' + vals['AI_KEY_PREFIX'] + ' <redacted>')
print('trust_mode:', vals['A2A_TRUST_MODE'])
PY

python3 - <<'PY'
import os, subprocess
from pathlib import Path
env = os.environ.copy()
for raw in Path('/opt/technocore-a2a/.env').read_text().splitlines():
    if not raw or raw.lstrip().startswith('#') or '=' not in raw:
        continue
    k, v = raw.split('=', 1)
    env[k] = v
subprocess.run([
    '/opt/technocore-a2a/venv/bin/python',
    '/opt/technocore-a2a/bin/agent.py',
    'init',
], env=env, check=True)
PY

systemctl daemon-reload
systemctl enable --now "$SERVICE"

echo
echo "=== SERVICE ==="
systemctl --no-pager --full status "$SERVICE" | sed -n '1,14p'
echo
echo "=== AGENT ==="
tc-a2a-status
