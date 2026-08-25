#!/usr/bin/env bash
set -Eeuo pipefail

# Upgrade an existing aizong Technocore agent to Social Brain v1.2.0.
# Preserves DID/private key, mailbox, brain API key, write budget and social state.

REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/yinchun6969/technocore-chat/main}"
AGENT_DIR="/opt/technocore-agent"
STATE_DIR="$AGENT_DIR/state"
CONFIG="$AGENT_DIR/config"
BRAIN_CONFIG="$AGENT_DIR/brain.env"
PROGRAM="$AGENT_DIR/aizong_social.py"
TOPICS="$STATE_DIR/trusted-topics.json"
SERVICE="technocore-aizong-social.service"

log() { printf '\n[+] %s\n' "$*"; }
die() { printf '\n[x] %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "请用 root 执行"
[ -s "$CONFIG" ] || die "找不到 $CONFIG；请先安装现有 aizong agent"
command -v python3 >/dev/null || die "python3 未安装"
command -v curl >/dev/null || die "curl 未安装"
command -v systemctl >/dev/null || die "systemd 未安装"

# shellcheck disable=SC1090
source "$CONFIG"
: "${NICK:?missing NICK}"
: "${DID:?missing DID}"
: "${KEY:?missing KEY}"
: "${FP:?missing FP}"
[ -s "$KEY" ] || die "Ed25519 私钥不存在：$KEY"

mkdir -p "$STATE_DIR"
chmod 700 "$AGENT_DIR" "$STATE_DIR"

if [ ! -f "$BRAIN_CONFIG" ]; then
  cat >"$BRAIN_CONFIG" <<'EOF'
BRAIN_URL=
BRAIN_MODEL=
BRAIN_KEY=
BRAIN_TIMEOUT=25
BRAIN_MAX_TOKENS=768
EOF
  chmod 600 "$BRAIN_CONFIG"
fi

BRAIN_URL=""
BRAIN_MODEL=""
BRAIN_KEY=""
BRAIN_TIMEOUT="25"
BRAIN_MAX_TOKENS="768"
# shellcheck disable=SC1090
source "$BRAIN_CONFIG"
BRAIN_URL="${BRAIN_URL%/}"
case "$BRAIN_URL" in
  */v1) BRAIN_URL="$BRAIN_URL/chat/completions" ;;
esac
if ! [[ "$BRAIN_MAX_TOKENS" =~ ^[0-9]+$ ]] || [ "$BRAIN_MAX_TOKENS" -lt 768 ]; then
  BRAIN_MAX_TOKENS="768"
fi
{
  printf 'BRAIN_URL=%q\n' "$BRAIN_URL"
  printf 'BRAIN_MODEL=%q\n' "$BRAIN_MODEL"
  printf 'BRAIN_KEY=%q\n' "$BRAIN_KEY"
  printf 'BRAIN_TIMEOUT=%q\n' "$BRAIN_TIMEOUT"
  printf 'BRAIN_MAX_TOKENS=%q\n' "$BRAIN_MAX_TOKENS"
} >"$BRAIN_CONFIG"
chmod 600 "$BRAIN_CONFIG"

if [ ! -f "$TOPICS" ]; then
  printf '{"topics":[]}\n' >"$TOPICS"
  chmod 600 "$TOPICS"
fi

backup_suffix="$(date +%Y%m%d-%H%M%S)"
[ -f "$PROGRAM" ] && cp -a "$PROGRAM" "$PROGRAM.bak-$backup_suffix"
[ -f "$STATE_DIR/social-v1.json" ] && \
  cp -a "$STATE_DIR/social-v1.json" "$STATE_DIR/social-v1.json.bak-$backup_suffix"

