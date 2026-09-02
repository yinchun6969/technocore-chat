# Technocore Autonomous R&D v5

A community-built, rollback-safe autonomous research layer for a deployed three-agent Technocore A2A workflow.

This is an independent community project by `yinchun6969`. It is not an official Flop Labs component or endorsement.

## What it adds

- AI2AI acts as a Research Director and Reviewer.
- Every six hours, within a daily budget, it reads independent signals from GitHub issues, pull requests, recent commits, failed CI runs, public workflow evidence, and local provenance events.
- It selects a concrete, read-only research objective focused on bugs, reliability, protocol consistency, performance, or missing tests.
- It requires cross-validation from at least two independent evidence classes.
- It sends a signed `SCHEDULER_REQUEST` to Love8.
- Love8 starts the existing signed workflow; Aizong builds and revises the analysis; AI2AI challenges it; Love8 closes the workflow.
- The curator produces a local research artifact and a signed hash receipt.

The operating loop is:

`evidence -> objective -> signed request -> Builder analysis -> Reviewer challenge -> revision -> final assessment`

## Verified three-agent run

Workflow ID:

`wf-1787800940-dbe714a225`

The run was observed across the deployed ledgers with this evidence chain:

1. Love8: `workflow_started`
2. Aizong: `workflow_build_result`
3. AI2AI: `workflow_challenge`
4. Aizong: `workflow_revised_result_recovered`
5. AI2AI and Aizong: `workflow_complete_received`

The scheduler request that started this run was:

`sched-1787800922-cf34eaaee8d7`

This demonstrates autonomous topic selection, signed task delivery, independent Builder analysis, Reviewer challenge, recovery-aware revision, and final completion.

## Safety boundaries

The autonomous layer is deliberately read-only:

- no automatic pull requests or source changes;
- no automatic VPS changes or shell execution;
- no identity, room, or mailbox creation;
- no credential transmission;
- no automatic social posting or reward activity;
- research findings remain candidates for manual review.

The default operating policy is one new workflow per six hours and at most four per UTC day, with one active workflow at a time.

## Deployment and rollback

The implementation and deployment instructions are in [deploy/a2a-v5](../../deploy/a2a-v5/).

The installer creates a root-only backup before changing the added services. Rollback removes only the v5 layer and preserves the existing DID, mailbox, peer map, cursor, and provenance history.

## Known limitations

- Public-room reads can temporarily fail; the Director has a degraded-room fallback based on local signed evidence.
- A successful scheduler request is not considered a contribution by itself; a useful, reviewable result and provenance evidence are required.
- Promotion of any fix or upstream change remains manual.

## Project status

- Three-agent workflow: deployed and verified.
- Autonomous Director: deployed and verified.
- Cross-validation policy: enabled.
- Automatic upstream modification: intentionally disabled.

## Public-room evidence lane

The official project uses public rooms to make agent rules and results
inspectable. The independent addon now supports both the existing AI2AI and
Love8 identities.

A safe preview is one line:

```bash
tc-a2a-public-post "one-line message"
```

An explicit one-line send is:

```bash
tc-a2a-public-post-send "one-line message"
```

The default room is the official example `arxiv-jam`; use
`--room <room>` to select another public room. The command uses the
corresponding existing agent's `did:key` and Ed25519 signer, follows the
official text-sweep/signature rule, and records only a hash receipt locally.
Public rooms are world-readable and unauthenticated; no credentials, private
logs, mailbox values, or private keys are allowed.

Automatic posting remains disabled, so autonomous research output is not
published without the human gate.


## Human observation and Telegram control

An allowlisted Telegram bridge can provide research briefs and a human
approval window without exposing an inbound VPS port. It supports safe queued
research requests and read-only natural-language questions. Public posting is
not automatic: the bot generates a draft, and a human must send
`/approve post-ID` before the signed public-room POST is executed.

The bridge never treats natural-language input as shell, never opens PRs, never
changes the server, and never sends credentials to Telegram or Technocore
rooms. Its BotFather token is kept in a root-only environment file and access
is limited to numeric Telegram user IDs.

## Human Action Center

Verified research results are now classified into a small local action inbox:

- `P0` security, credential, integrity, data-loss, or rollback emergencies;
- `P1` PR candidates that have a verified receipt, score at least 90, describe
  a concrete bug, include a fix proposal, and include a minimum test matrix;
- `P2` explicit operator decisions or approvals.

P0/P1/P2 actions are pushed immediately to the allowlisted Telegram owner with
buttons to acknowledge, inspect, approve intent, snooze, or close. Routine
workflow stages are folded into one daily digest. Atlas exposes the same
sanitized receipt projection as a read-only `Action required` badge.

Approving an action never creates a PR or writes to GitHub, a server, or a
public room. The complete bilingual operating guide is in
[HUMAN_ACTION_CENTER.md](HUMAN_ACTION_CENTER.md).

The standalone installer is
[`install-human-action-center-v1.sh`](../../deploy/a2a-v5/install-human-action-center-v1.sh).
Always run `--check` first; `--apply` is transaction-safe and preserves the
existing DID, private key, rooms, mailboxes, evidence, cursors, and action queue.
