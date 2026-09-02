# Technocore Human Action Center v1 / 人工行动中心 v1

## 中文

人工行动中心解决两个问题：三个 Agent 找到值得提交 PR 的 Bug 时没有醒目提示，
以及普通阶段推送过多导致无法判断优先级。

只有通过 v5.5.2 确定性验证的研究档案才能进入待办队列。系统会检查已验证 receipt、
64 位 Merkle root、64 位 artifact SHA-256 和交叉验证分数，再按以下规则分类：

- `P0`：私钥/凭据泄露、签名或认证绕过、数据丢失、静默损坏、回滚假成功、远程代码执行；
- `P1`：分数至少 90，并同时包含明确 Bug、修复方案和最小测试矩阵；
- `P2`：研究结论明确要求人工确认、批准或方案取舍。

P0/P1/P2 会立即发送 Telegram 警报，并提供“已查看”“查看详情”“批准准备 PR”
“6 小时后”“关闭”按钮。普通工作流阶段不再逐条通知，每天只发送一次摘要。

常用命令：

```text
/inbox                       按 P0、P1、P2 查看待办
/alert act-ID                查看证据摘要
/ack act-ID                  标记已查看
/approve-pr act-ID           只记录批准准备 PR 的人工意图
/snooze act-ID               延后 6 小时
/close act-ID                关闭待办
```

安全边界：队列保存在 AI2AI 节点本地，Atlas 只看到签名 receipt 中的非敏感投影。
Telegram 的批准不会自动创建 PR、修改服务器、公开发帖或上传私钥。P0 不允许用普通
“批准准备 PR”按钮绕过紧急处置。

## English

The Human Action Center separates owner decisions from routine three-agent
progress. Only a v5.5.2-verified artifact can become an action. The classifier
requires a verified receipt, valid 64-character Merkle and artifact hashes,
and then assigns:

- `P0` for credential, signing, integrity, data-loss, rollback, or RCE emergencies;
- `P1` for a score of 90 or higher plus a concrete bug, fix proposal, and test matrix;
- `P2` for an explicit operator decision or approval.

P0/P1/P2 actions are sent immediately to the allowlisted Telegram owner with
acknowledge, detail, approve-intent, six-hour snooze, and close controls.
Routine stages are summarized once per day. The local queue is not published;
Atlas receives only a sanitized projection from the signed artifact receipt.

An approval records human intent only. It does not create a pull request,
modify a host, publish to a room, or expose a DID private key.