log "下载 aizong Social Brain v1.2.0"
curl -fsSL "$REPO_RAW/scripts/aizong_social.py" -o "$PROGRAM.new"
python3 -m py_compile "$PROGRAM.new"
grep -q 'VERSION = "1.2.0"' "$PROGRAM.new" || die "下载到的程序不是 v1.2.0"
grep -q 'prompt_injection_risk' "$PROGRAM.new" || die "Relationship Intelligence 检查失败"
grep -q 'reconnect_candidate' "$PROGRAM.new" || die "主动重联模块检查失败"
chmod 700 "$PROGRAM.new"
mv "$PROGRAM.new" "$PROGRAM"

log "迁移现有联系人状态（保留旧分数/记忆）"
STATE_FILE="$STATE_DIR/social-v1.json" python3 <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["STATE_FILE"])
if not path.exists():
    raise SystemExit(0)
data = json.loads(path.read_text(encoding="utf-8"))
contacts = data.setdefault("contacts", {})
for contact in contacts.values():
    if not isinstance(contact, dict):
        continue
    verified = bool(contact.get("verified"))
    contact.setdefault("interest_score", 0)
    contact.setdefault("trust_score", 10 if verified else 5)
    contact.setdefault("bot_probability", 15 if verified else 25)
    contact.setdefault("scam_risk", 0)
    contact.setdefault("prompt_injection_risk", 0)
    contact.setdefault("spam_probability", 0)
    contact.setdefault(
        "relationship_stage", "observed" if contact.get("messages_seen") else "stranger"
    )
    contact.setdefault("inbound_count", int(contact.get("messages_seen", 0) or 0))
    contact.setdefault("outbound_count", 0)
    contact.setdefault("ai_interactions", 0)
    contact.setdefault("last_seq_by_room", {})
    memory = contact.setdefault("memory", {})
    if contact.get("note") and not memory.get("summary"):
        memory["summary"] = str(contact["note"])
    memory.setdefault("capabilities", [])
    memory.setdefault("projects", [])
    memory.setdefault("interests", [])
    memory.setdefault("topics", [])
data["version"] = "1.2.0"
tmp = path.with_suffix(".tmp")
tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
tmp.chmod(0o600)
os.replace(tmp, path)
PY

log "安装 v1.2 systemd 服务"
cat >"/etc/systemd/system/$SERVICE" <<EOF
[Unit]
Description=aizong Social v1.2 relationship-intelligence agent for technocore.chat
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 $PROGRAM
Restart=on-failure
RestartSec=30
Environment=PYTHONUNBUFFERED=1
Environment=TC_SOCIAL_BRAIN_CONFIG=$BRAIN_CONFIG
Environment=TC_SOCIAL_TOPICS=$TOPICS
Environment=TC_SOCIAL_INTERVAL=300
Environment=TC_SOCIAL_ROOMS=5
Environment=TC_SOCIAL_HOURLY_WRITES=3
Environment=TC_SOCIAL_DAILY_WRITES=12
Environment=TC_SOCIAL_MAX_FOLLOWUPS=6
Environment=TC_SOCIAL_REPLY_COOLDOWN=300
Environment=TC_SOCIAL_RECONNECT_AFTER=21600
Environment=TC_SOCIAL_RECONNECT_COOLDOWN=43200
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$AGENT_DIR

[Install]
WantedBy=multi-user.target
EOF

cat >/usr/local/bin/tc-social-contacts <<'EOF'
#!/usr/bin/env python3
import json
from pathlib import Path

path = Path("/opt/technocore-agent/state/social-v1.json")
if not path.exists():
    print("No social state yet.")
    raise SystemExit(0)
data = json.loads(path.read_text(encoding="utf-8"))
contacts = [x for x in data.get("contacts", {}).values() if isinstance(x, dict)]
contacts.sort(
    key=lambda x: (
        int(x.get("interest_score", 0) or 0),
        int(x.get("trust_score", 0) or 0),
        int(x.get("last_seen", 0) or 0),
    ),
    reverse=True,
)
if not contacts:
    print("No contacts yet.")
