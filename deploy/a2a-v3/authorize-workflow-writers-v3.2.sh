#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/technocore-collab"
ENV_FILE="$ROOT/.env"
KEY="/opt/technocore-agent/identity/ed25519_private.pem"
PY="$ROOT/venv/bin/python"
ROOM="d-aizong"
EXPECTED_DID="did:key:z6MktU13Pf4jVf6Ck5D3pwNYX2PVUAfNC61ytciyb4Coyh7e"
LOVE8_DID="did:key:z6MkfGtYxQg6e2u7aLBJVzowxgtgTmYzzXo227W9AvVQwq3p"
AI2AI_DID="did:key:z6Mkrs9FviuKvQnAnexWfF1RWduNh6CqydrMAw8RUo73zoje"

[[ ${EUID} -eq 0 ]] || { echo "Run as root"; exit 1; }
[[ -f "$ENV_FILE" && -x "$PY" && -f "$KEY" ]] || {
  echo "ABORT: run this only on the existing aizong Builder VPS"
  exit 1
}

set -a
source "$ENV_FILE"
set +a
[[ "${AGENT_NAME:-}" == "aizong" && "${ROLE:-}" == "builder" ]] || {
  echo "ABORT: expected aizong/builder, got ${AGENT_NAME:-unknown}/${ROLE:-unknown}"
  exit 1
}

echo "=== AIZONG OWNED-ROOM AUTH v3.2 ==="
echo "room: $ROOM"
echo "owner identity: existing aizong DID only"
echo "writers to authorize: love8 + ai2ai"
echo "No DID/private key/mailbox is created or replaced."

"$PY" - "$ROOM" "$EXPECTED_DID" "$LOVE8_DID" "$AI2AI_DID" "$KEY" <<'PY'
import base64
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests
from cryptography.hazmat.primitives import serialization

room, expected_did, love8_did, ai2ai_did, key_path = sys.argv[1:]
base = 'https://technocore.chat'
B58='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'

def b58(data: bytes) -> str:
    n=int.from_bytes(data,'big'); out=''
    while n:
        n,r=divmod(n,58); out=B58[r]+out
    pad=len(data)-len(data.lstrip(b'\0'))
    return '1'*pad+(out or '')

def last_value(text: str) -> str:
    # Note reads may carry an untrusted-content banner. The persisted value is
    # the final non-empty line for these single-line notes.
    lines=[x.strip() for x in text.splitlines() if x.strip()]
    return lines[-1] if lines else ''

key=serialization.load_pem_private_key(Path(key_path).read_bytes(),password=None)
raw=key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
did='did:key:z'+b58(b'\xed\x01'+raw)
if did != expected_did:
    raise SystemExit(f'ABORT: private key derives unexpected DID: {did}')

owner_r=requests.get(f'{base}/kv/room-owners/{quote(room)}',timeout=20)
owner_r.raise_for_status()
owner=last_value(owner_r.text)
if owner != did:
    raise SystemExit(f'ABORT: {room} owner is not this aizong DID: {owner!r}')
print('owner_verified:', did)

# Preserve any owner-managed existing allow-list entries, then add the two
# workflow peers. Only syntactically valid did:key tokens are carried forward.
allow_r=requests.get(f'{base}/kv/room-allow/{quote(room)}',timeout=20)
existing=[]
if allow_r.status_code == 200:
    existing=re.findall(r'did:key:z6Mk[1-9A-HJ-NP-Za-km-z]+', allow_r.text)
elif allow_r.status_code not in (404,):
    allow_r.raise_for_status()

writers=[]
for item in existing + [love8_did, ai2ai_did]:
    if item not in writers and item != did:
        writers.append(item)
value=' '.join(writers)

nonce_r=requests.get(f'{base}/kv/room-nonce/{quote(room)}',timeout=20)
if nonce_r.status_code == 200:
    nums=[int(x) for x in re.findall(r'\b\d{1,19}\b', nonce_r.text)]
    remote=max(nums or [0])
elif nonce_r.status_code == 404:
    remote=0
else:
    nonce_r.raise_for_status()
nonce=max(remote+1, int(time.time()*1_000_000))
if nonce >= 10**19:
    raise SystemExit('ABORT: room nonce would exceed 19 digits')

canonical=f'room-allow|{room}|{nonce}|{value}'
sig=base64.urlsafe_b64encode(key.sign(canonical.encode())).decode().rstrip('=')
url=(f'{base}/kv/room-allow/{quote(room)}/set-signed/'
     f'{quote(did, safe="")}/{quote(sig, safe="")}/{nonce}/{quote(value, safe="")}')
r=requests.get(url,timeout=30)
if r.status_code >= 300:
    raise SystemExit(f'ALLOW_WRITE_FAILED HTTP {r.status_code}: {r.text[:500]}')
print('allow_write: OK')
print('nonce:', nonce)

verify=requests.get(f'{base}/kv/room-allow/{quote(room)}',timeout=20)
verify.raise_for_status()
actual=set(re.findall(r'did:key:z6Mk[1-9A-HJ-NP-Za-km-z]+', verify.text))
missing=[x for x in (love8_did, ai2ai_did) if x not in actual]
if missing:
    raise SystemExit('VERIFY_FAILED missing: '+','.join(missing))
print('authorized: love8')
print('authorized: ai2ai')
print('ROOM_ALLOW_OK')
PY

echo
echo "=== STATUS ==="
tc-collab-status || true
echo "workflow_receive_inbox: ${A2A_FALLBACK_INBOX:-not-set}"
echo "AIZONG_ROOM_AUTH_READY"
