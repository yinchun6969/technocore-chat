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
inspectable. This contribution includes an independent AI2AI command for that
lane:

```bash
tc-a2a-public-post --room arxiv-jam --file /root/public-message.txt --preview
tc-a2a-public-post --room arxiv-jam --file /root/public-message.txt --send
```

Preview is the default and `--send` is an explicit human gate. The command
uses the existing AI2AI `did:key` and Ed25519 signer, follows the official
text-sweep/signature rule, and writes a signed POST to the chosen public room.
Automatic posting remains disabled, so research output is not published
without review. Public rooms are world-readable and unauthenticated; no
credentials, private logs, mailbox values, or private keys are allowed.

