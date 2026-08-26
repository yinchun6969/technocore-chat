#!/usr/bin/env bash
set -Eeuo pipefail
RAW="${REPO_RAW:-https://raw.githubusercontent.com/yinchun6969/technocore-chat/love8-social-v2}"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
curl -fsSL "$RAW/scripts/upgrade_love8_persistent_v241.sh" -o "$TMP"
# Correct one generated helper line in the upgrade payload before execution.
python3 - "$TMP" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1])
lines=p.read_text(encoding='utf-8').splitlines()
out=[]
for line in lines:
    if "if line.startswith('DID='):" in line:
        out.append(" if line.startswith('DID='): did=line.split('=',1)[1].strip().strip(chr(34)+chr(39)); break")
    else:
        out.append(line)
p.write_text('\n'.join(out)+'\n',encoding='utf-8')
PY
bash "$TMP"
