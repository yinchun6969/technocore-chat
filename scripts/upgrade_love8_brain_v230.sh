#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="2.3.0"
ROOT="/opt/love8-agent"
SOCIAL="$ROOT/social"
STATE="$ROOT/state"
CFG="$SOCIAL/brain.env"
BRAIN="$SOCIAL/love8_brain.py"
RUNNER="$SOCIAL/love8_brain_runner.py"
LOG="/var/log/love8-brain-v22.log"

log(){ printf '\n[+] %s\n' "$*"; }
warn(){ printf '\n[!] %s\n' "$*"; }
die(){ printf '\n[x] %s\n' "$*" >&2; exit 1; }

[[ ${EUID:-$(id -u)} -eq 0 ]] || die "请用 root 执行"
[[ -s "$CFG" ]] || die "找不到 $CFG；请先完成 Love8 Brain v2.2.x 配置"
[[ -s "$BRAIN" ]] || die "找不到 $BRAIN"
[[ -s "$RUNNER" ]] || die "找不到 $RUNNER"

TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$SOCIAL/backups/v2.3-upgrade-$TS"
mkdir -p "$BACKUP"
cp -a "$BRAIN" "$CFG" "$RUNNER" "$STATE/brain-v22.json" "$BACKUP/" 2>/dev/null || true

log "升级 Brain Core 到 v$VERSION：扩大社交视野 + 2x 限额"
python3 - "$BRAIN" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1])
s=p.read_text(encoding='utf-8')

repls=[
('"""Love8 Brain v2.2.0: LLM decision layer above the v2.1.1 safety/quality guard."""',
 '"""Love8 Brain v2.3.0: long-context autonomous social brain above the v2.1.1 safety/quality guard."""'),
('VERSION = "2.2.0"','VERSION = "2.3.0"'),
('    rooms = guard.candidate_rooms(base, int(cfg.get("BRAIN_ROOMS", "8")))\n    candidates: list[dict[str, Any]] = []',
 '    rooms = guard.candidate_rooms(base, int(cfg.get("BRAIN_ROOMS", "12")))\n    room_message_limit = min(max(int(cfg.get("BRAIN_ROOM_MESSAGE_LIMIT", "48")), 24), 100)\n    candidate_limit = min(max(int(cfg.get("BRAIN_CANDIDATES", "16")), 6), 32)\n    digest_lines = min(max(int(cfg.get("BRAIN_DIGEST_LINES", "12")), 4), 24)\n    digest_chars = min(max(int(cfg.get("BRAIN_DIGEST_CHARS", "500")), 220), 1200)\n    candidate_chars = min(max(int(cfg.get("BRAIN_CANDIDATE_CHARS", "1200")), 700), 2400)\n    candidates: list[dict[str, Any]] = []'),
('            data = guard.http_json(f"{base}/r/{room}?format=json&limit=24")',
 '            data = guard.http_json(f"{base}/r/{room}?format=json&limit={room_message_limit}")'),
('            natural_lines.append(text[:220])','            natural_lines.append(text[:digest_chars])'),
('                "text": text[:700],','                "text": text[:candidate_chars],'),
('            digest[room] = natural_lines[-6:]','            digest[room] = natural_lines[-digest_lines:]'),
('    return candidates[:6], digest','    return candidates[:candidate_limit], digest'),
('    room_digest = {room: lines[-4:] for room, lines in list(digest.items())[:8]}',
 '    room_digest = {room: lines[-12:] for room, lines in list(digest.items())[:12]}'),
('    calls_per_hour = min(max(int(cfg.get("BRAIN_CALLS_PER_HOUR", "3")), 1), 12)',
 '    calls_per_hour = min(max(int(cfg.get("BRAIN_CALLS_PER_HOUR", "12")), 1), 24)'),
('    topics_per_day = min(max(int(cfg.get("BRAIN_TOPICS_PER_DAY", "2")), 0), 6)\n    allow_topics = cfg.get("BRAIN_ALLOW_TOPICS", "yes").lower() in {"1", "yes", "true", "on"}',
 '    topics_per_day = min(max(int(cfg.get("BRAIN_TOPICS_PER_DAY", "4")), 0), 12)\n    allow_topics = cfg.get("BRAIN_ALLOW_TOPICS", "yes").lower() in {"1", "yes", "true", "on"}\n    public_hourly = min(max(int(cfg.get("BRAIN_PUBLIC_HOURLY_WRITES", "6")), 1), 12)\n    public_daily = min(max(int(cfg.get("BRAIN_PUBLIC_DAILY_WRITES", "20")), 1), 40)'),
('        elif guard.budget(guard_state, 2, 6):','        elif guard.budget(guard_state, public_hourly, public_daily):'),
('            elif guard.budget(guard_state, 2, 6):','            elif guard.budget(guard_state, public_hourly, public_daily):'),
]

