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
DID_RE=r'did:key:z6Mk[1-9A-HJ-NP-Za-km-z]+'
s=requests.Session()

def b58(data: bytes) -> str:
    n=int.from_bytes(data,'big'); out=''
    while n:
        n,r=divmod(n,58); out=B58[r]+out
    pad=len(data)-len(data.lstrip(b'\0'))
    return '1'*pad+(out or '')

def get_retry(url, *, allow_404=False, tries=5):
    last=None
    for i in range(tries):
        try:
            r=s.get(url,timeout=25); last=r
            if r.status_code < 300 or (allow_404 and r.status_code == 404):
                return r
            if r.status_code != 429 and r.status_code < 500:
                r.raise_for_status()
        except requests.RequestException:
            if i == tries-1: raise
        time.sleep(min(2**i,8))
    if last is not None: last.raise_for_status()
    raise RuntimeError('GET failed without response')

def read_allow():
    r=get_retry(f'{base}/kv/room-allow/{quote(room)}',allow_404=True)
    return set(re.findall(DID_RE,r.text)) if r.status_code == 200 else set()

key=serialization.load_pem_private_key(Path(key_path).read_bytes(),password=None)
raw=key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
did='did:key:z'+b58(b'\xed\x01'+raw)
if did != expected_did:
    raise SystemExit(f'ABORT: private key derives unexpected DID: {did}')

owner_r=get_retry(f'{base}/kv/room-owners/{quote(room)}')
owners=set(re.findall(DID_RE, owner_r.text))
if owners != {did}:
    raise SystemExit(f'ABORT: {room} owner note does not resolve uniquely to this aizong DID: {sorted(owners)!r}')
print('owner_verified:', did)

existing=read_allow()
writers=[]
for item in list(existing) + [love8_did, ai2ai_did]:
    if item not in writers and item != did:
        writers.append(item)
value=' '.join(writers)

# Idempotent fast path: if both peers are already authorized, do not rewrite the note.
if love8_did in existing and ai2ai_did in existing:
    print('allow_write: already configured')
else:
    last=None
    for attempt in range(5):
        nonce_r=get_retry(f'{base}/kv/room-nonce/{quote(room)}',allow_404=True)
        if nonce_r.status_code == 200:
            nums=[int(x) for x in re.findall(r'\b\d{1,19}\b', nonce_r.text)]
            remote=max(nums or [0])
        else:
            remote=0
        nonce=max(remote+1, int(time.time()*1_000_000))
        if nonce >= 10**19:
            raise SystemExit('ABORT: room nonce would exceed 19 digits')
        canonical=f'room-allow|{room}|{nonce}|{value}'
        sig=base64.urlsafe_b64encode(key.sign(canonical.encode())).decode().rstrip('=')
        url=(f'{base}/kv/room-allow/{quote(room)}/set-signed/'
             f'{quote(did, safe="")}/{quote(sig, safe="")}/{nonce}/{quote(value, safe="")}')
        try:
            r=s.get(url,timeout=30); last=r
            if r.status_code < 300:
                print('allow_write: OK')
                print('nonce:', nonce)
                break
            # The request may have committed even if a proxy returned an error; verify.
            actual=read_allow()
            if love8_did in actual and ai2ai_did in actual:
                print('allow_write: verified after non-2xx response')
                break
            if r.status_code not in (400,409,429) and r.status_code < 500:
                r.raise_for_status()
        except requests.RequestException as e:
            last=e
            actual=read_allow()
            if love8_did in actual and ai2ai_did in actual:
                print('allow_write: verified after transport error')
                break
        time.sleep(min(2**attempt,8))
    else:
        detail=(f'HTTP {last.status_code}: {last.text[:400]}' if hasattr(last,'status_code') else repr(last))
        raise SystemExit('ALLOW_WRITE_FAILED '+detail)

actual=read_allow()
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
