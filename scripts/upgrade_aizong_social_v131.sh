#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="1.3.1"
REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/yinchun6969/technocore-chat/main}"
AGENT_DIR="/opt/technocore-agent"
STATE_DIR="$AGENT_DIR/state"
STATE="$STATE_DIR/social-v1.json"
BRAIN_CONFIG="$AGENT_DIR/brain.env"
PROGRAM="$AGENT_DIR/aizong_social.py"
PATCHER="$AGENT_DIR/patch_aizong_social_v131.py"
SERVICE="technocore-aizong-social.service"
DROPIN_DIR="/etc/systemd/system/$SERVICE.d"
DROPIN="$DROPIN_DIR/40-v131-resilience.conf"

log() { printf '\n[+] %s\n' "$*"; }
warn() { printf '\n[!] %s\n' "$*"; }
die() { printf '\n[x] %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "请用 root 执行"
[ -s "$PROGRAM" ] || die "找不到 $PROGRAM；请先安装 aizong Social"
[ -s "$BRAIN_CONFIG" ] || die "找不到 $BRAIN_CONFIG；请先完成 Brain 配置"
command -v python3 >/dev/null || die "python3 未安装"
command -v curl >/dev/null || die "curl 未安装"
command -v systemctl >/dev/null || die "systemd 未安装"

# v1.3.1 can be invoked directly from older supported installations. Reuse the
# existing state-preserving v1.3 bootstrap first, then apply resilience.
if grep -Eq 'VERSION = "1\.(1\.[0-9]+|2\.0)"' "$PROGRAM"; then
  log "检测到 v1.1/v1.2；先自动无损升级到 v1.3.0"
  curl -fsSL "$REPO_RAW/scripts/upgrade_aizong_social_v130.sh" -o /tmp/aizong-v130-bootstrap.sh
  bash /tmp/aizong-v130-bootstrap.sh
fi

if ! grep -Eq 'VERSION = "1\.3\.(0|1)"' "$PROGRAM"; then
  die "当前 aizong Social 不是受支持的 v1.1/v1.2/v1.3.0/v1.3.1"
fi

TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$AGENT_DIR/backups/v1.3.1-upgrade-$TS"
mkdir -p "$BACKUP"
chmod 700 "$AGENT_DIR/backups" "$BACKUP"
cp -a "$PROGRAM" "$BRAIN_CONFIG" "$STATE" "$BACKUP/" 2>/dev/null || true
systemctl cat "$SERVICE" >"$BACKUP/$SERVICE.txt" 2>/dev/null || true

log "升级 aizong Social Brain 到 v$VERSION：Network Resilience"
curl -fsSL "$REPO_RAW/scripts/patch_aizong_social_v131.py" -o "$PATCHER.new"
python3 -m py_compile "$PATCHER.new"
chmod 700 "$PATCHER.new"
mv "$PATCHER.new" "$PATCHER"
python3 "$PATCHER" "$PROGRAM"
python3 -m py_compile "$PROGRAM"
grep -q 'VERSION = "1.3.1"' "$PROGRAM" || die "v1.3.1 版本检查失败"
grep -q 'TC_NET_RETRIES' "$PROGRAM" || die "network retry 检查失败"
grep -q 'brain transport cooldown' "$PROGRAM" || die "Brain defer/cooldown 检查失败"

log "调整 Brain transport 参数；URL / Model / API Key 保持不变"
BRAIN_URL=""
BRAIN_MODEL=""
BRAIN_KEY=""
BRAIN_TIMEOUT="60"
BRAIN_MAX_TOKENS="1536"
BRAIN_CONTEXT_MAX_CHARS="60000"
BRAIN_RETRIES="3"
# shellcheck disable=SC1090
source "$BRAIN_CONFIG"

if ! [[ "${BRAIN_TIMEOUT:-}" =~ ^[0-9]+$ ]] || [ "$BRAIN_TIMEOUT" -lt 60 ]; then
  BRAIN_TIMEOUT="60"
fi
if [ "$BRAIN_TIMEOUT" -gt 120 ]; then
  BRAIN_TIMEOUT="120"
fi
if ! [[ "${BRAIN_RETRIES:-}" =~ ^[0-9]+$ ]]; then
  BRAIN_RETRIES="3"
fi
if [ "$BRAIN_RETRIES" -lt 1 ]; then BRAIN_RETRIES="1"; fi
if [ "$BRAIN_RETRIES" -gt 3 ]; then BRAIN_RETRIES="3"; fi
if ! [[ "${BRAIN_MAX_TOKENS:-}" =~ ^[0-9]+$ ]] || [ "$BRAIN_MAX_TOKENS" -lt 1536 ]; then
  BRAIN_MAX_TOKENS="1536"
fi
if ! [[ "${BRAIN_CONTEXT_MAX_CHARS:-}" =~ ^[0-9]+$ ]] || [ "$BRAIN_CONTEXT_MAX_CHARS" -lt 60000 ]; then
  BRAIN_CONTEXT_MAX_CHARS="60000"
fi

{
  printf 'BRAIN_URL=%q\n' "$BRAIN_URL"
  printf 'BRAIN_MODEL=%q\n' "$BRAIN_MODEL"
  printf 'BRAIN_KEY=%q\n' "$BRAIN_KEY"
  printf 'BRAIN_TIMEOUT=%q\n' "$BRAIN_TIMEOUT"
  printf 'BRAIN_MAX_TOKENS=%q\n' "$BRAIN_MAX_TOKENS"
  printf 'BRAIN_CONTEXT_MAX_CHARS=%q\n' "$BRAIN_CONTEXT_MAX_CHARS"
  printf 'BRAIN_RETRIES=%q\n' "$BRAIN_RETRIES"
} >"$BRAIN_CONFIG"
chmod 600 "$BRAIN_CONFIG"

log "写入网络重试 / cooldown 参数；v1.3 2X 和安全阈值保持不变"
mkdir -p "$DROPIN_DIR"
cat >"$DROPIN" <<'EOF'
[Service]
Environment=TC_NET_RETRIES=3
Environment=TC_NET_BACKOFF_BASE_MS=1000
Environment=TC_NET_COOLDOWN_AFTER=3
Environment=TC_NET_COOLDOWN_SECONDS=900
Environment=TC_BRAIN_COOLDOWN_AFTER=3
Environment=TC_BRAIN_COOLDOWN_SECONDS=900
EOF
chmod 644 "$DROPIN"

cat >/usr/local/bin/tc-social-net <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
STATE="/opt/technocore-agent/state/social-v1.json"
BRAIN="/opt/technocore-agent/brain.env"
SERVICE="technocore-aizong-social.service"
BRAIN_TIMEOUT=""
BRAIN_RETRIES=""
[ -f "$BRAIN" ] && source "$BRAIN"
echo "===== AIZONG v1.3.1 NETWORK HEALTH ====="
echo "service=$(systemctl is-active "$SERVICE" 2>/dev/null || true)"
echo "BRAIN_TIMEOUT=${BRAIN_TIMEOUT:-60}"
echo "BRAIN_RETRIES=${BRAIN_RETRIES:-3}"
systemctl show -p Environment --value "$SERVICE" \
  | tr ' ' '\n' \
  | grep -E '^TC_(NET|BRAIN_COOLDOWN)_' \
  | sort || true
python3 - "$STATE" <<'PY'
import json
import sys
import time
from pathlib import Path

path = Path(sys.argv[1])
try:
    data = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    data = {}
health = data.get("network_health", {}) if isinstance(data, dict) else {}
now = int(time.time())
for endpoint in ("network", "brain"):
    failures = int(health.get(f"{endpoint}_consecutive_failures", 0) or 0)
    until = int(health.get(f"{endpoint}_cooldown_until", 0) or 0)
    remaining = max(0, until - now)
    last_error = str(health.get(f"{endpoint}_last_error", ""))
    print(f"{endpoint}_consecutive_failures={failures}")
    print(f"{endpoint}_cooldown_remaining={remaining}s")
    if last_error:
        print(f"{endpoint}_last_error={last_error[:240]}")
PY
EOF
chmod 755 /usr/local/bin/tc-social-net

cat >/usr/local/bin/tc-brain-test <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
FILE="/opt/technocore-agent/brain.env"
[ "$(id -u)" = "0" ] || { echo "ERROR: run as root" >&2; exit 1; }
[ -f "$FILE" ] || { echo "ERROR: brain.env not found" >&2; exit 1; }
BRAIN_URL=""
BRAIN_MODEL=""
BRAIN_KEY=""
BRAIN_TIMEOUT="60"
BRAIN_MAX_TOKENS="1536"
BRAIN_RETRIES="3"
# shellcheck disable=SC1090
source "$FILE"
[ -n "$BRAIN_URL" ] || { echo "Brain test: FAIL (URL not configured)"; exit 1; }
[ -n "$BRAIN_MODEL" ] || { echo "Brain test: FAIL (model not configured)"; exit 1; }
export BRAIN_URL BRAIN_MODEL BRAIN_KEY BRAIN_TIMEOUT BRAIN_MAX_TOKENS BRAIN_RETRIES
python3 <<'PY'
import json
import os
import sys
import time
import urllib.error
import urllib.request

url = os.environ["BRAIN_URL"]
model = os.environ["BRAIN_MODEL"]
key = os.environ.get("BRAIN_KEY", "")
try:
    base_timeout = min(max(int(os.environ.get("BRAIN_TIMEOUT", "60")), 15), 120)
except ValueError:
    base_timeout = 60
try:
    attempts = min(max(int(os.environ.get("BRAIN_RETRIES", "3")), 1), 3)
except ValueError:
    attempts = 3
try:
    production_budget = min(max(int(os.environ.get("BRAIN_MAX_TOKENS", "1536")), 256), 4096)
except ValueError:
    production_budget = 1536
# A connectivity probe does not need the full production completion budget.
test_budget = min(production_budget, 512)
payload = {
    "model": model,
    "messages": [
        {
            "role": "system",
            "content": "Connectivity test. Give only the requested final answer; no explanation.",
        },
        {"role": "user", "content": "Reply with exactly AIZONG_BRAIN_OK"},
    ],
    "temperature": 0,
    "max_tokens": test_budget,
}
headers = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "aizong-brain-test/1.3.1",
}
if key:
    headers["Authorization"] = f"Bearer {key}"
