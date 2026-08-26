# Technocore A2A Reliability Conformance v1

Status: **independent engineering draft based on one real three-agent run**. This is **not** an official FLOP Labs or Technocore protocol specification.

Companion receipt: `docs/a2a/A2A-CONTRIBUTION-RECEIPT-v1.json`

## 1. Purpose

This document defines a minimal reliability profile for signed agent-to-agent workflows transported over Technocore. It was produced from an actual three-DID workflow and the failures encountered while making that workflow complete.

The reference workflow used three persistent Ed25519 `did:key` identities:

| Role | Agent | DID |
|---|---|---|
| Scout | love8 | `did:key:z6MkfGtYxQg6e2u7aLBJVzowxgtgTmYzzXo227W9AvVQwq3p` |
| Builder | aizong | `did:key:z6MktU13Pf4jVf6Ck5D3pwNYX2PVUAfNC61ytciyb4Coyh7e` |
| Reviewer | ai2ai | `did:key:z6Mkrs9FviuKvQnAnexWfF1RWduNh6CqydrMAw8RUo73zoje` |

Workflow ID: `wf-1787757470-5f882e70e2`

Goal: produce a minimal conformance specification for a signed A2A workflow that survives transient 429/503 failures without duplicate task execution, including state, idempotency, replay, recovery, and tests.

## 2. Observed completed state machine

```text
Scout/love8
  WORKFLOW_TASK
      |
      v
Builder/aizong
  BUILD_RESULT
      |
      v
Reviewer/ai2ai
  CHALLENGE
      |
      |  original challenge transport failed semantically
      |  recovery emitted a valid bounded envelope
      v
Builder/aizong
  REVISED_RESULT
      |
      v
Scout/love8
  COMPLETE
      |\
      | +--> Builder received COMPLETE
      +----> Reviewer received COMPLETE
```

The run reached terminal completion. The Builder and Reviewer both recorded `workflow_complete_received` for the same workflow ID.

## 3. Evidence hashes

| Stage | SHA-256 |
|---|---|
| Goal | `ab1b9754ade4fd3b7fd304eda31548078068011247cd50f49cc57b38650b26f4` |
| Build result | `97adf7e5bf7a3ec11ec8c07a932b634f2a4983272573e6995d12f1b085fcdb0f` |
| Initial challenge | `243a69e81b54dae321004045ddabb468456e7076dc7bc6192697478f36122d9e` |
| Effective recovered challenge | `e49f36796b1a703b758b5cf74cbadc1b34c2d0282a64485f923829e9de3a1e53` |
| Revised result | `a21114f2f3df1be525cba10cbd527ca6acfec3f48edab7f76d3bb19012bbfa7b` |
| Derived receipt final hash | `be287c0bcc7b337d416cf8bb1f0cc3d76765c9ff8f5dc8add12874ee8387285e` |

The receipt final hash is a locally derived canonical receipt hash. It is **not** a Technocore protocol field.

## 4. Failure modes observed during the run

### F1. Transient 429 and 503 failures

Observed behavior: model/API and Technocore operations can fail transiently with HTTP 429 or 503. Blindly treating these failures as permanent loses work; blindly replaying whole workflows risks duplicate effects.

Conformance requirement:

- 429 and 5xx are retryable transport outcomes unless the endpoint states otherwise.
- Retry the individual stage delivery or poll, not the whole workflow.
- Use bounded exponential backoff with jitter.
- Preserve the same workflow ID and stage identity across retries.

### F2. Global room capacity blocked creation of a new mailbox room

Observed behavior: a write to an as-yet-unused mailbox returned an error stating the global room limit was `10240`, while existing rooms continued to accept writes.

Conformance requirement:

- A transport route MUST be preflighted before starting a workflow.
- A workflow MUST NOT assume that a configured mailbox string already exists as a writable room.
- If creation is unavailable, a previously existing authorized room MAY be used as a transport fallback without changing the persistent DID identity.
- Capacity failure MUST NOT cause creation of a second workflow ID.

### F3. Owned-room ACL rejected a valid signed writer

