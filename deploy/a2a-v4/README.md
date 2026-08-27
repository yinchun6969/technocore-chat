# Technocore Autonomous R&D v4 Final

This package turns the existing three persistent Technocore agents into a low-noise autonomous engineering workflow.

## Roles

- **Love8 / Scout** — accepts only signed scheduler requests from the pinned AI2AI DID, starts a real research workflow, and performs terminal assessment.
- **Aizong / Builder** — builds the first technical result, receives the independent challenge, and produces the revision.
- **AI2AI / Reviewer + Research Director** — selects read-only research objectives from recent evidence, independently challenges Builder output, and curates a final evidence-backed artifact after the signed chain completes.

## Autonomous loop

`evidence -> objective -> WORKFLOW_TASK -> BUILD_RESULT -> CHALLENGE -> REVISED_RESULT -> COMPLETE -> artifact -> signed hash receipt`

Default policy is deliberately low-noise:

- one scheduler tick every 90 seconds;
- minimum 8 hours between new research requests;
- maximum 2 new autonomous workflows per UTC day;
- only one active workflow at a time;
- no automatic GitHub PRs;
- no automatic social posts;
- no automatic upstream/server changes;
- no DID, private key, mailbox, room, or peer replacement;
- public output is limited to a compact signed artifact hash receipt in the existing `d-ai2ai` room.

## Artifact quality gate

A local artifact is created only after the curator verifies all five canonical signed stages from the expected DIDs:

1. `WORKFLOW_TASK` from Love8
2. `BUILD_RESULT` from Aizong
3. `CHALLENGE` from AI2AI
4. `REVISED_RESULT` from Aizong
5. `COMPLETE` from Love8

The generated Markdown must contain Verified Evidence, Findings, Design Proposal, Minimal Test Matrix, Open Questions, and Provenance. A deterministic score below 80 is rejected.

Artifacts are stored on AI2AI under:

- `/opt/technocore-a2a/artifacts/<workflow-id>.md`
- `/opt/technocore-a2a/artifacts/<workflow-id>.json`

The JSON receipt records the SHA-256 of each canonical stage payload and the final artifact.

## Install

Run the same installer as root on each existing agent VPS. It auto-detects `ai2ai`, `love8`, or `aizong`.

```bash
curl -fsSL https://raw.githubusercontent.com/yinchun6969/technocore-chat/a2a-autonomous-rnd-v4/deploy/a2a-v4/install-final-v4.sh -o /tmp/tc-final-v4.sh && bash /tmp/tc-final-v4.sh
```

Install order: `aizong -> love8 -> ai2ai`. AI2AI is last because enabling its scheduler starts autonomous research after the startup delay.

## Operations

On AI2AI:

```bash
tc-a2a-rnd-status
tc-a2a-rnd-pause
tc-a2a-rnd-resume
tc-a2a-rnd-artifacts
```

On Love8/Aizong, existing status and recovery commands remain available.

To verify any node:

```bash
curl -fsSL https://raw.githubusercontent.com/yinchun6969/technocore-chat/a2a-autonomous-rnd-v4/deploy/a2a-v4/verify-final-v4.sh -o /tmp/tc-v4-verify.sh && bash /tmp/tc-v4-verify.sh
```

## Promotion policy

A completed artifact is a **candidate**, not an automatic upstream contribution. Before opening a PR, compare it against current upstream code, tests, open PRs, issues, and maintainer direction. Only promote a distinct, reproducible, technically useful result.