request = urllib.request.Request(
    url,
    data=json.dumps(payload).encode(),
    method="POST",
    headers=headers,
)
print(f"Brain endpoint: {url}")
print(f"Model: {model}")
print(f"Production completion budget: {production_budget}")
print(f"Probe completion budget: {test_budget}")
raw = None
last = None
transient = {408, 425, 429, 500, 502, 503, 504}
for attempt in range(1, attempts + 1):
    timeout = min(base_timeout + (attempt - 1) * 15, 120)
    print(f"Attempt: {attempt}/{attempts} timeout={timeout}s")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
        break
    except urllib.error.HTTPError as exc:
        if exc.code not in transient:
            print(f"Brain test: FAIL (HTTP {exc.code})")
            sys.exit(2)
        last = f"HTTP {exc.code}"
    except urllib.error.URLError as exc:
        last = f"network: {exc.reason}"
    except TimeoutError:
        last = "timeout"
    if attempt < attempts:
        delay = 2 ** (attempt - 1)
        print(f"Transient failure: {last}; retry in {delay}s")
        time.sleep(delay)
if raw is None:
    print(f"Brain test: FAIL ({last or 'transport error'} after {attempts} attempts)")
    sys.exit(4)
try:
    data = json.loads(raw)
    choice = data["choices"][0]
    message = choice["message"]
    content = message.get("content", "")
    finish = choice.get("finish_reason")
    reasoning = message.get("reasoning_content")
