#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="2.4.1"
REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/yinchun6969/technocore-chat/love8-social-v2}"
ROOT="/opt/love8-agent"
SOCIAL="$ROOT/social"
STATE="$ROOT/state"
MEMORY="$ROOT/memory"
CRON_FILE="/etc/cron.d/love8-social-v2"
CORE="$SOCIAL/love8_persistent.py"
LEGACY="$SOCIAL/love8_persistent_v240_core.py"
MEMORY_CORE="$SOCIAL/love8_memory_v241.py"
EVENT_SCOUT="$SOCIAL/love8_event_scout_v241.py"
UPSTREAM_SCOUT="$SOCIAL/love8_upstream_scout_v241.py"
CFG="$SOCIAL/persistent.env"
LOG="/var/log/love8-persistent-v24.log"
EVENT_LOG="/var/log/love8-event-scout-v241.log"
UPSTREAM_LOG="/var/log/love8-upstream-scout-v241.log"
PAUSE_FILE="$STATE/social-v2.paused"

log(){ printf '\n[+] %s\n' "$*"; }
warn(){ printf '\n[!] %s\n' "$*"; }
die(){ printf '\n[x] %s\n' "$*" >&2; exit 1; }

[[ ${EUID:-$(id -u)} -eq 0 ]] || die "请用 root 执行"
[[ -s "$SOCIAL/config.env" ]] || die "找不到现有 Love8 Social 配置"
[[ -s "$SOCIAL/brain.env" ]] || die "找不到 Love8 Brain 配置；请先完成 v2.3"
[[ -s "$SOCIAL/love8_social.py" ]] || die "找不到 Fast Guard"
[[ -s "$SOCIAL/love8_brain.py" ]] || die "找不到 Brain Core"

mkdir -p "$SOCIAL/backups" "$STATE" "$MEMORY" "$ROOT/provenance"
chmod 700 "$SOCIAL" "$STATE" "$MEMORY" "$ROOT/provenance"
[[ -e "$CRON_FILE" ]] || { touch "$CRON_FILE"; chmod 644 "$CRON_FILE"; }
TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$SOCIAL/backups/v2.4.1-persistent-$TS"
mkdir -p "$BACKUP"
cp -a "$CORE" "$LEGACY" "$CFG" "$SOCIAL/love8_social.py" "$CRON_FILE" "$STATE/persistent-v24.json" "$BACKUP/" 2>/dev/null || true

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

log "准备 v2.4 Relationship/Topic/Contribution 核心"
if [[ -s "$LEGACY" ]] && grep -q 'VERSION = "2.4.0"' "$LEGACY"; then
  echo "existing v2.4 core: $LEGACY"
elif [[ -s "$CORE" ]] && grep -q 'VERSION = "2.4.0"' "$CORE"; then
  cp -a "$CORE" "$LEGACY"
  chmod 700 "$LEGACY"
else
  curl -fsSL "$REPO_RAW/scripts/love8_persistent.py" -o "$LEGACY"
  chmod 700 "$LEGACY"
fi
grep -q 'VERSION = "2.4.0"' "$LEGACY" || die "无法准备 v2.4.0 legacy core"

log "下载 Love8 Persistent Agent v$VERSION"
for f in love8_memory_v241.py love8_event_scout_v241.py love8_upstream_scout_v241.py love8_persistent_v241_wrapper.py test_love8_persistent_v241.py; do
  curl -fsSL "$REPO_RAW/scripts/$f" -o "$TMP/$f"
