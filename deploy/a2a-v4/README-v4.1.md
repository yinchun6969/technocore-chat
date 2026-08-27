# A2A Autonomous Research v4.1

This release is an independent hardening layer on top of the already-verified three-DID workflow. It does not replace the Love8, Aizong, or AI2AI identities, mailboxes, peers, workflow state, or provenance ledger.

## Roles

- Love8 — the only autonomous research director and Scout
- Aizong — Builder
- AI2AI — Reviewer and recovery watchdog
- All three nodes — 24/7 recovery watchdog

## Autonomous behavior

After the RC4 gate is enabled on Love8, the director can:

1. Read recent upstream commits, open pull requests, open issues, failed CI runs, and non-sensitive local failure signals.
2. Ask the configured model to select one specific, testable research objective.
3. Prefer reproducible bug verification when failure evidence exists.
4. Require a measurable baseline and acceptance criteria for optimization objectives.
5. Suppress duplicate goals and low-quality candidates.
6. Start the existing workflow automatically: WORKFLOW_TASK -> BUILD_RESULT -> CHALLENGE -> REVISED_RESULT -> COMPLETE.
7. Recover stalled workflow stages without creating a second workflow.

It only produces evidence-backed research and local artifacts. It does not execute generated commands, modify servers, open GitHub PRs, post to X, or perform reward/airdrop farming.

Defaults: one workflow at a time, at least 90 minutes between workflows, at most 8 autonomous workflows per rolling 24 hours, quality threshold 75/100, and a 30-minute candidate-attempt cooldown.

## Install

Run the v4.1 installer on all three existing VPS nodes, one at a time. It detects the node from the existing configuration.

```bash
curl -fL --retry 5 --retry-delay 2 \
  https://raw.githubusercontent.com/yinchun6969/technocore-chat/a2a-autonomous-v4.1/deploy/a2a-v4/install-autonomous-research-v4.1.sh \
  -o /tmp/install-autonomous-research-v4.1.sh &&
echo "f8f1181a00162eb727e54df02dfd05cc3d96308fd9207d1229831448fcec253a  /tmp/install-autonomous-research-v4.1.sh" | sha256sum -c - &&
chmod 700 /tmp/install-autonomous-research-v4.1.sh &&
bash /tmp/install-autonomous-research-v4.1.sh
```

The installer starts the watchdog in gated mode. It creates a per-node backup under:

```
/root/tc-autonomy-v4.1-backups/
```

## Enable autonomous research

Only after all three nodes are installed, run on Love8:

```bash
tc-autonomy-enable
tc-autonomy-status
```

The enable/disable switch is hot-reloaded by the running daemon. No manual restart is required.

Expected status:

```text
node: love8
enabled: 1
rc4_gate: VERIFIED
daemon: ACTIVE
```

Aizong and AI2AI remain recovery-only nodes:

```bash
tc-autonomy-status
```

## Observe

On Love8:

```bash
tail -f /opt/technocore-autonomy/log/autonomy.jsonl
cat /opt/technocore-autonomy/state/director.json
```

Useful events include `workflow_autonomous_started`, `candidate_rejected`, `candidate_duplicate`, `watch_read_error`, and `recovery_attempt`.

## Rollback

Run on the node where v4.1 was installed:

```bash
tc-autonomy-rollback
```

Rollback restores the previous autonomy files, helper commands, and systemd unit from the newest v4.1 backup. It does not touch the Technocore agent identity, mailbox, peers, cursor, or provenance ledger.
