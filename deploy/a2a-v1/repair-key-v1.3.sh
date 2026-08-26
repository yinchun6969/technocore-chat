#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="/opt/technocore-a2a"
ENV_FILE="$ROOT_DIR/.env"
AGENT_PY="$ROOT_DIR/bin/agent.py"
SERVICE="technocore-a2a"

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root: sudo bash repair-key-v1.3.sh"
  exit 1
fi

[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE"; exit 1; }
[[ -f "$AGENT_PY" ]] || { echo "Missing $AGENT_PY"; exit 1; }

read_env() {
  local key="$1"
  python3 - "$ENV_FILE" "$key" <<'PY'
import sys
from pathlib import Path
path, key = sys.argv[1], sys.argv[2]
for raw in Path(path).read_text().splitlines():
    if raw.startswith(key + '='):
        print(raw.split('=', 1)[1])
        raise SystemExit(0)
raise SystemExit(1)
PY
}

AI_BASE_URL="$(read_env AI_BASE_URL)"
AI_MODEL="$(read_env AI_MODEL)"
AI_KEY_HEADER="$(read_env AI_KEY_HEADER || true)"
AI_KEY_PREFIX="$(read_env AI_KEY_PREFIX || true)"
AI_KEY_HEADER="${AI_KEY_HEADER:-Authorization}"
AI_KEY_PREFIX="${AI_KEY_PREFIX:-Bearer}"

if [[ -z "$AI_BASE_URL" || -z "$AI_MODEL" ]]; then
  echo "AI_BASE_URL or AI_MODEL is empty; refusing to continue."
  exit 1
fi

if [[ -r /dev/tty ]]; then
  read -rsp "Re-enter the API key that returned HTTP 200 in your manual curl test: " NEW_AI_KEY </dev/tty
  echo >/dev/tty
else
  echo "No interactive TTY available." >&2
  exit 1
fi

[[ -n "$NEW_AI_KEY" ]] || { echo "API key cannot be empty"; exit 1; }
export NEW_AI_KEY AI_BASE_URL AI_MODEL AI_KEY_HEADER AI_KEY_PREFIX

# Validate the exact key/model pair before touching the saved config.
"$ROOT_DIR/venv/bin/python" - <<'PY'
import os, sys, requests
base = os.environ['AI_BASE_URL'].rstrip('/')
endpoint = base if base.endswith('/chat/completions') else base + '/chat/completions'
model = os.environ['AI_MODEL']
key = os.environ['NEW_AI_KEY']
header = os.environ.get('AI_KEY_HEADER', 'Authorization') or 'Authorization'
prefix = (os.environ.get('AI_KEY_PREFIX', 'Bearer') or '').strip()
auth = ((prefix + ' ') if prefix else '') + key
r = requests.post(
    endpoint,
    headers={'Content-Type':'application/json', header: auth},
    json={
        'model': model,
        'messages': [{'role':'user','content':'Reply only: OK'}],
        'max_tokens': 20,
    },
    timeout=60,
)
print('API validation status:', r.status_code)
if r.status_code >= 300:
    print('API validation body:', r.text[:500])
    sys.exit(1)
print('API key/model validation: OK')
PY

# Save the validated key without printing it.
python3 - <<'PY'
import os
from pathlib import Path
p = Path('/opt/technocore-a2a/.env')
key = os.environ['NEW_AI_KEY']
lines = p.read_text().splitlines()
out=[]
seen=False
for line in lines:
    if line.startswith('AI_API_KEY='):
        out.append('AI_API_KEY=' + key)
        seen=True
    else:
        out.append(line)
if not seen:
    out.append('AI_API_KEY=' + key)
p.write_text('\n'.join(out) + '\n')
PY
chown root:tcagent "$ENV_FILE"
chmod 0640 "$ENV_FILE"
unset NEW_AI_KEY

# Ensure the installed agent inserts exactly one separator between scheme and key.
python3 - <<'PY'
from pathlib import Path
p = Path('/opt/technocore-a2a/bin/agent.py')
s = p.read_text()
old = 'AI_HEADER: AI_PREFIX + AI_KEY'
new = 'AI_HEADER: ((AI_PREFIX.strip() + " ") if AI_PREFIX.strip() else "") + AI_KEY'
if old in s:
    s = s.replace(old, new)
elif new not in s:
    raise SystemExit('Could not locate expected auth header expression')
p.write_text(s)
PY
python3 -m py_compile "$AGENT_PY"

systemctl stop "$SERVICE" 2>/dev/null || true

# Load the now-validated config and complete initialization using the existing DID/key.
"$ROOT_DIR/venv/bin/python" - <<'PY'
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
echo "Repair v1.3 complete. Existing DID/private key were preserved."
echo "=== AGENT STATUS ==="
tc-a2a-status
