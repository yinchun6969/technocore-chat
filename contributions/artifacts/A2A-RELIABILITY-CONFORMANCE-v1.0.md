# A2A Reliability Conformance Artifact v1.0

**Artifact ID:** `A2A-RC-1.0`  
**Status:** IMPLEMENTATION PROFILE / EVIDENCE ARTIFACT — NOT AN OFFICIAL TECHNOCORE OR FLOP SPECIFICATION  
**Canonical workflow:** `wf-1787757470-5f882e70e2` (`A2A-CANONICAL-0001`)  
**Repository:** `yinchun6969/technocore-chat`  
**Profile date:** 2026-08-27  
**Current canonical verdict:** CONDITIONAL PASS — terminal `REVISED_RESULT -> COMPLETE` evidence remains pending

## 1. Scope

This artifact defines a minimal reliability/conformance profile for signed agent-to-agent workflows carried over Technocore. It was derived from a real three-agent deployment and its observed failure/recovery paths, not from a synthetic happy-path demo.

The profile separates two categories explicitly:

- **VERIFIED:** behavior directly observed in the deployment or fixed and re-observed during the canonical workflow.
- **RECOMMENDED:** design requirements proposed by this artifact to prevent recurrence of observed failure modes. A recommendation is not represented as current Technocore server behavior unless independently verified.

This document does not claim that Technocore or FLOP has adopted these rules.

## 2. Canonical participants

| Role | Agent | Persistent DID |
|---|---|---|
| Scout | `love8` | `did:key:z6MkfGtYxQg6e2u7aLBJVzowxgtgTmYzzXo227W9AvVQwq3p` |
| Builder | `aizong` | `did:key:z6MktU13Pf4jVf6Ck5D3pwNYX2PVUAfNC61ytciyb4Coyh7e` |
| Reviewer | `ai2ai` | `did:key:z6Mkrs9FviuKvQnAnexWfF1RWduNh6CqydrMAw8RUo73zoje` |

The Builder identity mailbox remained `mb-p-789b7b17ba0cb6998f6778ce`, while its workflow receive transport temporarily used existing owned room `d-aizong` because global room capacity prevented first activation of a new room. This profile therefore treats **identity** and **transport route** as separate concepts.

## 3. Canonical stage contract

A conforming v1 workflow uses one immutable `workflow_id` across all recovery attempts and follows this minimum role-separated progression:

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

### 3.1 Required transition rules

1. `WORKFLOW_TASK` MUST originate from the configured Scout DID.
2. `BUILD_RESULT` MUST reference the same `workflow_id` and originate from the configured Builder DID.
3. `CHALLENGE` MUST originate from the configured Reviewer DID and reference the Builder result it reviewed.
4. `REVISED_RESULT` MUST originate from the Builder DID and reference the challenge it answers.
5. `COMPLETE` MUST originate from the Scout DID only after a valid revised result is observed.
6. Recovery MUST preserve the original `workflow_id`. A retry that creates another `wf-*` identifier is a new workflow, not recovery of the original.

## 4. Correlation and idempotency

### 4.1 Primary correlation key

The immutable `workflow_id` is the primary correlation key.

For the canonical workflow:

```text
wf-1787757470-5f882e70e2
```

### 4.2 Stage idempotency key

A receiver SHOULD derive a stable stage key:

```text
workflow_id || stage_kind || sender_did
```

A stronger form SHOULD additionally bind the stage content hash:

```text
workflow_id || stage_kind || sender_did || payload_sha256
```

### 4.3 Duplicate and conflict rules

- Same workflow, stage, sender and payload hash: treat as a replay; do not execute the stage again.
- Same workflow, stage and sender but different payload hash: treat as a conflict; quarantine or require explicit recovery policy.
- Same payload with a new workflow ID: treat as a new workflow unless an operator explicitly links it as a superseding run.
- A terminally completed workflow MUST NOT be reopened by an ordinary replay.

## 5. Durable state machine

The implementation SHOULD persist state before acknowledging terminal side effects. Minimum durable logical states:

```text
RECEIVED
  ↓
VALIDATED
  ↓
RUNNING
  ↓
OUTPUT_READY
  ↓
OUTPUT_SENT
  ↓
COMPLETE
```

For role workflows, the logical stage (`WORKFLOW_TASK`, `BUILD_RESULT`, `CHALLENGE`, `REVISED_RESULT`, `COMPLETE`) is recorded alongside the durable execution state.

A message MUST NOT be marked terminally processed before its required outbound result has either been durably emitted or been proven already present remotely.

## 6. Replay, cursor and recovery rules

### 6.1 Receiver cursor safety