Observed behavior: after routing Builder traffic through the existing owned room `d-aizong`, writes from love8 initially returned HTTP 403. The Builder owner DID then authorized love8 and ai2ai via the room allow-list; subsequent signed writes succeeded.

Conformance requirement:

- Signed identity and room authorization are separate checks.
- Before using an owned room as shared A2A transport, verify owner identity and writer ACL.
- HTTP 403 is not a retryable transient failure until authorization/configuration changes.
- ACL changes MUST be signed by the room owner and MUST preserve the existing agent DID/private key.

### F4. Payload truncation converted valid JSON into invalid JSON

Observed behavior: the local sidecar implementation could truncate the final serialized message to a fixed character limit. A long CHALLENGE envelope was cut mid-JSON. The receiver could not parse it and therefore did not produce `REVISED_RESULT`.

This was an **implementation defect in the A2A sidecar**, not evidence that Technocore itself truncates valid JSON.

Conformance requirement:

- NEVER truncate an already serialized JSON envelope.
- Enforce a wire-size budget before signing/sending.
- Reduce optional/older context fields first, then serialize again.
- The final signed wire object MUST remain syntactically valid JSON.
- A sender SHOULD retain hashes of omitted context so provenance remains linkable.

Reference safe budget used in the repaired implementation: `3400` bytes.

### F5. Cursor advancement and replay safety

Observed behavior: a malformed/unparseable workflow item could be passed over while the local cursor still advanced. This made the lost stage invisible to normal replay and required a targeted recovery path.

Conformance requirement:

- A consumer MUST NOT treat cursor advancement as proof that a workflow item was semantically processed.
- Durable stage state MUST be written before the item is considered processed.
- Parse/validation failure MUST generate a durable failure record or dead-letter reference.
- Recovery MUST target the missing stage using the same workflow ID.
- Initial startup SHOULD prime a cursor to current history when old messages must not be replayed.

### F6. Duplicate worker processes

Observed behavior: more than one sidecar worker could run concurrently before hardening, creating a risk that two consumers process the same item.

Conformance requirement:

- Exactly one active worker SHOULD own a mailbox/role consumer at a time.
- Enforce this with systemd process ownership, a lock/lease, or another single-consumer primitive.
- A second worker MUST fail closed or become passive.
- Delivery may be at-least-once; externally visible effects MUST be idempotent.

## 5. Required workflow identity and idempotency model

A conforming implementation SHOULD treat the following tuple as the logical stage identity:

```text
(workflow_id, stage_type, sender_did)
```

Recommended stage types:

```text
WORKFLOW_TASK
BUILD_RESULT
CHALLENGE
REVISED_RESULT
COMPLETE
```

Rules:

1. `workflow_id` is created once by the Scout and is immutable.
2. Retries reuse the same `workflow_id`.
3. Each receiver maintains a durable set/state map of processed logical stage identities.
4. Duplicate delivery may be acknowledged but MUST NOT repeat model execution or external side effects after terminal processing of that stage.
5. `COMPLETE` is terminal for the workflow but does not erase provenance.

## 6. Minimal durable state machine

```text
NEW
  -> TASK_SENT
  -> BUILD_RESULT_RECEIVED
  -> CHALLENGE_RECEIVED
  -> REVISED_RESULT_RECEIVED
  -> COMPLETE
```

Recovery substates MAY include:

```text
SEND_RETRY_PENDING
POLL_RETRY_PENDING
INVALID_ENVELOPE
AUTH_BLOCKED
CAPACITY_BLOCKED
RECOVERY_STAGE_PENDING
```

A recovery substate MUST retain the original workflow ID and the last verified stage hash.

## 7. Retry classification

| Condition | Default classification | Required action |
|---|---|---|
| HTTP 429 | transient | retry same stage with backoff/jitter |
| HTTP 500/502/503/504 | transient | retry same stage with backoff/jitter |
| DNS/network timeout | transient environment failure | retry bounded; preserve workflow state |
| HTTP 400 malformed payload | deterministic | do not blind-retry; fix envelope/recover stage |
| HTTP 403 room ACL | deterministic authorization failure | repair ACL, then retry same stage |
| room capacity / new-room rejection | capacity/configuration failure | use existing route or wait; do not fork workflow |
| duplicate message | expected under at-least-once delivery | no duplicate side effect |

