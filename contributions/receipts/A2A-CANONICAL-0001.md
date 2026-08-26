# Contribution Receipt v1 — A2A-CANONICAL-0001

**Receipt version:** 1  
**Canonical ID:** `A2A-CANONICAL-0001`  
**Workflow ID:** `wf-1787757470-5f882e70e2`  
**Canonical designation:** YES — first canonical three-agent A2A workflow for this deployment  
**Acceptance verdict:** CONDITIONAL PASS  
**Terminal evidence:** NOT YET OBSERVED in the captured provenance supplied for this receipt  
**Repository:** `yinchun6969/technocore-chat`  
**Transport:** Technocore signed message lane; Builder fallback transport uses existing owned room `d-aizong`

## Purpose

This receipt fixes `wf-1787757470-5f882e70e2` as the first canonical workflow used to validate a three-agent, three-DID collaboration pattern over Technocore. The workflow goal was to produce a minimal conformance specification for a signed A2A workflow that survives transient failures without duplicate task execution, including state-machine, idempotency, replay, recovery, and test-matrix requirements.

Canonical designation identifies the reference workflow. It does **not** rewrite or overstate the observed evidence: the captured provenance currently proves start, build, review, and review-recovery stages; a terminal `REVISED_RESULT -> COMPLETE` chain has not yet been independently observed in the evidence used to publish this v1 receipt.

## Participants

| Role | Agent | DID |
|---|---|---|
| Scout | `love8` | `did:key:z6MkfGtYxQg6e2u7aLBJVzowxgtgTmYzzXo227W9AvVQwq3p` |
| Builder | `aizong` | `did:key:z6MktU13Pf4jVf6Ck5D3pwNYX2PVUAfNC61ytciyb4Coyh7e` |
| Reviewer | `ai2ai` | `did:key:z6Mkrs9FviuKvQnAnexWfF1RWduNh6CqydrMAw8RUo73zoje` |

## Observed provenance

| Stage | Agent | Evidence | SHA-256 / identifier | Verdict |
|---|---|---|---|---|
| `WORKFLOW_TASK` / `workflow_started` | love8 | Captured local provenance | `goal_sha256=ab1b9754ade4fd3b7fd304eda31548078068011247cd50f49cc57b38650b26f4` | PASS |
| `BUILD_RESULT` / `workflow_build_result` | aizong | Captured local provenance | `result_sha256=97adf7e5bf7a3ec11ec8c07a932b634f2a4983272573e6995d12f1b085fcdb0f` | PASS |
| `CHALLENGE` / `workflow_challenge` | ai2ai | Captured local provenance | `challenge_sha256=243a69e81b54dae321004045ddabb468456e7076dc7bc6192697478f36122d9e` | PASS |
| recovery / `workflow_challenge_recovered` | ai2ai | Captured local provenance after envelope hardening | `challenge_sha256=e49f36796b1a703b758b5cf74cbadc1b34c2d0282a64485f923829e9de3a1e53` | PASS |
| `REVISED_RESULT` / `workflow_revised_result` | aizong | Not present in supplied terminal evidence at receipt publication | — | PENDING |
| `COMPLETE` / `workflow_complete` | love8 | Not present in supplied terminal evidence at receipt publication | — | PENDING |
| terminal receipt / `workflow_complete_received` | ai2ai | Not present in supplied terminal evidence at receipt publication | — | PENDING |

## Reliability findings captured by the canonical workflow

The workflow exercised real failure and recovery paths rather than synthetic message-only activity. During bring-up, the deployment encountered transient `429/503` behavior, a half-completed task caused by marking work processed before the terminal result was safely emitted, duplicate sidecar workers, global room-capacity pressure during first-write mailbox activation, owned-room authorization (`room-allow`) requirements, and an application-side payload truncation bug that could turn a valid A2A JSON envelope into invalid JSON while the receive cursor still advanced.

The deployment was hardened with terminal-only processed state, remote ACK/RESULT duplicate suppression, single-worker enforcement, owned-room writer authorization, explicit fallback routing through `d-aizong`, a 3400-byte A2A envelope guard, refusal to truncate signed A2A payloads, and a same-workflow challenge recovery command. The recovered Reviewer challenge retained the original workflow ID instead of creating a second workflow.

## Canonical workflow contract

The intended canonical state progression is:

```text
love8 / Scout
  WORKFLOW_TASK
        ↓
aizong / Builder
  BUILD_RESULT
        ↓
ai2ai / Reviewer
  CHALLENGE
        ↓
aizong / Builder
  REVISED_RESULT
        ↓
love8 / Scout
  COMPLETE
        ├──→ aizong
        └──→ ai2ai
```

The canonical correlation key is the immutable workflow ID `wf-1787757470-5f882e70e2`. Recovery actions must preserve that ID. A retry that generates a different `wf-*` identifier is a new workflow and must not be represented as recovery of this canonical record.

## Acceptance criteria

| Criterion | Result |
|---|---|
| Three distinct persistent DIDs | PASS |
| Explicit Scout / Builder / Reviewer separation | PASS |
| Allow-listed peer mesh | PASS |
| Signed transport between agents | PASS |
| Same workflow ID preserved across observed stages | PASS |
| Independent Reviewer challenge | PASS |
| Recovery preserved original workflow ID | PASS |
| Payload truncation disabled for signed A2A envelope | PASS |
| Terminal `REVISED_RESULT` observed | PENDING |
| Scout `COMPLETE` observed | PENDING |
| Reviewer terminal receipt observed | PENDING |

## Public implementation references

- Scout / Builder Workflow v3 installer: `deploy/a2a-v3/install-workflow-v3-collab.sh`
- Owned-room authorization: `deploy/a2a-v3/authorize-workflow-writers-v3.2.sh`
- A2A envelope hardening: `deploy/a2a-v3/harden-workflow-envelope-v3.3.sh`
- Reviewer implementation and recovery are maintained on the public `a2a-deploy-v1` branch.

## Receipt policy

This receipt is evidence-oriented. It records only stages observed in supplied provenance and intentionally does not claim terminal completion before terminal evidence exists. Once `workflow_revised_result`, `workflow_complete`, and the terminal Reviewer receipt are observed for the same workflow ID, this file should be updated in place to **Acceptance verdict: PASS** without changing `Canonical ID` or `Workflow ID`.

---

**Canonical declaration:** `wf-1787757470-5f882e70e2` is designated `A2A-CANONICAL-0001`, the first canonical A2A workflow for this deployment.
