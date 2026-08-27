#!/usr/bin/env bash
set -Eeuo pipefail
VERSION="2.4.2"
RAW="${REPO_RAW:-https://raw.githubusercontent.com/yinchun6969/technocore-chat/love8-social-v2}"
ROOT="/opt/love8-agent"; SOCIAL="$ROOT/social"; STATE="$ROOT/state"; MEMORY="$ROOT/memory"
CRON="/etc/cron.d/love8-social-v2"; PAUSE="$STATE/social-v2.paused"
log(){ printf '\n[+] %s\n' "$*"; }
warn(){ printf '\n[!] %s\n' "$*"; }
die(){ printf '\n[x] %s\n' "$*" >&2; exit 1; }
[[ ${EUID:-$(id -u)} -eq 0 ]] || die "请用 root 执行"
[[ -s "$SOCIAL/love8_persistent_v240_core.py" ]] || die "缺少 v2.4 core；请先安装 v2.4.1"
[[ -s "$SOCIAL/love8_memory_v241.py" ]] || die "缺少 v2.4.1 permanent memory"
[[ -s "$SOCIAL/love8_brain.py" ]] || die "缺少 Brain Core"
[[ -s "$SOCIAL/love8_brain_compat.py" ]] || die "缺少 Brain compatibility layer"
[[ -s "$SOCIAL/config.env" && -s "$SOCIAL/brain.env" ]] || die "缺少 Love8 配置"
mkdir -p "$SOCIAL/backups" "$STATE" "$MEMORY"
TS="$(date -u +%Y%m%dT%H%M%SZ)"; BAK="$SOCIAL/backups/v2.4.2-$TS"; mkdir -p "$BAK"
cp -a "$SOCIAL/love8_persistent.py" "$SOCIAL/love8_brain_runner.py" "$SOCIAL/brain.env" "$SOCIAL/persistent.env" "$CRON" "$BAK/" 2>/dev/null || true
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
FILES=(love8_attention_v242.py love8_relationship_v242.py love8_memory_v242.py love8_brain_v242_overlay.py love8_deep_rooms_v242.py love8_persistent_v242_wrapper.py love8_brain_runner_v242.py test_love8_persistent_v242.py)
log "下载 Love8 v2.4.2 Relationship + Attention + Deep Room 模块"
for f in "${FILES[@]}"; do curl -fsSL "$RAW/scripts/$f" -o "$TMP/$f"; done
python3 -m py_compile "$TMP"/*.py
python3 "$TMP/test_love8_persistent_v242.py"
grep -q 'VERSION="2.4.2"' "$TMP/love8_attention_v242.py" || die "attention version mismatch"
grep -q 'VERSION="2.4.2"' "$TMP/love8_memory_v242.py" || die "memory version mismatch"

log "安装 v2.4.2 运行模块"
install -m 700 "$TMP/love8_attention_v242.py" "$SOCIAL/love8_attention_v242.py"
install -m 700 "$TMP/love8_relationship_v242.py" "$SOCIAL/love8_relationship_v242.py"
install -m 700 "$TMP/love8_memory_v242.py" "$SOCIAL/love8_memory_v242.py"
install -m 700 "$TMP/love8_brain_v242_overlay.py" "$SOCIAL/love8_brain_v242_overlay.py"
install -m 700 "$TMP/love8_deep_rooms_v242.py" "$SOCIAL/love8_deep_rooms_v242.py"
install -m 700 "$TMP/love8_persistent_v242_wrapper.py" "$SOCIAL/love8_persistent.py"
install -m 700 "$TMP/love8_brain_runner_v242.py" "$SOCIAL/love8_brain_runner.py"

log "策略调整：12次/小时思考；增加深聊余量；16候选中固定保留6个 discovery slots"
python3 - "$SOCIAL/brain.env" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]);lines=p.read_text().splitlines();updates={"BRAIN_CALLS_PER_HOUR":"12","BRAIN_PUBLIC_HOURLY_WRITES":"8","BRAIN_PUBLIC_DAILY_WRITES":"28","BRAIN_DISCOVERY_RESERVE":"6","BRAIN_CANDIDATES":"16","BRAIN_ROOMS":"12"};out=[];seen=set()
for line in lines:
    if "=" in line and not line.lstrip().startswith("#"):
        k=line.split("=",1)[0].strip()
        if k in updates:out.append(f"{k}={updates[k]}");seen.add(k);continue
    out.append(line)
for k,v in updates.items():
    if k not in seen:out.append(f"{k}={v}")
p.write_text("\n".join(out)+"\n")
PY
chmod 600 "$SOCIAL/brain.env"
python3 - "$SOCIAL/persistent.env" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]);lines=p.read_text().splitlines() if p.exists() else [];updates={"PERSIST_DEEP_TOPIC_MIN":"2.5","PERSIST_DEEP_ROOMS_PER_DAY":"2","PERSIST_DEEP_MIN_A2A_PEERS":"2","PERSIST_ROOM_ANCHOR_ENABLED":"yes","PERSIST_ANCHOR_ROOM":"love8-provenance","PERSIST_MEMORY_AUTO_PRUNE":"no"};out=[];seen=set()
for line in lines:
    if "=" in line and not line.lstrip().startswith("#"):
        k=line.split("=",1)[0].strip()
        if k in updates:out.append(f"{k}={updates[k]}");seen.add(k);continue
    out.append(line)
for k,v in updates.items():
    if k not in seen:out.append(f"{k}={v}")
p.write_text("\n".join(out)+"\n")
PY
chmod 600 "$SOCIAL/persistent.env"

log "安装管理命令"
cat >/usr/local/bin/love8-attention-status <<'EOF'
#!/usr/bin/env bash
exec python3 /opt/love8-agent/social/love8_attention_v242.py --status
EOF
cat >/usr/local/bin/love8-attention-refresh <<'EOF'
#!/usr/bin/env bash
exec /usr/bin/flock -n /run/lock/love8-attention-v242.lock python3 /opt/love8-agent/social/love8_attention_v242.py --build --limit 160
EOF
cat >/usr/local/bin/love8-reply-attribution-status <<'EOF'
#!/usr/bin/env bash
exec python3 /opt/love8-agent/social/love8_relationship_v242.py --status
EOF
cat >/usr/local/bin/love8-reply-attribution-run-now <<'EOF'
#!/usr/bin/env bash
exec /usr/bin/flock -n /run/lock/love8-relation-v242.lock python3 /opt/love8-agent/social/love8_relationship_v242.py --once
EOF
cat >/usr/local/bin/love8-deep-rooms-status <<'EOF'
#!/usr/bin/env bash
exec python3 /opt/love8-agent/social/love8_deep_rooms_v242.py --status
EOF
cat >/usr/local/bin/love8-deep-rooms-run-now <<'EOF'
#!/usr/bin/env bash
exec /usr/bin/flock -n /run/lock/love8-deep-v242.lock python3 /opt/love8-agent/social/love8_deep_rooms_v242.py --once
EOF
cat >/usr/local/bin/love8-deep-rooms-dry-run <<'EOF'
#!/usr/bin/env bash
exec /usr/bin/flock -n /run/lock/love8-deep-v242.lock python3 /opt/love8-agent/social/love8_deep_rooms_v242.py --once --dry-run
EOF
cat >/usr/local/bin/love8-a2a-peers-import <<'EOF'
#!/usr/bin/env bash
exec python3 /opt/love8-agent/social/love8_deep_rooms_v242.py --import-peers
EOF
cat >/usr/local/bin/love8-a2a-peer-add <<'EOF'
#!/usr/bin/env bash
[[ $# -ge 2 ]] || { echo 'usage: love8-a2a-peer-add NAME DID [MAILBOX]'; exit 2; }
exec python3 /opt/love8-agent/social/love8_deep_rooms_v242.py --add-peer "$@"
EOF
cat >/usr/local/bin/love8-a2a-peers-status <<'EOF'
#!/usr/bin/env bash
exec python3 /opt/love8-agent/social/love8_deep_rooms_v242.py --status
EOF
cat >/usr/local/bin/love8-memory-status <<'EOF'
#!/usr/bin/env bash
exec python3 /opt/love8-agent/social/love8_memory_v242.py --status
EOF
cat >/usr/local/bin/love8-memory-verify <<'EOF'
#!/usr/bin/env bash
exec python3 /opt/love8-agent/social/love8_memory_v242.py --verify
EOF
cat >/usr/local/bin/love8-persistent-version <<'EOF'
#!/usr/bin/env bash
python3 /opt/love8-agent/social/love8_persistent.py --version
python3 /opt/love8-agent/social/love8_memory_v242.py --version
echo 'brain_runner 2.4.2 attention-aware'
EOF
cat >/usr/local/bin/love8-v242-status <<'EOF'
#!/usr/bin/env bash
echo '===== LOVE8 v2.4.2 ====='
love8-persistent-version 2>/dev/null || true
echo; love8-attention-status
echo; love8-reply-attribution-status
echo; love8-deep-rooms-status
echo; love8-memory-status
EOF
chmod 755 /usr/local/bin/love8-v242-status /usr/local/bin/love8-attention-* /usr/local/bin/love8-reply-attribution-* /usr/local/bin/love8-deep-rooms-* /usr/local/bin/love8-a2a-* /usr/local/bin/love8-memory-status /usr/local/bin/love8-memory-verify /usr/local/bin/love8-persistent-version

log "更新 cron：5分钟 Reply Attribution；15分钟 Attention；20分钟 A2A Deep Room"
python3 - "$CRON" "$PAUSE" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]);pause=sys.argv[2];lines=p.read_text().splitlines() if p.exists() else [];markers=("love8_relationship_v242.py","love8_attention_v242.py","love8_deep_rooms_v242.py");out=[x for x in lines if not any(m in x for m in markers)]
out.append(f"1-56/5 * * * * root test -f {pause} || /usr/bin/flock -n /run/lock/love8-relation-v242.lock /usr/bin/python3 /opt/love8-agent/social/love8_relationship_v242.py --once >>/var/log/love8-relation-v242.log 2>&1")
out.append(f"3,18,33,48 * * * * root test -f {pause} || /usr/bin/flock -n /run/lock/love8-attention-v242.lock /usr/bin/python3 /opt/love8-agent/social/love8_attention_v242.py --build --limit 160 >>/var/log/love8-attention-v242.log 2>&1")
out.append(f"7,27,47 * * * * root test -f {pause} || /usr/bin/flock -n /run/lock/love8-deep-v242.lock /usr/bin/python3 /opt/love8-agent/social/love8_deep_rooms_v242.py --once >>/var/log/love8-deep-v242.log 2>&1")
p.write_text("\n".join(out)+"\n")
PY
chmod 644 "$CRON";touch /var/log/love8-relation-v242.log /var/log/love8-attention-v242.log /var/log/love8-deep-v242.log;chmod 640 /var/log/love8-relation-v242.log /var/log/love8-attention-v242.log /var/log/love8-deep-v242.log

log "建立 Working Set + 首轮 Reply Attribution"
python3 "$SOCIAL/love8_attention_v242.py" --build --limit 160
python3 "$SOCIAL/love8_relationship_v242.py" --once || warn "首轮暂未找到可归因回复"
log "迁移永久记忆策略：旧 journal 一条不删，只建立 semantic baseline"
python3 "$SOCIAL/love8_memory_v242.py" --sync
log "验证永久 Memory Hash Chain（历史很多时可能需要一点时间）"
python3 "$SOCIAL/love8_memory_v242.py" --verify || die "永久记忆链验证失败"

log "自动导入现有 Agent2Agent peers：只读取 DID/mailbox，跳过 key/secret 文件"
python3 "$SOCIAL/love8_deep_rooms_v242.py" --import-peers || true
log "Deep Room dry-run"
python3 "$SOCIAL/love8_deep_rooms_v242.py" --once --dry-run || warn "本轮暂无建房候选"
log "满足条件时直接创建第一间 p- 深聊房间并发送 signed mailbox 邀请"
python3 "$SOCIAL/love8_deep_rooms_v242.py" --once || warn "本轮没有满足建房条件；cron 会继续观察"

cat <<'EOF'

================================================================
 LOVE8 v2.4.2 RELATIONSHIP / ATTENTION / A2A DEEP CHAT READY
================================================================
Reply Attribution:
  只在目标 DID 于同一 room、Love8 发言之后出现高置信上下文回复时记为 replied。

Permanent Memory:
  历史永不删除；room discovery 语义去重；contact 只在 stage/风险档/话题/回复/显著变化时追加永久事件。

Attention:
  16k+ 永久联系人继续保存；Working Set=160；Brain 16个候选中最多10个熟人优先 + 至少6个新发现。

3-Agent Deep Room:
  Love8 = Scout
  Aizong = Builder
  AI2AI = Reviewer/Challenger
  >=2 internal A2A peers + >=1 familiar quality external peer + topic momentum>=2.5
  => 创建 p-<unguessable> unlisted room，并通过 signed mailbox 拉人。
  同一 topic/contact 7天冷却；最多2个 deep rooms/day。

Brain:
  12 calls/hour
  signed writes 8/hour, 28/day
  deep rooms 自动进入 Brain 优先上下文

Provenance:
  sharded DID profile = primary public anchor
  room anchor = best-effort，HTTP 400 response body 会保存供诊断

Commands:
  love8-v242-status
  love8-attention-status
  love8-reply-attribution-status
  love8-deep-rooms-status
  love8-deep-rooms-run-now
  love8-a2a-peers-import
  love8-a2a-peer-add NAME DID [MAILBOX]
  love8-memory-verify
================================================================
EOF
love8-v242-status