## 8. Envelope conformance

A workflow message MUST contain enough information to associate it with a persistent workflow and sender. A minimal logical envelope is:

```json
{
  "kind": "CHALLENGE",
  "workflow_id": "wf-...",
  "sender_did": "did:key:...",
  "payload": "...",
  "payload_sha256": "..."
}
```

Transport-specific signature fields may wrap this structure.

Requirements:

- JSON MUST parse after transport.
- `workflow_id`, `kind`, and sender identity MUST survive any context compaction.
- Hashes MUST be computed over the exact stage content whose provenance is being claimed.
- Optional prior-stage text MAY be compacted; prior-stage hashes SHOULD be retained.

## 9. Replay rules

1. Never replay historical mailbox content merely because a daemon restarted.
2. Cursor position alone is insufficient for exactly-once semantics.
3. The durable processed-stage map is authoritative for side effects.
4. If a stage was sent but local persistence failed, query remote evidence before resending when possible.
5. If the remote stage is already present, mark the local stage complete instead of sending a duplicate.
6. Recovery messages reuse the original workflow ID and explicitly record that recovery occurred.

## 10. Completion rule

A workflow is considered terminally complete when:

- a valid `REVISED_RESULT` exists for the workflow, and
- the Scout emits `COMPLETE`, and
- terminal reception is observed by the participating downstream agents or otherwise independently verifiable.

For the reference run, both Builder and Reviewer recorded `workflow_complete_received` for `wf-1787757470-5f882e70e2`.

## 11. Minimal conformance test matrix

| ID | Test | Expected result |
|---|---|---|
| T01 | Normal 3-agent workflow | one workflow reaches COMPLETE |
| T02 | 429 during stage send | same stage/workflow retried; no new workflow ID |
| T03 | 503 during mailbox poll | poll resumes; no duplicate model execution |
| T04 | Duplicate delivery of WORKFLOW_TASK | Builder effect occurs once |
| T05 | Restart after remote send but before local terminal write | remote evidence suppresses duplicate resend |
| T06 | Oversized CHALLENGE context | context compacted before serialization; valid JSON arrives |
| T07 | Deliberately malformed JSON | durable invalid-envelope record; cursor does not imply semantic success |
| T08 | Configured mailbox room does not exist while capacity is full | workflow start fails safely or uses preflighted existing route |
| T09 | Unauthorized writer to owned room | 403 classified as ACL failure; no blind retry loop |
| T10 | Owner grants writer ACL | same DID can retry same stage successfully |
| T11 | Two workers start for one agent | only one remains active/authoritative |
| T12 | Daemon starts with old mailbox history | cursor priming prevents old workflow replay |
| T13 | Recovery of a lost CHALLENGE | same workflow ID continues to REVISED_RESULT and COMPLETE |
| T14 | COMPLETE delivered twice | terminal state remains one logical completion |

## 12. Reference-run result

The reference workflow demonstrated the following recovery chain:

```text
room capacity failure
  -> existing owned-room fallback
  -> 403 ACL discovery
  -> owner-signed allow-list repair
  -> successful WORKFLOW_TASK
  -> BUILD_RESULT
  -> CHALLENGE
  -> invalid-envelope/truncation discovery
  -> bounded envelope repair
  -> targeted CHALLENGE recovery
  -> REVISED_RESULT
  -> COMPLETE received by Builder + Reviewer
```

This sequence is the basis for the requirements above. It is deliberately separated into **observed behavior** and **design recommendations** so that implementation lessons are not presented as official Technocore protocol guarantees.

## 13. Non-goals

This document does not:

- claim official FLOP/Technocore conformance status;
- define token, airdrop, reward, or eligibility rules;
- claim exactly-once network delivery;
- treat a DID as a trust/reputation guarantee;
- require automatic public posting, GitHub PR creation, or reward farming.

## 14. Versioning

`v1` captures the first completed three-DID signed workflow and its observed reliability failures. Future revisions should only add requirements backed by reproducible tests or clearly marked design proposals.
