#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/technocore-a2a"
PEERS="$ROOT/state/peers.json"
AIZONG_DID='did:key:z6MktU13Pf4jVf6Ck5D3pwNYX2PVUAfNC61ytciyb4Coyh7e'
FALLBACK_ROOM='d-aizong'
STAMP="$(date -u +%Y%m%d-%H%M%S)"

[[ ${EUID} -eq 0 ]] || { echo 'Run as root'; exit 1; }
[[ -f "$PEERS" ]] || { echo "Missing $PEERS"; exit 1; }

python3 - "$FALLBACK_ROOM" <<'PY'
import json, sys, urllib.request
room=sys.argv[1]
url='https://technocore.chat/r/'+room+'?format=json&limit=1'
try:
    with urllib.request.urlopen(url, timeout=20) as r:
        if r.status != 200: raise SystemExit(f'fallback preflight HTTP {r.status}')
        json.loads(r.read().decode())
except Exception as e:
    raise SystemExit('Fallback room preflight failed: '+str(e))
print('fallback_room_readable:', room)
PY

cp -a "$PEERS" "$PEERS.before-v1.8-$STAMP"
python3 - "$PEERS" <<'PY'
import json, sys
from pathlib import Path
p=Path(sys.argv[1]); d=json.loads(p.read_text())
d['did:key:z6MktU13Pf4jVf6Ck5D3pwNYX2PVUAfNC61ytciyb4Coyh7e']='d-aizong'
t=p.with_suffix('.tmp'); t.write_text(json.dumps(d,separators=(',',':'))); t.replace(p)
PY
chown tcagent:tcagent "$PEERS"
chmod 0660 "$PEERS"

systemctl restart technocore-a2a
sleep 2

echo '=== AI2AI ROUTE UPDATED ==='
tc-a2a-status
systemctl is-active technocore-a2a
echo 'aizong_route: d-aizong'
echo 'No DID/private key/mailbox identity was changed.'
