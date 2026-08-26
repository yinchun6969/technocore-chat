#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/technocore-collab"
ENV_FILE="$ROOT/.env"
PEERS="$ROOT/state/peers.json"

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root"
  exit 1
fi

[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE"; exit 1; }
set -a
source "$ENV_FILE"
set +a

LOVE8_DID='did:key:z6MkfGtYxQg6e2u7aLBJVzowxgtgTmYzzXo227W9AvVQwq3p'
LOVE8_MB='mb-p-610459b4e1262e4a95dce4ec'
AIZONG_DID='did:key:z6MktU13Pf4jVf6Ck5D3pwNYX2PVUAfNC61ytciyb4Coyh7e'
AIZONG_MB='mb-p-789b7b17ba0cb6998f6778ce'
AI2AI_DID='did:key:z6Mkrs9FviuKvQnAnexWfF1RWduNh6CqydrMAw8RUo73zoje'
AI2AI_MB='mb-p-611da800aa892112c88cd6da6e0fc065'

mkdir -p "$ROOT/state"
if [[ -f "$PEERS" ]]; then
  cp -a "$PEERS" "$PEERS.bak.$(date -u +%Y%m%dT%H%M%SZ)"
fi

case "${AGENT_NAME:-}" in
  love8)
    cat > "$PEERS.tmp" <<EOF
{"$AIZONG_DID":"$AIZONG_MB","$AI2AI_DID":"$AI2AI_MB"}
EOF
    ;;
  aizong)
    cat > "$PEERS.tmp" <<EOF
{"$LOVE8_DID":"$LOVE8_MB","$AI2AI_DID":"$AI2AI_MB"}
EOF
    ;;
  *)
    echo "Refusing: AGENT_NAME=${AGENT_NAME:-unknown}. This repair is only for love8 or aizong collab sidecars."
    exit 1
    ;;
esac

python3 -m json.tool "$PEERS.tmp" >/dev/null
mv "$PEERS.tmp" "$PEERS"
chmod 0600 "$PEERS"

echo "=== PEER MESH REPAIRED ==="
tc-collab-status

echo
echo "=== PEERS.JSON ==="
python3 -m json.tool "$PEERS"

echo
python3 - <<'PY'
import json, os
from pathlib import Path
p=Path('/opt/technocore-collab/state/peers.json')
d=json.loads(p.read_text())
agent=os.environ.get('AGENT_NAME','')
self_did={
'love8':'did:key:z6MkfGtYxQg6e2u7aLBJVzowxgtgTmYzzXo227W9AvVQwq3p',
'aizong':'did:key:z6MktU13Pf4jVf6Ck5D3pwNYX2PVUAfNC61ytciyb4Coyh7e',
}.get(agent)
assert len(d)==2, f'expected 2 peers, got {len(d)}'
assert self_did not in d, 'self DID is still present in peers'
print('PEER_MESH_OK')
PY
