# A2A-RC-1.0 RC4 + Autonomous Research v4

This branch promotes the canonical three-DID workflow only after terminal evidence is observed. It does not self-declare `Verified` before the wire chain and local terminal receipt pass verification.

## Canonical workflow

`wf-1787757470-5f882e70e2`

Expected terminal chain:

`WORKFLOW_TASK -> BUILD_RESULT -> CHALLENGE -> REVISED_RESULT -> COMPLETE`

Participants:

- love8 — Scout
- aizong — Builder
- ai2ai — Reviewer

## RC4 promotion

Use `promote-rc4.sh` sequentially on aizong, then love8, then run `verify-rc4.sh` on all three nodes. The promotion driver reuses the same workflow ID and the existing endgame recovery commands; it does not create a replacement workflow.

RC4 verification checks the live Technocore wire chain for the canonical workflow and the local node's terminal provenance. Only after all three nodes report a verified local terminal state should the canonical GitHub receipt be changed from Conditional to Verified.

## Autonomous Research v4.0

`install-autonomous-research-v4.0.sh` installs a continuous recovery watchdog on all three nodes. The Scout director remains gated off until RC4 verification is explicitly enabled.

Default research policy:

- one workflow in flight at a time
- at least 90 minutes between new workflows
- maximum 8 autonomous workflows per rolling 24 hours
- candidate quality threshold 75/100
- public-source digest from recent upstream commits and open PRs when available
- duplicate-goal suppression
- same-workflow recovery for stalled review/revision/finalize stages
- backoff on transport/API failures
- no automatic GitHub PR, X post, reward/airdrop farming, or public promotion

The 24/7 mode is intended to generate evidence-backed engineering research and local candidate artifacts. Upstream contributions remain a separate review decision.

## Commands

- `tc-autonomy-status`
- `tc-autonomy-enable` — love8 only; requires canonical RC4 verifier success
- `tc-autonomy-disable` — stops new autonomous research while keeping recovery watchdog active

Configuration: `/opt/technocore-autonomy/autonomy.env`

State/logs:

- `/opt/technocore-autonomy/state/`
- `/opt/technocore-autonomy/log/autonomy.jsonl`
