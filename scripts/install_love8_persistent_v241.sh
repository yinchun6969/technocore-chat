#!/usr/bin/env bash
set -Eeuo pipefail
RAW="${REPO_RAW:-https://raw.githubusercontent.com/yinchun6969/technocore-chat/love8-social-v2}"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
curl -fsSL "$RAW/scripts/upgrade_love8_persistent_v241.sh" -o "$TMP"
# Correct the generated helper's quote-strip expression before execution.
python3 - "$TMP" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); s=p.read_text(encoding='utf-8')
bad="did=line.split('=',1)[1].strip().strip('\\\"\\\\\''); break"
good='did=line.split(\'=\',1)[1].strip().strip("\\\"\'"); break'
if bad in s:
    s=s.replace(bad,good)
p.write_text(s,encoding='utf-8')
PY
bash "$TMP"
