#!/usr/bin/env bash
set -Eeuo pipefail

# aizong Social Brain v1.1.1 compatibility repair.
# - accepts an OpenAI-compatible base URL ending in /v1 and normalizes it to /chat/completions
# - preserves the existing API key and social/DID state
# - installs tc-brain-test so model connectivity can be verified without a Technocore write

AGENT_DIR="/opt/technocore-agent"
BRAIN_CONFIG="$AGENT_DIR/brain.env"
SERVICE="technocore-aizong-social.service"

log() { printf '\n[+] %s\n' "$*"; }
die() { printf '\n[x] %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "请用 root 执行"
[ -f "$BRAIN_CONFIG" ] || die "找不到 $BRAIN_CONFIG；请先安装 aizong Social v1.1 Brain"
command -v python3 >/dev/null || die "python3 未安装"

normalize_url() {
  local url="${1%/}"
  case "$url" in
    */v1) printf '%s/chat/completions\n' "$url" ;;
    *) printf '%s\n' "$url" ;;
  esac
}

BRAIN_URL=""
BRAIN_MODEL=""
BRAIN_KEY=""
BRAIN_TIMEOUT="25"
BRAIN_MAX_TOKENS="220"
# shellcheck disable=SC1090
source "$BRAIN_CONFIG"

if [ -n "$BRAIN_URL" ]; then
  OLD_URL="$BRAIN_URL"
  BRAIN_URL="$(normalize_url "$BRAIN_URL")"
  if [ "$OLD_URL" != "$BRAIN_URL" ]; then
    log "Brain URL 已自动规范化"
    printf '  %s\n' "$BRAIN_URL"
  fi
fi

{
  printf 'BRAIN_URL=%q\n' "$BRAIN_URL"
  printf 'BRAIN_MODEL=%q\n' "$BRAIN_MODEL"
  printf 'BRAIN_KEY=%q\n' "$BRAIN_KEY"
  printf 'BRAIN_TIMEOUT=%q\n' "$BRAIN_TIMEOUT"
  printf 'BRAIN_MAX_TOKENS=%q\n' "$BRAIN_MAX_TOKENS"
} >"$BRAIN_CONFIG"
chmod 600 "$BRAIN_CONFIG"

cat >/usr/local/bin/tc-brain-config <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail

FILE="/opt/technocore-agent/brain.env"
SERVICE="technocore-aizong-social.service"
BRAIN_URL=""
BRAIN_MODEL=""
BRAIN_KEY=""
BRAIN_TIMEOUT="25"
BRAIN_MAX_TOKENS="220"

normalize_url() {
  local url="${1%/}"
  case "$url" in
    */v1) printf '%s/chat/completions\n' "$url" ;;
    *) printf '%s\n' "$url" ;;
  esac
}

if [ -f "$FILE" ]; then
  # shellcheck disable=SC1090
  source "$FILE"
fi

printf '\nConfigure aizong Social Brain\n'
printf 'OpenAI-compatible /v1 base URL or full /chat/completions URL are both accepted.\n\n'

read -r -p "Brain API URL/base [$BRAIN_URL]: " NEW_URL
BRAIN_URL="${NEW_URL:-$BRAIN_URL}"
BRAIN_URL="$(normalize_url "$BRAIN_URL")"
read -r -p "Model [$BRAIN_MODEL]: " NEW_MODEL
BRAIN_MODEL="${NEW_MODEL:-$BRAIN_MODEL}"
read -r -s -p "API key [Enter keeps existing]: " NEW_KEY
printf '\n'
if [ -n "$NEW_KEY" ]; then
  BRAIN_KEY="$NEW_KEY"
fi

case "$BRAIN_URL" in
  http://*|https://*) ;;
  *) echo "ERROR: Brain API URL must start with http:// or https://" >&2; exit 1 ;;
esac
[ -n "$BRAIN_MODEL" ] || { echo "ERROR: model is required" >&2; exit 1; }

{
  printf 'BRAIN_URL=%q\n' "$BRAIN_URL"
  printf 'BRAIN_MODEL=%q\n' "$BRAIN_MODEL"
  printf 'BRAIN_KEY=%q\n' "$BRAIN_KEY"
  printf 'BRAIN_TIMEOUT=%q\n' "$BRAIN_TIMEOUT"
  printf 'BRAIN_MAX_TOKENS=%q\n' "$BRAIN_MAX_TOKENS"
} >"$FILE"
chmod 600 "$FILE"
systemctl restart "$SERVICE"
printf '\nBrain configured and social service restarted.\n'
printf 'Endpoint: %s\n' "$BRAIN_URL"
printf 'API key is root-only and hidden. Run tc-brain-test next.\n'
EOF

cat >/usr/local/bin/tc-brain-test <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
FILE="/opt/technocore-agent/brain.env"
[ "$(id -u)" = "0" ] || { echo "ERROR: run as root" >&2; exit 1; }
[ -f "$FILE" ] || { echo "ERROR: brain.env not found" >&2; exit 1; }
BRAIN_URL=""
BRAIN_MODEL=""
BRAIN_KEY=""
BRAIN_TIMEOUT="25"
# shellcheck disable=SC1090
source "$FILE"
[ -n "$BRAIN_URL" ] || { echo "Brain test: FAIL (URL not configured)"; exit 1; }
[ -n "$BRAIN_MODEL" ] || { echo "Brain test: FAIL (model not configured)"; exit 1; }
export BRAIN_URL BRAIN_MODEL BRAIN_KEY BRAIN_TIMEOUT
python3 <<'PY'
import json
import os
import sys
import urllib.error
import urllib.request

url = os.environ["BRAIN_URL"]
model = os.environ["BRAIN_MODEL"]
key = os.environ.get("BRAIN_KEY", "")
try:
    timeout = min(max(int(os.environ.get("BRAIN_TIMEOUT", "25")), 5), 60)
except ValueError:
    timeout = 25
payload = {
    "model": model,
    "messages": [
        {"role": "system", "content": "You are a connectivity test. Follow the user's request."},
        {"role": "user", "content": "Reply with exactly: AIZONG_BRAIN_OK"},
    ],
    "temperature": 0,
    "max_tokens": 32,
}
headers = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "aizong-brain-test/1.1.1",
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
try:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
except urllib.error.HTTPError as exc:
    print(f"Brain test: FAIL (HTTP {exc.code})")
    sys.exit(2)
except urllib.error.URLError as exc:
    print(f"Brain test: FAIL (network: {exc.reason})")
    sys.exit(3)
except TimeoutError:
    print("Brain test: FAIL (timeout)")
    sys.exit(4)
try:
    data = json.loads(raw)
    content = data["choices"][0]["message"]["content"]
except (json.JSONDecodeError, KeyError, IndexError, TypeError):
    print("Brain test: FAIL (response is not OpenAI chat-completions compatible)")
    sys.exit(5)
text = " ".join(str(content).split())[:160]
print(f"Response: {text}")
if "AIZONG_BRAIN_OK" not in text:
    print("Brain test: WARN (request worked, but model did not return the expected marker)")
    sys.exit(0)
print("Brain test: PASS")
PY
EOF

chmod 755 /usr/local/bin/tc-brain-config /usr/local/bin/tc-brain-test
systemctl restart "$SERVICE"

log "aizong Brain v1.1.1 compatibility patch installed"
printf 'Brain URL: %s\n' "$BRAIN_URL"
printf 'Model:     %s\n' "$BRAIN_MODEL"
printf 'Key:       %s\n' "$([ -n "$BRAIN_KEY" ] && echo 'configured (hidden)' || echo 'empty')"
printf '\nRun now:\n  tc-brain-test\n'
