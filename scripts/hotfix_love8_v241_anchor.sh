#!/usr/bin/env bash
set -Eeuo pipefail
CFG=/opt/love8-agent/social/persistent.env
STATE=/opt/love8-agent/memory/state.json
[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo '[x] 请用 root 执行' >&2; exit 1; }
[[ -s "$CFG" ]] || { echo '[x] missing persistent.env' >&2; exit 1; }

# A d- room must be claimed as it is created. Posting first would make a later
# ownership claim invalid under the official Technocore contract. Until Love8
# has a full signed owner-claim flow, provenance anchors use an ordinary public
# room; the message itself is still DID-signed and the local ledger is canonical.
python3 - "$CFG" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1])
lines=p.read_text(encoding='utf-8').splitlines()
out=[]; seen=False
for line in lines:
    if line.startswith('PERSIST_ANCHOR_ROOM='):
        out.append('PERSIST_ANCHOR_ROOM=love8-provenance'); seen=True
    else:
        out.append(line)
if not seen: out.append('PERSIST_ANCHOR_ROOM=love8-provenance')
p.write_text('\n'.join(out)+'\n',encoding='utf-8')
p.chmod(0o600)
PY

echo '===== LOVE8 v2.4.1 ANCHOR HOTFIX ====='
grep '^PERSIST_ANCHOR_ROOM=' "$CFG"
if [[ -s "$STATE" ]]; then
  python3 - "$STATE" <<'PY'
import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: d={}
print('last_anchor_date:', d.get('last_anchor_date','-'))
print('last_anchor_room:', d.get('last_anchor_room','-'))
print('last_anchor_error:', d.get('last_anchor_error','-'))
PY
fi
echo 'OK: future daily provenance anchors will use signed public room love8-provenance.'
