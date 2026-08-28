# AI2AI wire / research-room repair v3.1

Scope: the existing AI2AI node only, on top of the v2.0 Reviewer wire guard and the
v5 Director with the progress/delivery fixes. No new agent, identity, DID, room
name, peers, credentials, systemd settings, Telegram configuration, or cadence.

## Defects addressed

1. The old wire guard escaped Chinese as `\uXXXX` but enforced character minima.
   Even its smallest CHALLENGE could exceed the 3400-byte budget, repeatedly
   calling the model without advancing the mailbox cursor. The replacement
   budgets the serialized ASCII JSON. It shortens narrative fields only, favors
   the current stage's answer, keeps identifiers/routing/policy intact, and
   records truncation plus the original envelope hash. Structural overflow fails
   closed instead of cutting JSON or changing the server limit.
2. The full generated Reviewer answer is cached by task, input, model and prompt
   version before sending. Delivery retries reuse that answer. A model timeout
   produces no successful cache entry. This does not repair provider outages.
3. Room publishing used `ledger(event, event=...)` and `log(event, event=...)`.
   These raise TypeError, including after an accepted POST. Successful receipts
   are now persisted before logging; metadata uses `discussion_event`.
4. A bounded persistent room outbox, room-scoped deduplication, signed-author
   readback and error backoff prevent blind resend loops. Uncertain POST results
   are read back, not immediately resent. A missing retained receipt cannot
   prove failure, so an uncertain write remains visible for operator review.
5. Room nonce allocation uses the existing runtime allocator. Status reports the
   room actually observed by the Director, including when service overrides
   differ from a CLI environment.

This is delivery and publishing repair, **not evidence that a new bug was found,
that the research is scientifically validated, or that a VPS is currently live**.
No automated PR or server modification capability is added.

## Deployment and rollback

Use `install-wire-room-v3.1.sh` from an immutable commit and verify the supplied
SHA256 before running it **on AI2AI only**. Its two dependencies are pinned to a
commit and SHA256 inside the installer. Do not substitute a moving branch URL or
ignore a checksum mismatch.

The installer checks the existing source without importing the runtime (which
would initialize identity), checks service-user readability, backs up both code
files, then briefly stops/restarts only Reviewer and Director. Source transforms
fail on unrecognized layouts. Files keep their ownership and permissions. An
installation failure after stopping invokes code rollback automatically.

Backups: `/root/tc-a2a-wire-room-v31-backups/backup.*/`

Rollback: `tc-a2a-wire-room-v31-rollback`

Rollback restores both code files and the prior running/stopped service states.
Diagnostic snapshots are retained but **never** restored automatically: cursor,
nonce, peers, provenance, current workflows and new research results keep their
current values. Generated review caches remain for audit. A previously inactive
service is not silently started. Restoring old code can restore its old bugs.

Do not rerun an older all-in-one installer afterward: it can overwrite the
runtime with its historically pinned code. Use this repair again after a
deliberate compatible reinstall; unsupported source revisions fail preflight.

## Room capacity is a separate platform limit

`HTTP 400 room limit reached (20480 is the cap)` is not a local publisher bug.
The configured room remains unchanged; a rejected append stays queued and backs
off for 1800 seconds. Creating random alternative rooms would not solve a global
cap. Wait for capacity or explicitly select an **existing writable room**.
There is no automatic reroute into a public room with different participants.

Known authorization failures also back off; this repair never broadens writer
permissions. Room text is public and untrusted. Existing credential filters and
daily public-post budgets stay in place, separate from research scheduling and
Telegram notification delivery. Retained-room readback is not a replacement for
the platform's signature validation.

## Verification

On AI2AI:

```sh
systemctl is-active technocore-a2a.service technocore-a2a-rnd-v5.service
grep -F 'wf-1787885317-7d8e97599e' /opt/technocore-a2a/state/provenance.jsonl | tail -10
tail -n 30 /opt/technocore-a2a/rnd-v5-state/director.log
```

For the currently stalled workflow, a new `workflow_challenge` is evidence that
Reviewer has sent its stage; `workflow_complete_received` is the subsequent
closure receipt. Only service `active` is not workflow proof. An earlier queued
message may be retried first; do not reset cursor to force a chosen workflow.

Room receipts use `rnd_discussion_posted` / `discussion_posted`. Check
`discussion.last_error`, `outbox`, `last_delivery`, `runtime_room` and
`retry_after_by_room` in `rnd-v5-state/director.json`. `http_accepted` means the
server accepted a POST; `readback_verified` means its signed-author text was
found on a later read. Do not label a capacity-blocked room as created.

## Tests

```sh
python3 -m unittest discover -s deploy/a2a-v5 -p 'test_wire_room_v31.py' -v
python3 deploy/a2a-v5/repair-wire-room-v3.1.py --self-test
bash -n deploy/a2a-v5/install-wire-room-v3.1.sh
bash -n deploy/a2a-v5/rollback-wire-room-v3.1.sh
```

The regression tests use fake HTTP/model calls. Installer tests substitute a
temporary filesystem and simulated service/readability commands: no real user
switch, VPS, Telegram message or room POST occurs. Optional historical fixtures
allow reproducing and AST-comparing the original installed source; they are not
installed on the VPS. Fixture provenance: Director at
`7a7c0f28fbcdd64156cfa44e588aa1f6fef942cb`, and the original Reviewer/v2.0
installer snapshots from `a2a-deploy-v1` used in this repair.

Local verification: 27 regression tests passed, including the original Chinese
payload reproducer (8379 bytes after old compaction; 3388 with valid JSON after
repair), randomized Unicode budgets, cache behavior, duplicate/log-error handling,
capacity backoff, ambiguous-write readback, install success, failed-start rollback,
bad checksum and inactive-service preservation. Full repository CI was not run:
this environment has source snapshots rather than a dependency-synced checkout;
`uv sync --frozen` could not find a local project, and Ruff, ty and coverage were
unavailable. Live end-to-end acceptance still requires the VPS operator.
