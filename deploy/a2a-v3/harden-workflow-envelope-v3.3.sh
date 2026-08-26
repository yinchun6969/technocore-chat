#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/technocore-collab"
AGENT="$ROOT/bin/collab.py"
STAMP="$(date -u +%Y%m%d-%H%M%S)"

[[ ${EUID} -eq 0 ]] || { echo 'Run as root'; exit 1; }
[[ -f "$ROOT/.env" && -f "$AGENT" ]] || { echo 'Missing existing collab sidecar'; exit 1; }
set -a; source "$ROOT/.env"; set +a
[[ "${AGENT_NAME:-}" == "love8" || "${AGENT_NAME:-}" == "aizong" ]] || { echo "Unexpected agent: ${AGENT_NAME:-unknown}"; exit 1; }

if command -v systemctl >/dev/null 2>&1 && systemctl show-environment >/dev/null 2>&1; then
  systemctl stop technocore-collab 2>/dev/null || true
elif command -v tc-collab-stop >/dev/null 2>&1; then
  tc-collab-stop || true
fi

cp -a "$AGENT" "$AGENT.before-v3.3-$STAMP"

python3 - "$AGENT" <<'PY'
from pathlib import Path
import sys

p=Path(sys.argv[1]); s=p.read_text()
if 'A2A_WIRE_GUARD_V33' in s:
    print('wire guard already installed')
    raise SystemExit(0)

start=s.find("def payload(kind,tid,**kw):\n")
end=s.find("\ndef parse(text):\n", start)
if start < 0 or end < 0:
    raise SystemExit('Could not locate payload() block; no changes made')

new=r'''# A2A_WIRE_GUARD_V33
MAX_A2A_WIRE_BYTES=3400

def payload(kind,tid,**kw):
    obj={'v':1,'type':kind,'task_id':tid,'from_did':DID,'reply_mailbox':MAILBOX,'role':ROLE,**kw}
    def enc(): return 'A2A1 '+json.dumps(obj,separators=(',',':'),ensure_ascii=True)
    text=enc()
    if len(text.encode('utf-8')) <= MAX_A2A_WIRE_BYTES:
        return text
    # Preserve the newest stage output as long as possible; compact older context first.
    orders={
      'BUILD_RESULT':['goal','build_result'],
      'CHALLENGE':['build_result','goal','challenge'],
      'REVISED_RESULT':['goal','challenge','revised_result'],
      'COMPLETE':['final_summary'],
      'RESULT':['result'],
      'WORKFLOW_TASK':['goal'],
      'TASK':['goal'],
    }
    mins={'goal':320,'build_result':520,'challenge':520,'revised_result':700,'final_summary':500,'result':700}
    for key in orders.get(kind, list(kw.keys())):
        while len(enc().encode('utf-8')) > MAX_A2A_WIRE_BYTES and isinstance(obj.get(key),str) and len(obj[key]) > mins.get(key,160):
            over=len(enc().encode('utf-8'))-MAX_A2A_WIRE_BYTES
            cut=max(96,over+96)
            keep=max(mins.get(key,160),len(obj[key])-cut)
            obj[key]=obj[key][:keep]
    text=enc()
    if len(text.encode('utf-8')) > MAX_A2A_WIRE_BYTES:
        raise ValueError(f'A2A payload too large after compaction: {len(text.encode("utf-8"))} bytes')
    return text
'''
s=s[:start]+new+s[end:]

old="    text=' '.join(str(text).splitlines()).strip()[:4000]\n"
newpost="    text=' '.join(str(text).splitlines()).strip()\n    if len(text.encode('utf-8')) > 3900:\n        raise ValueError(f'refusing to truncate signed A2A payload: {len(text.encode(\"utf-8\"))} bytes')\n"
if old not in s:
    raise SystemExit('Could not locate post() truncation; no changes written')
s=s.replace(old,newpost,1)

p.write_text(s)
print('patched:',p)
PY

"$ROOT/venv/bin/python" -m py_compile "$AGENT"
chmod 0700 "$AGENT"

if command -v systemctl >/dev/null 2>&1 && systemctl show-environment >/dev/null 2>&1; then
  systemctl daemon-reload
  systemctl start technocore-collab
  sleep 2
  echo "service: $(systemctl is-active technocore-collab || true)"
else
  command -v tc-collab-start >/dev/null 2>&1 && tc-collab-start
  sleep 2
  command -v tc-collab-process-status >/dev/null 2>&1 && tc-collab-process-status || true
fi

echo '=== WORKFLOW ENVELOPE v3.3 ==='
tc-collab-status || true
echo 'wire_limit_bytes: 3400'
echo 'raw_truncation: disabled'
echo 'A2A_ENVELOPE_GUARD_OK'
echo 'DID/private key/mailbox/peer configuration unchanged.'