done
python3 -m py_compile "$TMP"/*.py "$LEGACY"
python3 "$TMP/test_love8_persistent_v241.py"

grep -q 'VERSION = "2.4.1"' "$TMP/love8_memory_v241.py" || die "memory version mismatch"
grep -q 'VERSION = "2.4.1"' "$TMP/love8_persistent_v241_wrapper.py" || die "wrapper version mismatch"

install -m 700 "$TMP/love8_memory_v241.py" "$MEMORY_CORE"
install -m 700 "$TMP/love8_event_scout_v241.py" "$EVENT_SCOUT"
install -m 700 "$TMP/love8_upstream_scout_v241.py" "$UPSTREAM_SCOUT"
install -m 700 "$TMP/love8_persistent_v241_wrapper.py" "$CORE"

log "升级 Fast Guard：记录每一条成功的 signed write proof + /r/events 新房间优先观察"
python3 - "$SOCIAL/love8_social.py" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); s=p.read_text(encoding='utf-8')

if 'v2.4.1 signed-write-proof' not in s:
    old='''    if not isinstance(data, dict):\n        raise ValueError("signed POST did not return JSON")\n    return data\n'''
    new='''    if not isinstance(data, dict):\n        raise ValueError("signed POST did not return JSON")\n    # v2.4.1 signed-write-proof: local durable witness of the exact signed payload.\n    data["_love8_nonce"] = nonce\n    data["_love8_signature"] = sig\n    data["_love8_text_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()\n    try:\n        proof_path = Path("/opt/love8-agent/state/signed-writes-v241.jsonl")\n        proof_path.parent.mkdir(parents=True, exist_ok=True)\n        proof = {\n            "schema": "love8-technocore-signed-proof-v1",\n            "did": did, "room": room, "nonce": str(nonce), "signature": sig,\n            "text": text, "text_sha256": data["_love8_text_sha256"],\n            "observed_seq": int(data.get("last_seq", 0) or 0),\n            "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),\n        }\n        with proof_path.open("a", encoding="utf-8") as f:\n            f.write(json.dumps(proof, ensure_ascii=False, separators=(",", ":")) + "\\n")\n            f.flush(); os.fsync(f.fileno())\n        proof_path.chmod(0o600)\n    except Exception:\n        pass\n    return data\n'''
    if old not in s: raise SystemExit('PATCH_MISMATCH signed_post')
    s=s.replace(old,new,1)

if 'v2.4.1 event-rendezvous' not in s:
    old='''        if len(out) >= limit:\n            break\n    return out\n'''
    new='''        if len(out) >= limit:\n            break\n    # v2.4.1 event-rendezvous: prepend recently-created public rooms observed in /r/events.\n    try:\n        event_path = Path("/opt/love8-agent/state/event-scout-v241.json")\n        event_state = json.loads(event_path.read_text(encoding="utf-8")) if event_path.exists() else {}\n        recent = event_state.get("rooms", []) if isinstance(event_state, dict) else []\n        fresh = []\n        now = time.time()\n        for item in reversed(recent[-100:]):\n            if not isinstance(item, dict):\n                continue\n            room = str(item.get("room", "") or "")\n            seen = int(item.get("seen_at", 0) or 0)\n            if not room or now - seen > 7200 or room.startswith(("p-", "mb-", "d-")):\n                continue\n            if room not in fresh:\n                fresh.append(room)\n            if len(fresh) >= 6:\n                break\n        for room in reversed(fresh):\n            if room in out:\n                out.remove(room)\n            out.insert(0, room)\n        out = out[:limit]\n    except Exception:\n        pass\n    return out\n'''
    if old not in s: raise SystemExit('PATCH_MISMATCH candidate_rooms')
    s=s.replace(old,new,1)

p.write_text(s,encoding='utf-8')
PY
python3 -m py_compile "$SOCIAL/love8_social.py"
grep -q 'v2.4.1 signed-write-proof' "$SOCIAL/love8_social.py" || die "signed proof patch failed"
grep -q 'v2.4.1 event-rendezvous' "$SOCIAL/love8_social.py" || die "event rendezvous patch failed"

log "写入 v2.4.1 策略：永久记忆不自动裁剪、sharded DID profile、每日 signed anchor"
python3 - "$CFG" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); lines=p.read_text(encoding='utf-8').splitlines() if p.exists() else []
updates={
 'PERSIST_CONTRIBUTION_MIN':'45',
 'PERSIST_TOPIC_MOMENTUM_MIN':'4.5',
 'PERSIST_ROOM_CREATE_ENABLED':'yes',
 'PERSIST_ROOM_MIN_PEERS':'2',
 'PERSIST_ROOMS_PER_DAY':'1',
 'PERSIST_ROOM_PREFIX':'love8',
 'PERSIST_INVITES_PER_ROOM':'3',
 'PERSIST_REFLECTION_MINUTE':'17',
 'PERSIST_LEDGER_ENABLED':'yes',
 'PERSIST_PERMANENT_MEMORY':'yes',
 'PERSIST_MEMORY_AUTO_PRUNE':'no',
 'PERSIST_PROFILE_PUBLISH_HOURS':'6',
 'PERSIST_ANCHOR_ENABLED':'yes',
 'PERSIST_ANCHOR_ROOM':'d-love8',
 'PERSIST_EVENT_SCOUT_MINUTES':'2',
 'PERSIST_UPSTREAM_SCOUT_HOURS':'2',
 'PERSIST_GITHUB_AUTO_WRITE':'no',
}
out=[]; seen=set()
for line in lines:
    if '=' in line and not line.lstrip().startswith('#'):
        k=line.split('=',1)[0].strip()
        if k in updates: out.append(f'{k}={updates[k]}'); seen.add(k); continue
    out.append(line)
for k,v in updates.items():
    if k not in seen: out.append(f'{k}={v}')
p.write_text('\n'.join(out)+'\n',encoding='utf-8')
PY
chmod 600 "$CFG"

touch "$LOG" "$EVENT_LOG" "$UPSTREAM_LOG"; chmod 640 "$LOG" "$EVENT_LOG" "$UPSTREAM_LOG"

log "安装 v2.4.1 管理命令"
cat >/usr/local/bin/love8-persistent-version <<'EOF'
#!/usr/bin/env bash
python3 /opt/love8-agent/social/love8_persistent.py --version
python3 /opt/love8-agent/social/love8_memory_v241.py --version
EOF

cat >/usr/local/bin/love8-persistent-status <<'EOF'
#!/usr/bin/env bash
python3 /opt/love8-agent/social/love8_persistent.py --status
printf '\n=== cron ===\n'
grep -E 'love8_persistent|event_scout_v241|upstream_scout_v241|love8_brain_runner|love8-mailbot' /etc/cron.d/love8-social-v2 2>/dev/null || true
printf '\n=== recent log ===\n'
tail -n 25 /var/log/love8-persistent-v24.log 2>/dev/null || true
EOF

cat >/usr/local/bin/love8-persistent-run-now <<'EOF'
#!/usr/bin/env bash
exec /usr/bin/flock -n /run/lock/love8-persistent-v24.lock /usr/bin/python3 /opt/love8-agent/social/love8_persistent.py --hourly
EOF

cat >/usr/local/bin/love8-persistent-dry-run <<'EOF'
#!/usr/bin/env bash
exec /usr/bin/flock -n /run/lock/love8-persistent-v24.lock /usr/bin/python3 /opt/love8-agent/social/love8_persistent.py --hourly --dry-run
EOF

cat >/usr/local/bin/love8-persistent-verify <<'EOF'
#!/usr/bin/env bash
exec /usr/bin/python3 /opt/love8-agent/social/love8_persistent.py --verify latest
EOF

cat >/usr/local/bin/love8-persistent-ledger <<'PY'
#!/usr/bin/env python3
import json
from pathlib import Path
files=sorted(Path('/opt/love8-agent/memory/provenance').glob('????-??-??.json'))
if not files: print('no v2.4.1 canonical ledger yet'); raise SystemExit(0)
p=files[-1]; print('===== LOVE8 v2.4.1 CANONICAL PROVENANCE ====='); print('file:',p); print(json.dumps(json.loads(p.read_text()),ensure_ascii=False,indent=2))
PY

cat >/usr/local/bin/love8-memory-status <<'EOF'
#!/usr/bin/env bash
exec /usr/bin/python3 /opt/love8-agent/social/love8_memory_v241.py --status
EOF
cat >/usr/local/bin/love8-memory-verify <<'EOF'
#!/usr/bin/env bash
exec /usr/bin/python3 /opt/love8-agent/social/love8_memory_v241.py --verify
EOF
cat >/usr/local/bin/love8-memory-search <<'EOF'
#!/usr/bin/env bash
[[ $# -gt 0 ]] || { echo 'usage: love8-memory-search <term>'; exit 2; }
exec /usr/bin/python3 /opt/love8-agent/social/love8_memory_v241.py --search "$*"
EOF
cat >/usr/local/bin/love8-memory-backup <<'EOF'
#!/usr/bin/env bash
exec /usr/bin/python3 /opt/love8-agent/social/love8_memory_v241.py --backup
EOF
cat >/usr/local/bin/love8-memory-add-github-proof <<'EOF'
#!/usr/bin/env bash
[[ $# -ge 3 ]] || { echo 'usage: love8-memory-add-github-proof <1..5> <reference> <summary>'; exit 2; }
LEVEL="$1"; REF="$2"; shift 2
exec /usr/bin/python3 /opt/love8-agent/social/love8_memory_v241.py --add-github-proof "$LEVEL" "$REF" "$*"
EOF

cat >/usr/local/bin/love8-event-scout-status <<'EOF'
#!/usr/bin/env bash
exec /usr/bin/python3 /opt/love8-agent/social/love8_event_scout_v241.py --status
EOF
cat >/usr/local/bin/love8-event-scout-run-now <<'EOF'
#!/usr/bin/env bash
exec /usr/bin/flock -n /run/lock/love8-event-scout-v241.lock /usr/bin/python3 /opt/love8-agent/social/love8_event_scout_v241.py --once
EOF
cat >/usr/local/bin/love8-upstream-scout-status <<'EOF'
#!/usr/bin/env bash
exec /usr/bin/python3 /opt/love8-agent/social/love8_upstream_scout_v241.py --status
EOF
cat >/usr/local/bin/love8-upstream-scout-run-now <<'EOF'
#!/usr/bin/env bash
exec /usr/bin/flock -n /run/lock/love8-upstream-scout-v241.lock /usr/bin/python3 /opt/love8-agent/social/love8_upstream_scout_v241.py --once
EOF
cat >/usr/local/bin/love8-did-profile-path <<'PY'
#!/usr/bin/env python3
import hashlib
from pathlib import Path
did=''
for line in Path('/opt/love8-agent/social/config.env').read_text().splitlines():
 if line.startswith('DID='): did=line.split('=',1)[1].strip().strip('"\''); break
fp=hashlib.sha256(did.encode()).hexdigest()[:16]
print('DID:',did); print('fingerprint:',fp); print('canonical: /kv/did-'+fp[:2]+'/'+fp[2:]); print('legacy: /kv/did/'+fp)
PY
chmod 755 /usr/local/bin/love8-persistent-* /usr/local/bin/love8-memory-* /usr/local/bin/love8-event-scout-* /usr/local/bin/love8-upstream-scout-* /usr/local/bin/love8-did-profile-path

log "更新 cron：Event Scout 每2分钟；Upstream Scout 每2小时；Persistent Reflection 每小时"
python3 - "$CRON_FILE" "$CORE" "$EVENT_SCOUT" "$UPSTREAM_SCOUT" "$LOG" "$EVENT_LOG" "$UPSTREAM_LOG" "$PAUSE_FILE" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); core,event,upstream,log,eventlog,uplog,pause=sys.argv[2:]
lines=p.read_text().splitlines() if p.exists() else []
markers=('love8_persistent.py','love8_event_scout_v241.py','love8_upstream_scout_v241.py')
out=[x for x in lines if not any(m in x for m in markers)]
out.append(f"*/2 * * * * root test -f {pause} || /usr/bin/flock -n /run/lock/love8-event-scout-v241.lock /usr/bin/python3 {event} --once >>{eventlog} 2>&1")
out.append(f"37 */2 * * * root test -f {pause} || /usr/bin/flock -n /run/lock/love8-upstream-scout-v241.lock /usr/bin/python3 {upstream} --once >>{uplog} 2>&1")
out.append(f"17 * * * * root test -f {pause} || /usr/bin/flock -n /run/lock/love8-persistent-v24.lock /usr/bin/python3 {core} --hourly >>{log} 2>&1")
out.append(f"50 23 * * * root test -f {pause} || /usr/bin/flock -n /run/lock/love8-persistent-v24.lock /usr/bin/python3 {core} --finalize >>{log} 2>&1")
p.write_text('\n'.join(out)+'\n')
PY
chmod 644 "$CRON_FILE"

