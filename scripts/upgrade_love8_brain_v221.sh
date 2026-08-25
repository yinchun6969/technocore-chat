#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="2.2.1"
REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/yinchun6969/technocore-chat/love8-social-v2}"
ROOT="/opt/love8-agent"
SOCIAL="$ROOT/social"
CFG="$SOCIAL/brain.env"
BRAIN="$SOCIAL/love8_brain.py"
RUNNER="$SOCIAL/love8_brain_runner.py"
COMPAT="$SOCIAL/love8_brain_compat.py"
LOG="/var/log/love8-brain-v22.log"

log(){ printf '\n[+] %s\n' "$*"; }
warn(){ printf '\n[!] %s\n' "$*"; }
die(){ printf '\n[x] %s\n' "$*" >&2; exit 1; }

[[ ${EUID:-$(id -u)} -eq 0 ]] || die "请用 root 执行"
[[ -s "$CFG" ]] || die "找不到 $CFG；请先完成 Love8 Brain v2.2 配置"
[[ -s "$BRAIN" ]] || die "找不到 $BRAIN"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$SOCIAL/backups/v2.2.1-fix-$TS"
mkdir -p "$BACKUP"
cp -a "$RUNNER" "$COMPAT" "$CFG" "$BACKUP/" 2>/dev/null || true

log "下载 Love8 Brain API compatibility v$VERSION"
curl -fsSL "$REPO_RAW/scripts/love8_brain_runner.py" -o "$TMP/love8_brain_runner.py"
curl -fsSL "$REPO_RAW/scripts/love8_brain_compat.py" -o "$TMP/love8_brain_compat.py"
python3 -m py_compile "$TMP/love8_brain_runner.py" "$TMP/love8_brain_compat.py"
grep -q 'v2.2.1' "$TMP/love8_brain_runner.py" || die "runner 版本检查失败"
grep -q 'VERSION = "2.2.1"' "$TMP/love8_brain_compat.py" || die "compat 版本检查失败"

install -m 700 "$TMP/love8_brain_runner.py" "$RUNNER"
install -m 700 "$TMP/love8_brain_compat.py" "$COMPAT"

# Reasoning-style models can consume 700 tokens before writing final content.
# Preserve every secret/config value; only raise the completion budget.
if grep -q '^BRAIN_MAX_TOKENS=' "$CFG"; then
  sed -i 's/^BRAIN_MAX_TOKENS=.*/BRAIN_MAX_TOKENS=1800/' "$CFG"
else
  printf '\nBRAIN_MAX_TOKENS=1800\n' >>"$CFG"
fi
chmod 600 "$CFG"

log "模型兼容性自检：支持 content / reasoning_content / choices.text / output_text"
python3 "$RUNNER" --self-test || die "Brain self-test 失败"

log "检查模型是否真的返回了可解析 JSON（不发送 Technocore 消息）"
python3 - <<'PY'
import importlib.util, json
from pathlib import Path
root=Path('/opt/love8-agent/social')

def load(name,path):
    s=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
brain=load('brain_diag',root/'love8_brain.py')
brain.guard=brain.load_guard()
compat=load('compat_diag',root/'love8_brain_compat.py')
brain.chat=compat.make_chat(brain)
cfg=brain.load_env(root/'brain.env')
payload=json.dumps({'task':'Compatibility diagnostic. Return observe and no reply.','candidates':[],'room_digest':{'test':['plain harmless diagnostic']}})
raw=brain.chat(cfg,payload,timeout=60)
if raw.get('_compat_empty_fallback'):
    raise SystemExit('DIAG FAIL: provider still returned no parseable final JSON')
print('BRAIN v2.2.1 DIAG OK')
print('response_source:', raw.get('_compat_source','standard content'))
print('retry_used:', bool(raw.get('_compat_retry',False)))
PY

log "真实房间 dry-run：会调用模型分析，但绝不发消息"
python3 "$RUNNER" --once --dry-run || die "Brain dry-run 失败"

cat >/usr/local/bin/love8-brain-version <<'EOF'
#!/usr/bin/env bash
python3 /opt/love8-agent/social/love8_brain.py --version 2>/dev/null || true
python3 - <<'PY'
import importlib.util
p='/opt/love8-agent/social/love8_brain_compat.py'
s=importlib.util.spec_from_file_location('c',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
print('love8_brain_compat.py',m.VERSION)
PY
EOF
chmod 755 /usr/local/bin/love8-brain-version

cat >/usr/local/bin/love8-brain-diagnose <<'EOF'
#!/usr/bin/env bash
set -e
python3 /opt/love8-agent/social/love8_brain_runner.py --self-test
echo
echo 'Recent brain log:'
tail -n 30 /var/log/love8-brain-v22.log 2>/dev/null || true
EOF
chmod 755 /usr/local/bin/love8-brain-diagnose

cat <<'EOF'

============================================================
 LOVE8 BRAIN v2.2.1 API COMPAT FIX READY
============================================================
Fixed:
  - message.content 为空时读取 reasoning_content
  - 支持 choices[].text / output_text 等兼容返回
  - reasoning 模型首轮只思考不输出时自动重试一次
  - completion budget 700 -> 1800
  - 仍无有效结果时 fail-closed: observe，绝不乱发消息
  - URL / API Key / Model 全部保持原配置，不需要重新输入 Key

Commands:
  love8-brain-version
  love8-brain-diagnose
  love8-brain-dry-run
  love8-brain-run-now
  love8-brain-memory
============================================================
EOF
love8-brain-version
