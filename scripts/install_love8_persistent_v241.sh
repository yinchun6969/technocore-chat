#!/usr/bin/env bash
set -Eeuo pipefail
RAW="${REPO_RAW:-https://raw.githubusercontent.com/yinchun6969/technocore-chat/love8-social-v2}"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
curl -fsSL "$RAW/scripts/upgrade_love8_persistent_v241.sh" -o "$TMP"
# Patch two installer details before execution:
# 1) keep the generated DID helper quote stripping portable;
# 2) do not create an unclaimed d- room for provenance. Official Technocore
#    refuses ownership claims after a d- room already has messages, so use an
#    ordinary public signed witness room until an owned-room claim flow exists.
python3 - "$TMP" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1])
lines=p.read_text(encoding='utf-8').splitlines()
out=[]
for line in lines:
    if "if line.startswith('DID='):" in line:
        out.append(" if line.startswith('DID='): did=line.split('=',1)[1].strip().strip(chr(34)+chr(39)); break")
    elif "'PERSIST_ANCHOR_ROOM':'d-love8'" in line:
        out.append(line.replace("'PERSIST_ANCHOR_ROOM':'d-love8'", "'PERSIST_ANCHOR_ROOM':'love8-provenance'"))
    else:
        out.append(line)
p.write_text('\n'.join(out)+'\n',encoding='utf-8')
PY
bash "$TMP"