for item in contacts[:40]:
    author = str(item.get("author", ""))
    room = str(item.get("last_room", ""))
    stage = str(item.get("relationship_stage", "stranger"))
    interest = int(item.get("interest_score", 0) or 0)
    trust = int(item.get("trust_score", 0) or 0)
    bot = int(item.get("bot_probability", 0) or 0)
    risk = max(
        int(item.get("scam_risk", 0) or 0),
        int(item.get("prompt_injection_risk", 0) or 0),
        int(item.get("spam_probability", 0) or 0),
    )
    verified = "DID" if item.get("verified") else "nick"
    print(
        f"I{interest:02d} T{trust:02d} B{bot:02d} R{risk:02d} "
        f"{stage:<17} {verified:<4} {author[:54]} room={room}"
    )
    memory = item.get("memory", {})
    if isinstance(memory, dict) and memory.get("summary"):
        print(f"    {str(memory['summary'])[:180]}")
EOF

cat >/usr/local/bin/tc-social-contact <<'EOF'
#!/usr/bin/env python3
import json
import sys
from pathlib import Path

if len(sys.argv) < 2:
    print("Usage: tc-social-contact <DID/prefix/substring>")
    raise SystemExit(2)
needle = sys.argv[1].lower()
path = Path("/opt/technocore-agent/state/social-v1.json")
if not path.exists():
    raise SystemExit("No social state yet.")
data = json.loads(path.read_text(encoding="utf-8"))
matches = []
for item in data.get("contacts", {}).values():
    if not isinstance(item, dict):
        continue
    author = str(item.get("author", ""))
    if needle in author.lower():
        matches.append(item)
if not matches:
    raise SystemExit("No matching contact.")
for item in matches[:5]:
    print(json.dumps(item, ensure_ascii=False, indent=2))
EOF

cat >/usr/local/bin/tc-social-stats <<'EOF'
#!/usr/bin/env python3
import json
import time
from collections import Counter
from pathlib import Path

state_path = Path("/opt/technocore-agent/state/social-v1.json")
topic_path = Path("/opt/technocore-agent/state/trusted-topics.json")
if not state_path.exists():
    print("No social state yet.")
    raise SystemExit(0)
data = json.loads(state_path.read_text(encoding="utf-8"))
contacts = [x for x in data.get("contacts", {}).values() if isinstance(x, dict)]
stages = Counter(str(x.get("relationship_stage", "stranger")) for x in contacts)
now = time.time()
writes = [float(x) for x in data.get("writes", [])]
topics = 0
if topic_path.exists():
    try:
        raw = json.loads(topic_path.read_text(encoding="utf-8"))
        topics = len(raw.get("topics", [])) if isinstance(raw, dict) else len(raw)
    except Exception:
        topics = 0
print(f"version: {data.get('version', '-')}")
print(f"contacts: {len(contacts)}")
print(f"brain_scored: {sum(1 for x in contacts if x.get('last_brain_at'))}")
print(
    f"likely_bots>=80: "
    f"{sum(1 for x in contacts if int(x.get('bot_probability', 0) or 0) >= 80)}"
)
print(
    "high_risk>=70: "
    + str(
        sum(
            1
            for x in contacts
            if max(
                int(x.get("scam_risk", 0) or 0),
                int(x.get("prompt_injection_risk", 0) or 0),
                int(x.get("spam_probability", 0) or 0),
            )
            >= 70
        )
    )
)
print(f"trusted_topics: {topics}")
print(f"writes_1h: {sum(1 for x in writes if now - x < 3600)}")
print(f"writes_24h: {sum(1 for x in writes if now - x < 86400)}")
for stage in (
    "stranger",
    "observed",
    "contacted",
    "recurring_contact",
    "trusted_peer",
    "collaborator",
):
    print(f"{stage}: {stages.get(stage, 0)}")
EOF

cat >/usr/local/bin/tc-social-topic <<'EOF'
#!/usr/bin/env python3
import json
import sys
from pathlib import Path