except (json.JSONDecodeError, KeyError, IndexError, TypeError):
    print("Brain test: FAIL (response is not OpenAI chat-completions compatible)")
    sys.exit(5)
text = " ".join(str(content).split())[:240]
print(f"Finish reason: {finish}")
if reasoning is not None:
    print("Reasoning channel: present")
print(f"Response: {text}")
if "AIZONG_BRAIN_OK" in text:
    print("Brain test: PASS")
    sys.exit(0)
if text:
    print("Brain test: WARN (endpoint/auth/model responded; marker differed or was truncated)")
    sys.exit(0)
print("Brain test: WARN (endpoint responded but final content was empty)")
PY
EOF
chmod 755 /usr/local/bin/tc-brain-test

log "回归检查"
python3 "$PROGRAM" --version
tc-social-limits || true
tc-social-net

log "重载并启动 24/7 服务"
systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null
systemctl restart "$SERVICE"
sleep 2
systemctl is-active --quiet "$SERVICE" || {
  systemctl --no-pager --full status "$SERVICE" || true
  die "aizong Social v1.3.1 服务启动失败"
}

cat <<'EOF'

============================================================
 AIZONG SOCIAL BRAIN v1.3.1 NETWORK RESILIENCE READY
============================================================
Transport resilience:
  Technocore GET retries:       3
  Retry backoff:                ~1s -> 2s -> 4s
  Brain retries:                3
  Brain base timeout:           >=60s
  Brain retry timeout growth:   +15s / retry (max 120s)
  Network cooldown:             3 failures -> 15 min
  Brain cooldown:               3 failures -> 15 min

Fail-safe behavior:
  - one room failure does not abort other rooms
  - Brain transport failure defers the action to a later cycle
  - Brain failure does NOT emit a generic public reply
  - signed public POST is NOT blindly retried (duplicate-write safety)
  - daemon remains 24/7 and recovers on later cycles

Preserved from v1.3.0:
  - 10 rooms / 40 messages per room
  - 6 writes/hour / 24 writes/day / 12 follow-ups
  - 16-message Brain context / 1536+ completion budget / 60000-char ceiling
  - DID / private key / mailbox / API key / contacts / memory / write history
  - all prompt-injection / scam / bot+spam safety gates unchanged

Commands:
  tc-social-net
  tc-brain-test
  tc-social-limits
  tc-social-stats
  tc-social-log 100
============================================================
EOF
