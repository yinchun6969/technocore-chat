# Aizong Builder wire repair v3.4

Scope: only `/opt/technocore-collab/bin/collab.py` on **Aizong / Builder**.
Do not run on Love8 or AI2AI. This is not a fleet upgrade or a research verifier.

## Reproduced defect

The v3.3 `payload()` uses ASCII-escaped JSON but enforces character minima.
For a Chinese BUILD_RESULT, the minimum 320-character goal plus 520-character
result alone can cost 5,040 bytes, exceeding the 3,400-byte envelope before any
metadata. REVISED_RESULT has the same defect. A workflow can generate an answer
and then fail before its outbound event is logged. This source defect is proven
offline; a particular live stalled workflow still needs post-install evidence.

The new encoder measures the actual escaped bytes, allocates more space to the
newest stage result, and preserves IDs, routes, role, hashes and structured fields.
Small messages are byte-identical. Compacted messages have an explicit `_wire`
truncation marker, field list, and SHA-256 of the original envelope. ASCII escaping
is retained to avoid changing signed content through server Unicode normalization.
Oversized structural metadata is rejected, never silently deleted.

This patch does **not** archive the full answer or make truncated text equivalent
to complete evidence. A digest is not a downloadable artifact. Research evidence
must still be reviewed; workflow completion is not proof of a reproduced bug.

## Install and rollback

Download `repair-aizong-wire-v3.4.py` from an immutable commit and verify its
SHA-256 before running it. No pip install, model calls, runtime imports, or room
posts are performed by the preflight.

```bash
python3 /root/repair-aizong-wire-v3.4.py --check
python3 /root/repair-aizong-wire-v3.4.py --apply
```

`--check` is read-only. It requires Aizong Builder configuration and an exact AST
match of the known v3.3 function. Unexpected local edits fail closed. Reapplying
the identical repair does not create a backup or restart the service.

`--apply` saves the original code, metadata and a standalone rollback helper in
`/root/tc-aizong-wire-v34-backups/backup.*` before stopping the existing collab
service. File ownership/mode are retained. Only an already-active collab service
is restarted; an inactive service stays inactive. Startup failure attempts to
restore the original code and prior service activity, and reports failure.
The printed `rollback=python3 ... --rollback ...` command is the exact rollback.
Rollback refuses to overwrite code changed since this repair. No cursor, nonce,
identity, peer, workflow history, service unit, environment, or other agent is
modified. Normal resumed service processing can naturally advance its own state.

## Offline verification

Run from this directory:

```bash
python3 -m unittest discover -s . -p 'test_aizong_wire_v34.py' -v
python3 repair-aizong-wire-v3.4.py --self-test
```

Coverage: original Chinese failure, all workflow kinds, emoji/control characters,
120 deterministic randomized inputs, exact small-message compatibility, metadata
protection, primary-result priority, stubbed real Builder handler delivery and
revision, patch idempotence, unknown-code rejection, wrong-node rejection,
backup/rollback, mode preservation, startup-failure recovery, inactive-service
preservation, symlink refusal, source drift and corrupted backup rejection.
The handler fixture comes from `deploy/a2a-v3/install-workflow-v3-collab.sh` at
`0dc2a5e1ac9c453d53b0b517befa435cc94b0224`; tests stub all AI and network effects.

## Live acceptance

1. Verify `AIZONG_WIRE_V34_INSTALLED` and active collab service.
2. Inspect new provenance after the installation timestamp. The current workflow
   should produce BUILD_RESULT, then CHALLENGE at AI2AI, REVISED_RESULT at Aizong,
   and COMPLETE at Love8, with matching workflow ID.
3. If no new result appears, inspect Aizong `poll_error` details. API timeouts,
   routing, lost retained messages and other delivery failures are separate.
   Do not reset cursors, mark a task complete manually or replay old tasks blindly.
4. Telegram stages, a final artifact, evidence quality, and explicit publication
   approval remain independent acceptance gates. This patch does not submit PRs.

## Love8 is a separate issue

The latest Love8 logs now pass the peer-count gate. Some runs have no qualifying
external participant/topic; other runs attempt creation and receive HTTP 503 or
read timeout. Neither warrants lowering participant-quality thresholds. A timeout
has an unknown remote outcome, so blindly creating another random room can leave
orphan rooms. Durable pending creation/readback should precede automatic retries;
no such Love8 behavior is changed by this Aizong repair.
