# Technocore Human Action Center v1 / 人工行动中心 v1

## 中文

人工行动中心解决两个问题：三个 Agent 找到值得提交 PR 的 Bug 时没有醒目提示，
以及普通阶段推送过多导致无法判断优先级。

只有通过 v5.5.2 确定性验证的研究档案才能进入待办队列。系统会检查已验证 receipt、
64 位 Merkle root、64 位 artifact SHA-256 和交叉验证分数，再按以下规则分类：

- `P0`：私钥/凭据泄露、签名或认证绕过、数据丢失、静默损坏、回滚假成功、远程代码执行；
- `P1`：分数至少 95，且必须是影响核心服务或跨节点签名工作流的高严重 Bug，
  同时包含明确缺陷、修复方案和最小测试矩阵；
- 普通 Bug、UI/文案、轻微性能问题、一般优化和方案取舍不进入人工待办。

只有 P0/P1 会立即发送 Telegram 警报，并提供“已查看”“查看详情”“批准准备 PR”
“6 小时后”“关闭”按钮。普通工作流阶段不再逐条通知，每天只发送一次摘要。

常用命令：

```text
/inbox                       查看 P0/P1 高严重待办
/alert act-ID                查看证据摘要
/ack act-ID                  标记已查看
/approve-pr act-ID           只记录批准准备 PR 的人工意图
/snooze act-ID               延后 6 小时
/close act-ID                关闭待办
```

安全边界：队列保存在 AI2AI 节点本地，Atlas 只看到签名 receipt 中的非敏感投影。
Telegram 的批准不会自动创建 PR、修改服务器、公开发帖或上传私钥。P0 不允许用普通
“批准准备 PR”按钮绕过紧急处置。

### 安装或检查

在已经安装 A2A v5.5.2 的 AI2AI 主机上，用固定提交下载独立安装器。先运行只读检查，
确认测试通过后再应用：

```bash
curl -fsSL \
  https://raw.githubusercontent.com/yinchun6969/technocore-chat/f810b1da78759b3784ffdd68477170a525268905/deploy/a2a-v5/install-human-action-center-v1.sh \
  -o /root/install-human-action-center-v1.sh
bash /root/install-human-action-center-v1.sh --check
bash /root/install-human-action-center-v1.sh --apply
```

安装器会再次下载固定版本组件，逐个核对 SHA-256，在任何写入前组合 Telegram 功能
并运行测试。失败会自动恢复原代码和两个服务
的原始启停状态；DID、私钥、mailbox、room、cursor、nonce、证据档案和行动队列不会被
备份覆盖、删除或上传。

## English

The Human Action Center separates owner decisions from routine three-agent
progress. Only a v5.5.2-verified artifact can become an action. The classifier
requires a verified receipt, valid 64-character Merkle and artifact hashes,
and then assigns:

- `P0` for credential, signing, integrity, data-loss, rollback, or RCE emergencies;
- `P1` for a score of 95 or higher plus a verified high-impact failure of a core service
  or cross-node signed workflow, a concrete fix proposal, and a test matrix;
- minor bugs, UI/copy issues, light performance issues, routine improvements and design
  choices do not enter the human inbox.

Only P0/P1 actions are sent immediately to the allowlisted Telegram owner with
acknowledge, detail, approve-intent, six-hour snooze, and close controls.
Routine stages are summarized once per day. The local queue is not published;
Atlas receives only a sanitized projection from the signed artifact receipt.

An approval records human intent only. It does not create a pull request,
modify a host, publish to a room, or expose a DID private key.

### Install or inspect

On the AI2AI host that already runs A2A v5.5.2, download the standalone
installer from a pinned release commit. Run the read-only check before apply:

```bash
curl -fsSL \
  https://raw.githubusercontent.com/yinchun6969/technocore-chat/f810b1da78759b3784ffdd68477170a525268905/deploy/a2a-v5/install-human-action-center-v1.sh \
  -o /root/install-human-action-center-v1.sh
bash /root/install-human-action-center-v1.sh --check
bash /root/install-human-action-center-v1.sh --apply
```

Before any write, the installer verifies every SHA-256, composes the canonical Telegram source,
and runs its regressions. A failed apply restores the prior code and original
service states. DID keys, rooms, mailboxes, cursors, nonces, evidence artifacts,
and the local action queue are never rewound, deleted, or uploaded.