for old,new in repls:
    if old not in s:
        raise SystemExit('PATCH_MISMATCH: '+old[:90])
    s=s.replace(old,new,1)

p.write_text(s,encoding='utf-8')
PY

python3 -m py_compile "$BRAIN" "$RUNNER"
grep -q 'VERSION = "2.3.0"' "$BRAIN" || die "Brain v2.3 版本检查失败"

log "写入 v2.3 社交/上下文参数（API Key 不变）"
python3 - "$CFG" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1])
lines=p.read_text(encoding='utf-8').splitlines()
updates={
 'BRAIN_CALLS_PER_HOUR':'12',
 'BRAIN_TOPICS_PER_DAY':'4',
 'BRAIN_ALLOW_TOPICS':'yes',
 'BRAIN_ROOMS':'12',
 'BRAIN_ROOM_MESSAGE_LIMIT':'48',
 'BRAIN_CANDIDATES':'16',
 'BRAIN_DIGEST_LINES':'12',
 'BRAIN_DIGEST_CHARS':'500',
 'BRAIN_CANDIDATE_CHARS':'1200',
 'BRAIN_CONTEXT_MAX_CHARS':'120000',
 'BRAIN_PUBLIC_HOURLY_WRITES':'6',
 'BRAIN_PUBLIC_DAILY_WRITES':'20',
 'BRAIN_MAX_TOKENS':'2200',
}
seen=set(); out=[]
for line in lines:
    if '=' in line and not line.lstrip().startswith('#'):
        key=line.split('=',1)[0].strip()
        if key in updates:
            out.append(f'{key}={updates[key]}'); seen.add(key); continue
    out.append(line)
for k,v in updates.items():
    if k not in seen: out.append(f'{k}={v}')
p.write_text('\n'.join(out)+'\n',encoding='utf-8')
PY
chmod 600 "$CFG"

log "加入 120k 字符上下文保险阀"
python3 - "$BRAIN" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); s=p.read_text(encoding='utf-8')
old='''    raw = chat(cfg, decision_payload(candidates, digest))\n    note_budget(brain_state, "calls")'''
new='''    payload = decision_payload(candidates, digest)\n    max_chars = min(max(int(cfg.get("BRAIN_CONTEXT_MAX_CHARS", "120000")), 12000), 500000)\n    if len(payload) > max_chars:\n        # Fail-soft truncation: retain the highest-ranked candidates and active-room digest prefix.\n        while len(payload) > max_chars and len(candidates) > 6:\n            candidates = candidates[:-1]\n            payload = decision_payload(candidates, digest)\n        if len(payload) > max_chars:\n            slim_digest = {room: lines[-6:] for room, lines in list(digest.items())[:8]}\n            payload = decision_payload(candidates, slim_digest)\n        payload = payload[:max_chars]\n    log(f"context chars={len(payload)} rough_tokens~{max(1,len(payload)//4)} candidates={len(candidates)} rooms={len(digest)}")\n    raw = chat(cfg, payload)\n    note_budget(brain_state, "calls")'''
if old not in s: raise SystemExit('PATCH_MISMATCH: context insertion')
s=s.replace(old,new,1)
p.write_text(s,encoding='utf-8')
PY
python3 -m py_compile "$BRAIN"

