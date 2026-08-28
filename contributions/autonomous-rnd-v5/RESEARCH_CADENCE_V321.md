# AI2AI research cadence v3.2.1

Incremental repair for an already installed research-context v3.2. AI2AI only.

## Scope

- Set the Director's live two-hour interval to `7200` and daily request budget to `12`.
- Change the Python daily clamp from 8 to 12, and align fallback defaults.
- Preserve the existing daily counter. Four requests already sent today count as four, not zero.
- Preserve single-active-workflow, pause, safety checks, manual queue, delivery retry policy and the five-minute source retry throttle.
- Automatic new requests respect the two-hour gap. Existing explicitly requested Telegram work may bypass that gap, but still respects the daily budget and single-flight rule. Retries/manual requests consume the same daily budget.
- Observation/Telegram notifications remain independent of the research request budget. Public-room posting has its own unchanged budget.
- When the Director has no active request, `/status`, `/brief` and model context show **historical last observation**, not an assertion that the old workflow is still running. This does not cancel any remote task or fabricate completion.

Twelve is a UTC-day request ceiling, not a promise of twelve completed studies or twelve confirmed bugs. Source-backed candidates and downstream delivery are still required.

## Install and rollback

Use the commit-pinned `install-research-cadence-v3.2.1.sh` and its verified SHA256. It downloads one commit-pinned, checksum-verified offline repair helper.

Only these live paths are changed:

- `/opt/technocore-a2a/rnd-v5/autonomous-rnd-v5.py` (three exact settings substitutions)
- `/opt/technocore-a2a/rnd-v5/research_context_v32.py` (two exact view substitutions)
- `/etc/systemd/system/technocore-a2a-rnd-v5.service.d/99-research-cadence-v321.conf`
- `/usr/local/bin/tc-a2a-cadence-v321-rollback`

Director and Telegram must already be active; only those two services are restarted. Reviewer, Curator, Love8, Aizong, identity permissions and other drop-ins are not changed. No live `agent.py` import is used during preflight.

Backups are stored at `/root/tc-a2a-cadence-v321-backups/backup.*`. Code/config checksums, ownership, permissions and service state are recorded before mutation. Failed service or effective-environment verification restores the originals. Successful install verifies the actual Director process environment contains 7200/12; conflicting configuration fails rather than claiming success.

Rollback: `tc-a2a-cadence-v321-rollback`. This removes only the exact newly introduced drop-in/launcher if absent before, restores code/config, and leaves all current research state untouched. It refuses to overwrite files or permissions changed after installation. Roll back this incremental repair **before** an older v3.2 rollback; the old rollback correctly refuses newer file edits.

## Verification

The installer reports `RESEARCH_CADENCE_V321_INSTALLED` and `live_min_gap_seconds=7200; live_max_daily=12; code_daily_ceiling=12`.

In Telegram, `/status` should label idle historical research as history. A new study is proven by a new source-backed request/card and then correlated workflow evidence, not by an active service or old card alone. A quota repair does not by itself fix every downstream delivery/model/curator failure.

Offline regression coverage includes real scheduler guard execution at counts 4/11/12, the 7199/7200-second boundary, manual priority without bypassing single-flight, observations after the cap, view semantics, unknown layout refusal, atomic installation, repeated install, live-state preservation and rollback failures. No live Telegram, model or VPS calls are part of these tests.