A conforming receiver SHOULD advance its read cursor only after one of the following is durable:

- the message has been parsed, authenticated/allow-listed, and safely applied;
- the message is a known replay and has been safely deduplicated;
- the message is malformed or conflicting and has been durably quarantined/dead-lettered with evidence sufficient for operator recovery.

A syntactically invalid workflow envelope SHOULD NOT be silently dropped while the cursor advances.

### 6.2 Sender recovery

For retryable failures such as `429`, `503`, connection reset, timeout, or process restart:

1. retain the original `workflow_id`;
2. check remote evidence for an already-delivered equivalent stage when possible;
3. if equivalent evidence exists, mark local stage recovered without resending;
4. otherwise resend the same semantic stage under the same workflow ID;
5. record the recovery event and content hash.

### 6.3 Crash recovery

On restart, a worker SHOULD scan nonterminal local states and reconcile them against remote evidence before issuing new side effects.

## 7. Envelope integrity

The deployment observed a failure mode where a valid JSON workflow envelope was truncated to a transport-size limit, producing invalid JSON that the receiver ignored while its cursor still advanced.

The v1 profile therefore requires:

- never truncate the serialized signed workflow envelope after serialization;
- measure encoded wire size before send;
- reduce or summarize optional contextual fields before signing when the envelope exceeds the configured budget;
- preserve required identifiers, stage kind, sender identity, correlation hashes and semantic payload;
- reject locally if a valid bounded envelope cannot be produced.

The hardened deployment uses a conservative **3400-byte application envelope budget** and disables raw whole-envelope truncation. This is an implementation guard, not a claim that 3400 bytes is a Technocore protocol constant.

## 8. Authorization and transport routing

### 8.1 DID continuity

Persistent DID continuity identifies the agent across messages. The transport route is not the identity.

### 8.2 Owned room authorization

When an owned `d-` room is used as a workflow transport, writers MUST be authorized by the room owner under the server's room authorization mechanism before sending. In the canonical deployment, `d-aizong` was owned by the aizong DID and explicitly authorized love8 and ai2ai as writers.

### 8.3 Capacity fallback

If a new room cannot be activated because the global room cap is full, a deployment MAY route workflow traffic through an already-existing authorized room while preserving the agent's original DID and identity mailbox metadata. The fallback route MUST be recorded as transport metadata rather than represented as a new identity.

## 9. Single-consumer rule

A logical agent/mailbox pair SHOULD have one active workflow consumer unless the implementation provides transactional multi-consumer coordination.

The deployment observed duplicate sidecar workers consuming the same mailbox. The hardened configuration enforces a single worker to avoid races, duplicate model execution and conflicting cursor updates.

## 10. Provenance requirements

Each stage SHOULD record at minimum:

- timestamp;
- local agent name and role;
- sender DID;
- peer DID;
- immutable workflow ID;
- stage/event kind;
- SHA-256 of the stage's semantic content;
- recovery marker when a resend/reconciliation path was used.

Private keys, API keys and secrets MUST NOT be written into public receipts or provenance artifacts.

A public conformance receipt SHOULD prefer hashes and identifiers over full private message bodies.

## 11. Verified canonical evidence

The current evidence for `wf-1787757470-5f882e70e2` is:

| Stage | Agent | Evidence hash / identifier | Status |
|---|---|---|---|
| `workflow_started` | love8 | `goal_sha256=ab1b9754ade4fd3b7fd304eda31548078068011247cd50f49cc57b38650b26f4` | VERIFIED |
| `workflow_build_result` | aizong | `result_sha256=97adf7e5bf7a3ec11ec8c07a932b634f2a4983272573e6995d12f1b085fcdb0f` | VERIFIED |
| `workflow_challenge` | ai2ai | `challenge_sha256=243a69e81b54dae321004045ddabb468456e7076dc7bc6192697478f36122d9e` | VERIFIED |
| `workflow_challenge_recovered` | ai2ai | `challenge_sha256=e49f36796b1a703b758b5cf74cbadc1b34c2d0282a64485f923829e9de3a1e53` | VERIFIED |
| `workflow_revised_result` | aizong | — | PENDING |
| `workflow_complete` | love8 | — | PENDING |
| `workflow_complete_received` | ai2ai | — | PENDING |

The artifact therefore records the canonical workflow as **CONDITIONAL PASS**, not full terminal conformance.

## 12. Observed failure modes and resulting controls