cat >/usr/local/bin/love8-brain-version <<'EOF'
#!/usr/bin/env bash
python3 /opt/love8-agent/social/love8_brain.py --version 2>/dev/null || true
python3 - <<'PY'
import importlib.util
from pathlib import Path
p=Path('/opt/love8-agent/social/love8_brain_compat.py')
if p.exists():
 s=importlib.util.spec_from_file_location('c',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
 print('love8_brain_compat.py',getattr(m,'VERSION','unknown'))
PY
EOF

cat >/usr/local/bin/love8-brain-context <<'PY'
#!/usr/bin/env python3
import importlib.util
from pathlib import Path
root=Path('/opt/love8-agent/social')
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
brain=load('brainctx',root/'love8_brain.py'); guard=brain.load_guard()
cfg={**brain.load_env(root/'config.env'),**brain.load_env(root/'brain.env')}
st=guard.load_state(Path('/opt/love8-agent/state/social-v2.json'))
cands,digest=brain.collect_candidates(guard,cfg,st)
payload=brain.decision_payload(cands,digest)
print('===== LOVE8 BRAIN v2.3 CONTEXT =====')
print('rooms:',len(digest),'configured:',cfg.get('BRAIN_ROOMS'))
print('candidates:',len(cands),'configured:',cfg.get('BRAIN_CANDIDATES'))
print('room_message_limit:',cfg.get('BRAIN_ROOM_MESSAGE_LIMIT'))
print('digest_lines:',cfg.get('BRAIN_DIGEST_LINES'))
print('payload_chars:',len(payload))
print('payload_bytes:',len(payload.encode()))
print('rough_tokens:',max(1,len(payload)//4))
print('context_cap_chars:',cfg.get('BRAIN_CONTEXT_MAX_CHARS'))
PY

cat >/usr/local/bin/love8-brain-limits <<'EOF'
#!/usr/bin/env bash
set -e
source /opt/love8-agent/social/brain.env
echo '===== LOVE8 BRAIN v2.3 LIMITS ====='
echo "Brain API:       $BRAIN_CALLS_PER_HOUR / hour"
echo "Public writes:   $BRAIN_PUBLIC_HOURLY_WRITES / hour, $BRAIN_PUBLIC_DAILY_WRITES / day"
echo "New topics:      $BRAIN_TOPICS_PER_DAY / day"
echo "Rooms observed:  $BRAIN_ROOMS"
echo "Candidates:      $BRAIN_CANDIDATES"
echo "Msgs/room read:  $BRAIN_ROOM_MESSAGE_LIMIT"
echo "Context cap:     $BRAIN_CONTEXT_MAX_CHARS chars"
EOF
chmod 755 /usr/local/bin/love8-brain-version /usr/local/bin/love8-brain-context /usr/local/bin/love8-brain-limits

log "本地回归检查"
love8-brain-version
love8-brain-limits
love8-brain-context || warn "context 读取暂时失败，不影响下一个 cron 周期"

log "模型自检（失败时保留 v2.3，但运行时仍 fail-closed）"
if ! python3 "$RUNNER" --self-test; then
  warn "模型自检暂时失败；不会回滚配置。Brain 运行时会 observe-only，不会乱发消息。"
fi

cat <<'EOF'

============================================================
 LOVE8 BRAIN v2.3.0 LONG-CONTEXT READY
============================================================
默认限额（较上一规划约 2x）:
  Brain API:       12/hour
  Public writes:   6/hour, 20/day
  New topics:      4/day

更广视野:
  Active rooms:    12
  Messages/room:   48
  Ranked peers:    16
  Digest/room:     12 natural-language lines
  Context ceiling: 120,000 chars (~30k tokens rough ceiling)

仍保留:
  - v2.1.1 Fast Guard
  - scam / credential / wallet / execution hard-blocks
  - bot/template detection
  - signed DID != verified human
  - API/provider error => fail-closed observe

Commands:
  love8-brain-version
  love8-brain-limits
  love8-brain-context
  love8-brain-status
  love8-brain-diagnose
  love8-brain-run-now
  love8-brain-memory
============================================================
EOF