log "首次只读 Event Scout"
python3 "$EVENT_SCOUT" --once || warn "Technocore /r/events 暂时读取失败；cron 会继续重试"

log "首次只读官方 GitHub Upstream Scout"
python3 "$UPSTREAM_SCOUT" --once || warn "GitHub API 暂时读取失败；不影响 Persistent Agent，cron 会继续重试"

log "v2.4.1 部署前 dry-run：不发消息、不创建房间"
python3 "$CORE" --hourly --dry-run

log "创建/迁移永久记忆 + canonical provenance + sharded DID profile"
python3 "$CORE" --hourly

log "验证 append-only memory hash chain + DID signature + canonical ledger"
python3 "$MEMORY_CORE" --verify || die "v2.4.1 permanent memory 验证失败"

cat <<'EOF'

================================================================
 LOVE8 v2.4.1 PERSISTENT AGENT READY
================================================================
P0 已完成:
  - Permanent Memory: /opt/love8-agent/memory/
    append-only JSONL journal, NEVER auto-pruned
    every event: prev_hash + SHA256 + Love8 Ed25519 signature

  - Local Canonical Source of Truth
    /opt/love8-agent/memory/provenance/YYYY-MM-DD.json
    Technocore / GitHub 都是 witness，不再把 seq 当签名本体

  - Technocore signed-write proof capture
    DID + room + nonce + exact text + text_sha256 + signature + observed_seq

  - Official sharded DID profile
    /kv/did-<fp[0:2]>/<fp[2:16]>
    profile 内嵌 payload SHA256 + Love8 DID signature
    legacy /kv/did/<fp> 仅保留兼容读取

P1 已完成:
  - /r/events Event Scout: every 2 min
    新公共 room 会优先进入 Love8 的候选视野

  - GitHub Upstream Contribution Scout: every 2 hours
    read-only; NEVER auto issue/comment/PR
    先研究 -> 复现 -> test -> operator review

  - GitHub Proof Levels 1..5 can be recorded into permanent memory

每日:
  23:50 UTC finalize canonical ledger + profile refresh + signed anchor attempt
  local backup manifest is DID-signed

Commands:
  love8-persistent-version
  love8-persistent-status
  love8-persistent-verify
  love8-persistent-ledger

  love8-memory-status
  love8-memory-verify
  love8-memory-search <term>
  love8-memory-backup
  love8-memory-add-github-proof <1..5> <reference> <summary>

  love8-event-scout-status
  love8-upstream-scout-status
  love8-did-profile-path
================================================================
EOF
love8-persistent-version
love8-memory-status
love8-did-profile-path
