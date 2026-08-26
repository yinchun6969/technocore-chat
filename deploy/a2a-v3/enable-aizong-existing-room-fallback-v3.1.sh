#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/technocore-collab"
ENV_FILE="$ROOT/.env"
AGENT="$ROOT/bin/collab.py"
PEERS="$ROOT/state/peers.json"
AIZONG_DID='did:key:z6MktU13Pf4jVf6Ck5D3pwNYX2PVUAfNC61ytciyb4Coyh7e'
FALLBACK_ROOM='d-aizong'
STAMP="$(date -u +%Y%m%d-%H%M%S)"

[[ ${EUID} -eq 0 ]] || { echo 'Run as root'; exit 1; }
[[ -f "$ENV_FILE" && -f "$AGENT" && -f "$PEERS" ]] || { echo 'Missing existing collab sidecar'; exit 1; }
set -a; source "$ENV_FILE"; set +a

# Preflight: the fallback must already exist. A read does not create a room.
python3 - "$FALLBACK_ROOM" <<'PY'
import json, sys, urllib.request
room=sys.argv[1]
url='https://technocore.chat/r/'+room+'?format=json&limit=1'
try:
    with urllib.request.urlopen(url, timeout=20) as r:
        if r.status != 200:
            raise SystemExit(f'fallback preflight HTTP {r.status}')
        json.loads(r.read().decode())
except Exception as e:
    raise SystemExit('Fallback room preflight failed: '+str(e))
print('fallback_room_readable:', room)
PY

cp -a "$PEERS" "$PEERS.before-v3.1-$STAMP"
python3 - "$PEERS" <<'PY'
import json, sys
from pathlib import Path
p=Path(sys.argv[1]); d=json.loads(p.read_text())
d['did:key:z6MktU13Pf4jVf6Ck5D3pwNYX2PVUAfNC61ytciyb4Coyh7e']='d-aizong'
t=p.with_suffix('.tmp'); t.write_text(json.dumps(d,separators=(',',':'))); t.replace(p)
PY
chmod 0600 "$PEERS"

if [[ "${AGENT_NAME:-}" == "love8" ]]; then
  echo '=== LOVE8 ROUTE UPDATED ==='
  tc-collab-status
  echo 'aizong_route: d-aizong'
  echo 'No identity/mailbox/private-key change.'
  exit 0
fi

[[ "${AGENT_NAME:-}" == "aizong" ]] || { echo "Refusing unexpected AGENT_NAME=${AGENT_NAME:-unknown}"; exit 1; }

# Stop the Builder listener while changing only its A2A receive transport.
if command -v systemctl >/dev/null 2>&1 && systemctl show-environment >/dev/null 2>&1; then
  systemctl stop technocore-collab 2>/dev/null || true
elif command -v tc-collab-stop >/dev/null 2>&1; then
  tc-collab-stop || true
fi

cp -a "$AGENT" "$AGENT.before-v3.1-$STAMP"
cp -a "$ENV_FILE" "$ENV_FILE.before-v3.1-$STAMP"
if grep -q '^A2A_FALLBACK_INBOX=' "$ENV_FILE"; then
  sed -i 's|^A2A_FALLBACK_INBOX=.*|A2A_FALLBACK_INBOX=d-aizong|' "$ENV_FILE"
else
  printf '\nA2A_FALLBACK_INBOX=d-aizong\n' >> "$ENV_FILE"
fi
chmod 0600 "$ENV_FILE"

python3 - "$AGENT" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); s=p.read_text()
if "A2A_FALLBACK_INBOX" not in s:
    anchor="POLL=int(os.environ.get('POLL_SECONDS','25'))\n"
    if anchor not in s: raise SystemExit('Could not locate POLL config; no patch applied')
    s=s.replace(anchor, anchor+"FALLBACK_INBOX=os.environ.get('A2A_FALLBACK_INBOX','').strip()\n",1)
old="def fetch_messages():\n    r=requests.get(f'{BASE}/r/{quote(MAILBOX)}',params={'format':'json','limit':200},timeout=30); r.raise_for_status(); return r.json().get('messages',[])"
new="def fetch_messages():\n    inbox=FALLBACK_INBOX or MAILBOX\n    r=requests.get(f'{BASE}/r/{quote(inbox)}',params={'format':'json','limit':200},timeout=30); r.raise_for_status(); return r.json().get('messages',[])"
if old not in s:
    if 'inbox=FALLBACK_INBOX or MAILBOX' not in s:
        raise SystemExit('Could not locate fetch_messages; no patch applied')
else:
    s=s.replace(old,new,1)
p.write_text(s)
print('patched:',p)
PY

"$ROOT/venv/bin/python" -m py_compile "$AGENT"

# Prime the Builder cursor to the current end of d-aizong so historical room
# traffic is not replayed as A2A work.
set -a; source "$ENV_FILE"; set +a
"$ROOT/venv/bin/python" - <<'PY'
import os, requests
from pathlib import Path
from urllib.parse import quote
base=os.environ['TECHNOCORE_BASE_URL'].rstrip('/')
inbox=os.environ.get('A2A_FALLBACK_INBOX','d-aizong')
r=requests.get(f'{base}/r/{quote(inbox)}',params={'format':'json','limit':200},timeout=30); r.raise_for_status()
def seq(m):
    try: return int(m.get('seq',0))
    except Exception: return 0
mx=max([seq(m) for m in r.json().get('messages',[])] or [0])
Path('/opt/technocore-collab/state/cursor.txt').write_text(str(mx))
print('fallback_cursor_primed:',mx)
PY

if command -v systemctl >/dev/null 2>&1 && systemctl show-environment >/dev/null 2>&1; then
  systemctl daemon-reload
  systemctl start technocore-collab
  sleep 2
  echo "service: $(systemctl is-active technocore-collab || true)"
else
  command -v tc-collab-start >/dev/null 2>&1 && tc-collab-start
  sleep 2
fi

echo '=== AIZONG FALLBACK READY ==='
tc-collab-status
echo 'identity_mailbox: unchanged'
echo 'workflow_receive_inbox: d-aizong'
echo 'No DID/private key/mailbox identity was replaced.'