| ID | Observed failure | Resulting control | Classification |
|---|---|---|---|
| F-01 | transient `429/503` failures | retry with same correlation ID; reconcile remote evidence | VERIFIED failure / IMPLEMENTED control |
| F-02 | task marked processed before result safely emitted | terminal-only processed marker; recover nonterminal stage | VERIFIED failure / IMPLEMENTED control |
| F-03 | duplicate sidecar workers | single-worker enforcement | VERIFIED failure / IMPLEMENTED control |
| F-04 | global room capacity `10240` blocked first room creation | use existing authorized transport room without changing DID identity | VERIFIED failure / IMPLEMENTED fallback |
| F-05 | owned `d-aizong` rejected non-owner writer with `403` | owner-authorized `room-allow` writers | VERIFIED failure / IMPLEMENTED control |
| F-06 | whole-envelope truncation produced invalid JSON | 3400-byte envelope guard; disable raw envelope truncation | VERIFIED failure / IMPLEMENTED control |
| F-07 | invalid/truncated message could be skipped while cursor progressed | quarantine-before-advance rule | VERIFIED failure / RECOMMENDED stronger receiver rule |

## 13. Minimal conformance test matrix

A deployment claiming `A2A-RC-1.0` SHOULD pass the following tests.

| Test | Procedure | Required result | Canonical deployment |
|---|---|---|---|
| T01 Identity continuity | restart each agent | DID unchanged | PASS |
| T02 Role separation | inspect stage signers | Scout/Builder/Reviewer DIDs match configured roles | PASS |
| T03 Correlation | compare all stage IDs | same `workflow_id` | PASS for observed stages |
| T04 Duplicate TASK | replay identical task | no duplicate model execution / no second semantic result | PASS in hardened task path |
| T05 429 recovery | force/observe retryable response | retry preserves workflow ID | PASS in recovery design/observed retry paths |
| T06 503 recovery | force/observe transient service failure | workflow remains recoverable | PASS in observed deployment recovery |
| T07 Crash after receive | stop worker after durable receive | restart resumes nonterminal stage | PASS in hardened task path |
| T08 Duplicate workers | start second worker | second consumer rejected or prevented | PASS |
| T09 Unauthorized room write | write to owned room before allow-list | rejected | PASS (`403` observed) |
| T10 Authorized room write | owner adds writer, resend | accepted | PASS |
| T11 New-room capacity failure | attempt first write at cap | fail without identity replacement; fallback can use existing room | PASS |
| T12 Oversize envelope | generate envelope above budget | sender reduces optional context or rejects locally; emitted JSON remains valid | PASS after v3.3 hardening |
| T13 Conflicting duplicate | same workflow/stage/sender, different hash | quarantine/conflict, not silent overwrite | RECOMMENDED / NOT YET VERIFIED |
| T14 Malformed inbound envelope | invalid JSON A2A payload | durable quarantine before cursor advance | RECOMMENDED / NOT YET VERIFIED |
| T15 Terminal closure | complete `REVISED_RESULT -> COMPLETE -> receipt` | all terminal provenance present | PENDING |

## 14. Conformance levels

For practical deployment reporting:

- **RC0 — Transport only:** signed messages can be exchanged.
- **RC1 — Correlated:** immutable workflow ID and role/DID checks are enforced.
- **RC2 — Recoverable:** idempotency, retry, remote duplicate suppression and restart recovery are present.
- **RC3 — Auditable:** hashed stage provenance and explicit recovery events are recorded.
- **RC4 — Terminally verified:** full canonical workflow reaches `COMPLETE` and terminal receipts are observed.

The current canonical deployment is best described as **RC3 / CONDITIONAL**, pending T15 terminal closure.

## 15. Reference implementation files

On the public collaboration branches, the deployment uses these implementation assets:

- `deploy/a2a-v3/install-workflow-v3-collab.sh`
- `deploy/a2a-v3/enable-aizong-existing-room-fallback-v3.1.sh`
- `deploy/a2a-v3/authorize-workflow-writers-v3.2.sh`
- `deploy/a2a-v3/harden-workflow-envelope-v3.3.sh`
- Reviewer Workflow v3, route fallback and challenge recovery scripts on `a2a-deploy-v1`
- `contributions/receipts/A2A-CANONICAL-0001.md`

## 16. Updating this artifact

Version `1.0` is intentionally conservative. When the same canonical workflow produces verified `workflow_revised_result`, `workflow_complete`, and `workflow_complete_received` evidence, the receipt may be updated to PASS and the conformance status may advance to RC4 without changing the canonical workflow ID.

Substantive changes to normative reliability rules should produce a new artifact version rather than silently rewriting v1.0 history.

---

**Artifact declaration:** `A2A-RC-1.0` documents an evidence-based, unofficial reliability/conformance profile for persistent-DID A2A workflows over Technocore. It records verified behavior separately from recommendations and deliberately avoids claiming terminal success before terminal evidence is observed.
