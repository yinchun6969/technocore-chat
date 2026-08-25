#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="2.2.2"
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
[[ -s "$RUNNER" ]] || die "找不到 $RUNNER"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$SOCIAL/backups/v2.2.2-fix-$TS"
mkdir -p "$BACKUP"
cp -a "$COMPAT" "$CFG" "$RUNNER" "$BACKUP/" 2>/dev/null || true

log "下载 Love8 Brain v$VERSION timeout adapter"
curl -fsSL "$REPO_RAW/scripts/love8_brain_compat.py" -o "$TMP/love8_brain_compat.py"
python3 -m py_compile "$TMP/love8_brain_compat.py"
grep -q 'VERSION = "2.2.2"' "$TMP/love8_brain_compat.py" || die "compat 版本检查失败"
install -m 700 "$TMP/love8_brain_compat.py" "$COMPAT"

# 1M context is an input-window capability; max_tokens is OUTPUT budget.
# Keep input curated for latency, while giving reasoning models enough output/time.
for kv in 'BRAIN_TIMEOUT=150' 'BRAIN_RETRIES=1' 'BRAIN_MAX_TOKENS=2200'; do
  key="${kv%%=*}"; val="${kv#*=}"
  if grep -q "^${key}=" "$CFG"; then
    sed -i "s/^${key}=.*/${key}=${val}/" "$CFG"
  else
    printf '%s\n' "$kv" >>"$CFG"
  fi
done
chmod 600 "$CFG"

# Install helpers BEFORE any online diagnostic, so a slow provider never leaves
# the user without recovery/diagnostic commands.
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
set +e
source /opt/love8-agent/social/brain.env
printf '===== LOVE8 BRAIN DIAG =====\n'
printf 'Model: %s\n' "$BRAIN_MODEL"
printf 'API: %s\n' "$BRAIN_API_BASE"
printf 'Timeout: %ss\n' "${BRAIN_TIMEOUT:-150}"
printf 'Retries: %s\n' "${BRAIN_RETRIES:-1}"
printf 'Output max_tokens: %s\n' "${BRAIN_MAX_TOKENS:-2200}"
printf 'API key: [hidden]\n\n'
/usr/bin/python3 /opt/love8-agent/social/love8_brain_runner.py --self-test
rc=$?
printf '\nRecent brain log:\n'
tail -n 30 /var/log/love8-brain-v22.log 2>/dev/null || true
exit $rc
EOF
chmod 755 /usr/local/bin/love8-brain-diagnose

cat >/usr/local/bin/love8-brain-context <<'EOF'
#!/usr/bin/env python3
import importlib.util
from pathlib import Path
root=Path('/opt/love8-agent/social')
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
b=load('brain_context',root/'love8_brain.py'); g=b.load_guard()
cfg={**b.load_env(root/'config.env'),**b.load_env(root/'brain.env')}
st=g.load_state(Path('/opt/love8-agent/state/social-v2.json'))
candidates,digest=b.collect_candidates(g,cfg,st)
payload=b.decision_payload(candidates,digest)
raw=len(payload.encode('utf-8'))
print('===== LOVE8 BRAIN CONTEXT =====')
print('candidates:',len(candidates))
print('rooms:',len(digest))
print('payload_bytes:',raw)
print('rough_tokens:',max(1,raw//4))
print('note: model context window is an upper limit, not a target; curated context reduces latency and cost.')
EOF
chmod 755 /usr/local/bin/love8-brain-context

log "v$VERSION 已安装；先显示上下文大小"
love8-brain-version
love8-brain-context || true

log "在线自检：现在允许单次读取最多 150 秒，并在超时时重试 1 次"
if /usr/bin/python3 "$RUNNER" --self-test; then
  echo '[+] Brain online self-test OK'
else
  warn "模型端仍然较慢/异常；v2.2.2 已保持 fail-closed，cron 不会乱发消息。"
  warn "可稍后执行 love8-brain-diagnose 重试，不需要再次安装。"
fi

log "真实房间 dry-run（不发送消息）"
if /usr/bin/python3 "$RUNNER" --once --dry-run; then
  echo '[+] Brain dry-run OK'
else
  warn "dry-run 未完成；已保留 v2.2.2 与诊断命令，自动运行仍是 fail-closed。"
fi

cat <<'EOF'

============================================================
 LOVE8 BRAIN v2.2.2 READY
============================================================
Fixed:
  - read timeout 45/60s -> configurable 150s
  - timeout retry: 1 bounded retry
  - timeout最终失败时 observe-only，不崩溃、不发消息
  - helper commands 先安装，诊断失败也不会 command not found
  - max_tokens=2200 是输出预算，不是输入上下文大小
  - 保持精选上下文；1M context 是上限，不需要为了“聪明”硬塞满

Commands:
  love8-brain-version
  love8-brain-context
  love8-brain-diagnose
  love8-brain-dry-run
  love8-brain-run-now
  love8-brain-memory
============================================================
EOF
