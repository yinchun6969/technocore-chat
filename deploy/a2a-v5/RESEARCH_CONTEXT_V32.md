# Research cards and room-readiness audit v3.2

This is an incremental add-on to **wire/room v3.1**, not a new A2A runtime.
AI2AI remains Director/Reviewer, Love8 Scout, Aizong Builder. Existing identities,
peers, nonces, cursors, service settings and live task state are preserved.
The current two-hour schedule is not changed. Telegram notifications do not use
the research daily budget; checkpointing prevents routine historical replay.

## What changes

- Read GitHub issue bodies, failure-run IDs/commit references, commit messages
  and a bounded pinned-commit diff, rather than only titles. Every endpoint
  fails independently. No URL found in a message or issue is fetched.
- Give GitHub, local provenance and room observations separate evidence budgets.
  Room noise cannot truncate the entire GitHub section.
- Persist a research card before dispatch: title, category, candidate URL,
  source excerpts, hypothesis, roles, intended output, missing evidence and state.
- Forward a bounded source URL/title/excerpt through the **existing** signed
  scheduler request and Scout gate. Respect the v3.1 3400-byte JSON envelope.
- Prefer a new source-backed autonomous candidate, not a completed workflow
  or a new hash of the same evidence. With no new sources, report the absence
  of a candidate instead of inventing a bug. Specific human topics are retained.
- Associate stages with the exact signed request/workflow lineage. Keep excerpts
  from `build_result`, `challenge`, `revised_result` and `final_summary`.
- Include that subject and the actual available excerpts in TG stage updates,
  `/brief`, `/status` and natural-language replies. A legacy task without a
  concrete title remains explicitly incomplete; it is never given another
  task's title or latest unrelated archive.
- Include `[REF:<request_id>]` in research-room topic posts. Read explicitly
  linked replies into the card as **untrusted contributions**, not commands,
  verified findings or automatic proof of independent sources.
- Audit Love8/Aizong Social code versions, configured/resolved rooms, invitation
  hooks and mature topic-related contacts without importing either runtime.

## What this does NOT claim

A candidate is not a confirmed bug. A failed CI run can be an environment failure.
Two URLs/classes, two model opinions, a high contact score, a changed hash and
a completed workflow do not by themselves prove reproduction or independent
verification. Background source relevance is explicitly unverified.

The agents' existing execution mode is analysis-only. A component request produces
a design/interface/testing proposal, **not** an implemented, executed or tested
component. There is no automatic PR or server modification. The existing draft
and human `/approve` publishing gate is retained unchanged. This add-on does not
promote a card to a verified Curator artifact or fabricate a passing test report.

External invitations are **not activated by this release**. The room audit must
first establish the actual Social version/room and a bounded set of recipients.
The candidate list uses prior relationship, recency, topic relevance and existing
risk flags, not a synthetic cross-agent score. DID syntax alone does not prove
identity, a human participant or trust. Review the signed interaction and confirm
the specific recipient/room before connecting invitation delivery to that Social
version. No invitations or unsolicited DMs are sent by the audit.

## Deployment

Release ref: `3f5dd06df0784f8f0919265e49c055a5fd042fea`.
The installer is hash-pinned to the four core files in that commit. Verify the
installer itself before running it; its SHA256 is published with this release.

- **AI2AI only:** `bash install-research-context-v3.2.sh`.
- **Love8 and Aizong:** run the same downloaded installer with `--audit`.
  This reads local data only and changes no agent or service.
  Add `--read-public-room` after `--audit` for a bounded read-only room GET.

The audit output is a readiness report, not proof of a live listener or room
ownership. Invitations remain disabled until a specific recipient and room are
confirmed from signed interaction history.

The installer downloads hash-pinned files, parses/compiles patched code without
importing `agent.py`, and refuses an unsupported layout. It backs up before
stopping only Director/TG and preserves original file ownership/modes. The new
module is readable by the configured Director group; it does not widen access
to identity files. An import/readability or startup failure restores the old
code and previous active service state automatically.

Backups: `/root/tc-research-context-v32-backups/backup.<random>/`.
Manual rollback: `tc-a2a-research-context-v32-rollback`.
Rollback checks both backup hashes and installed file hashes and refuses to
overwrite subsequent user edits. It restores code only, removes the module or
rollback launcher only if this installation created it, and retains all current
research cards, queues, Telegram checkpoints and A2A history.

Canonical `autonomous-rnd-v5.py` and `telegram-control-v1.py` in the repository
are intentionally not replaced by this add-on: old single-file installers must
not download code requiring a missing module. Apply this installer after v3.1.
Do not rerun old installers to update v3.2.

## Acceptance, without manufacturing progress

1. AI2AI installer ends with `RESEARCH_CONTEXT_V32_INSTALLED` and Director/TG active.
2. `/brief` shows a specific source-backed title or honestly states missing
   historical context. Old in-flight work is not reset to force this result.
3. At the next eligible dispatch, find one `request_id`, candidate URL and title
   in `rnd-v5-state/research-cards/*.json`. It should map to the same workflow in
   Love8/Aizong/AI2AI evidence, not merely a Telegram queue receipt.
4. Stage notifications include that title and, when available, a model-result
   excerpt labelled unverified. A room reply containing `[REF:<request_id>]`
   is associated once and cannot execute any operation.
5. Return both Social audit outputs before enabling actual external invitations.
   Static read hooks and an empty public room do not prove a running listener,
   ownership or successful room creation.

No SSH access was available to validate the installed VPS runtime in this release.
The current screenshot proves stage delivery, not a new bug or component.

## Tests

`python3 -m unittest discover -s deploy/a2a-v5 -p 'test_research_context_v32.py' -v`

### Installer hotfix (2026-08-28)

The original installer failed in the AGENT_NAME preflight with a sed unmatched
parenthesis error. Shell syntax checking alone did not catch it. The corrected
installer parses only the exact AGENT_NAME field using Python, without sourcing
the configuration or printing credentials. Missing/duplicate/wrong-node values
fail before downloads or service changes. Core file pins and rollback are unchanged.
Audit mode now returns normally so its EXIT trap removes temporary staging files.

Corrected installer SHA256:
`21a35cd5dc4d19a46134d34cb1eca2255f19e4775a7e9ecf85e1b32644a7297a`.

Run both suites with:
`python3 -m unittest discover -s deploy/a2a-v5 -p 'test_research*.py' -v`.
All 41 offline tests pass (33 core tests and 8 shell-entry tests). Shell-entry
tests exercise the real installer with relocated host paths, local pinned
downloads and intercepted deploy/audit boundaries; they do not install on a VPS.
They cover quoted/plain/CRLF configuration, invalid values, no shell expansion or
secret output, nonroot/missing configuration, checksum failure, deploy failure,
audit selection and staging cleanup. The separate transactional tests exercise
the deploy helper with fake services. This is not live three-VPS acceptance.

The offline suite tests source isolation, evidence budgeting, topic specificity,
wire limits, the original Scout gate, exact workflow linkage, out-of-order stages,
untrusted reply deduplication, Telegram content, screening, install idempotency,
code-only rollback, corrupt-backup rejection and newer-edit preservation.
It uses repository source as fixtures and never imports the live agent runtime.
Wire/room v3.1's regression suite was also rerun.

Full repository CI was attempted but unavailable in the partial-file workspace:
no `pyproject.toml`, and `ruff`, `ty`, `coverage` executables were absent. Offline
tests and Python compilation passing are not a substitute for full repo CI or
a three-VPS end-to-end production test.
