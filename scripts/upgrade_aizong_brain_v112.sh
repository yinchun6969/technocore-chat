#!/usr/bin/env bash
set -Eeuo pipefail

# aizong Social Brain v1.1.2 reasoning-model compatibility patch.
# Preserves DID, mailbox, contacts, write budget and API key.

AGENT_DIR="/opt/technocore-agent"
BRAIN_CONFIG="$AGENT_DIR/brain.env"
PROGRAM="$AGENT_DIR/aizong_social.py"
SERVICE="technocore-aizong-social.service"

log() { printf '\n[+] %s\n' "$*"; }
die() { printf '\n[x] %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "请用 root 执行"
[ -f "$BRAIN_CONFIG" ] || die "找不到 $BRAIN_CONFIG"
[ -f "$PROGRAM" ] || die "找不到 $PROGRAM"

BRAIN_URL=""
BRAIN_MODEL=""
BRAIN_KEY=""
BRAIN_TIMEOUT="25"
BRAIN_MAX_TOKENS="220"
# shellcheck disable=SC1090
source "$BRAIN_CONFIG"

# Reasoning-capable models may consume part of the completion budget before
# emitting the final compact JSON. Keep the public reply cap in the Python
# client, but give the model enough completion room to finish its JSON object.
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

# The original v1.1 client clamped BRAIN_MAX_TOKENS at 500. Raise only that
# internal ceiling; the emitted public message remains capped at 500 chars.
PROGRAM="$PROGRAM" python3 <<'PY'
import os
from pathlib import Path

path = Path(os.environ["PROGRAM"])
text = path.read_text(encoding="utf-8")
old = 'max_tokens = min(max(int(brain.get("BRAIN_MAX_TOKENS", "220")), 80), 500)'
new = 'max_tokens = min(max(int(brain.get("BRAIN_MAX_TOKENS", "768")), 128), 2048)'
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit("unknown Brain max-token source shape; refusing to patch")
text = text.replace('VERSION = "1.1.0"', 'VERSION = "1.1.2"', 1)
text = text.replace('Social v1.1.0', 'Social v1.1.2', 1)
path.write_text(text, encoding="utf-8")
PY
python3 -m py_compile "$PROGRAM"
chmod 700 "$PROGRAM"

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
BRAIN_MAX_TOKENS="768"
# shellcheck disable=SC1090
source "$FILE"
[ -n "$BRAIN_URL" ] || { echo "Brain test: FAIL (URL not configured)"; exit 1; }
[ -n "$BRAIN_MODEL" ] || { echo "Brain test: FAIL (model not configured)"; exit 1; }
export BRAIN_URL BRAIN_MODEL BRAIN_KEY BRAIN_TIMEOUT BRAIN_MAX_TOKENS
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
try:
    configured = int(os.environ.get("BRAIN_MAX_TOKENS", "768"))
except ValueError:
    configured = 768
max_tokens = min(max(configured, 256), 2048)
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
    "max_tokens": max_tokens,
}
headers = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "aizong-brain-test/1.1.2",
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
print(f"Completion budget: {max_tokens}")
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
if text and "AIZONG_BRAIN_OK".startswith(text.replace(" ", "")):
    print("Brain test: WARN (endpoint/auth/model OK, final answer was truncated)")
    sys.exit(0)
print("Brain test: WARN (endpoint/auth/model responded, marker differed)")
PY
EOF
chmod 755 /usr/local/bin/tc-brain-test

systemctl restart "$SERVICE"

log "aizong Brain v1.1.2 reasoning-model patch installed"
printf 'Brain URL:          %s\n' "$BRAIN_URL"
printf 'Model:              %s\n' "$BRAIN_MODEL"
printf 'Completion budget:  %s\n' "$BRAIN_MAX_TOKENS"
printf 'Key:                %s\n' "$([ -n "$BRAIN_KEY" ] && echo 'configured (hidden)' || echo 'empty')"
printf '\nRun now:\n  tc-brain-test\n'