path = Path("/opt/technocore-agent/state/trusted-topics.json")
path.parent.mkdir(parents=True, exist_ok=True)
try:
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"topics": []}
except json.JSONDecodeError:
    data = {"topics": []}
topics = data.get("topics", []) if isinstance(data, dict) else []
if not isinstance(topics, list):
    topics = []
cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
if cmd == "list":
    if not topics:
        print("No trusted topics.")
    for i, topic in enumerate(topics, 1):
        print(f"{i}. {topic}")
elif cmd == "add":
    text = " ".join(sys.argv[2:]).strip()
    if not text:
        raise SystemExit("Usage: tc-social-topic add <operator-approved topic summary>")
    text = " ".join(text.split())[:280]
    if text not in topics:
        topics.append(text)
    topics = topics[-20:]
    path.write_text(
        json.dumps({"topics": topics}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    path.chmod(0o600)
    print("Trusted topic added.")
elif cmd == "remove":
    if len(sys.argv) != 3 or not sys.argv[2].isdigit():
        raise SystemExit("Usage: tc-social-topic remove <number>")
    idx = int(sys.argv[2]) - 1
    if idx < 0 or idx >= len(topics):
        raise SystemExit("Topic number out of range.")
    removed = topics.pop(idx)
    path.write_text(
        json.dumps({"topics": topics}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    path.chmod(0o600)
    print(f"Removed: {removed}")
elif cmd == "clear":
    path.write_text('{"topics":[]}\n', encoding="utf-8")
    path.chmod(0o600)
    print("Trusted topics cleared.")
else:
    raise SystemExit("Usage: tc-social-topic [list|add <text>|remove <n>|clear]")
EOF

cat >/usr/local/bin/tc-social-test <<'EOF'
#!/usr/bin/env bash
exec python3 /opt/technocore-agent/aizong_social.py --once --dry-run "$@"
EOF

cat >/usr/local/bin/tc-social-status <<EOF
#!/usr/bin/env bash
exec systemctl --no-pager --full status $SERVICE
EOF

cat >/usr/local/bin/tc-social-log <<EOF
#!/usr/bin/env bash
exec journalctl -u $SERVICE -n "\${1:-100}" --no-pager
EOF

cat >/usr/local/bin/tc-social-start <<EOF
#!/usr/bin/env bash
exec systemctl start $SERVICE
EOF

cat >/usr/local/bin/tc-social-stop <<EOF
#!/usr/bin/env bash
exec systemctl stop $SERVICE
EOF

chmod 755 \
  /usr/local/bin/tc-social-contacts \
  /usr/local/bin/tc-social-contact \
  /usr/local/bin/tc-social-stats \
  /usr/local/bin/tc-social-topic \
  /usr/local/bin/tc-social-test \
  /usr/local/bin/tc-social-status \
  /usr/local/bin/tc-social-log \
  /usr/local/bin/tc-social-start \
  /usr/local/bin/tc-social-stop

systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null
systemctl restart "$SERVICE"
sleep 2

log "aizong Social Brain v1.2.0 installed"
printf 'Agent:              %s\n' "$NICK"
printf 'DID:                %s\n' "$DID"
printf 'Brain model:        %s\n' "${BRAIN_MODEL:-rules fallback}"
printf 'Write cap:          3/hour, 12/day\n'
printf 'Reconnect:          after 6h; max one consideration per 12h\n'
printf 'Relationship intel: trust / bot / scam / injection / spam / memory / stages\n'
printf 'Trusted topics:     local operator-approved feed only (no room-driven URL fetching)\n'
printf '\nCommands:\n'
printf '  tc-social-status\n'
printf '  tc-social-log 100\n'
printf '  tc-social-contacts\n'
printf '  tc-social-contact <DID-prefix>\n'
printf '  tc-social-stats\n'
printf '  tc-social-topic list\n'
printf '  tc-social-topic add "topic summary"\n'
printf '  tc-social-test\n'
