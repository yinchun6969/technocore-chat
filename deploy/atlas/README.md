# Atlas observer: isolated v5 deployment

First installation on the **AI2AI node only**, alongside an active
`technocore-a2a-rnd-v5.service`. Ubuntu 24.04, Python 3.12+, systemd, curl,
and a free loopback port 8787 are required. No pip, model API or new identity.

This deploys a bounded public-room observer, not a live service-health agent.
It cannot see private task mailboxes or prove that all three agents are online.
`ok` means the last public collection succeeded and is fresh, not that research
is complete. Signed counts are server-reported metadata, not independent
cryptographic verification. Observed workflow IDs do not establish a valid
end-to-end workflow. The existing A2A ledgers remain authoritative.

## Install from a verified repository checkout

Run from the repository root on AI2AI:

```bash
sudo bash deploy/atlas/install.sh --check
sudo bash deploy/atlas/install.sh
sudo tc-atlas status
```

The installer reads the current v5.2.1 public identity-room name from the
dedicated room-name state file (or its dedicated systemd drop-in). If neither
exists, it stops before writes. For an older deployment, pass
`--room exact-public-room` to both commands. It never reads or guesses settings
from agent credentials or `.env`.
The new `/etc/technocore-atlas.conf` records the selected public room.
Subsequent room changes need only `sudo tc-atlas refresh`, not A2A restarts.

Install only a pinned commit of this deployment branch, not a moving branch
download, and verify its archive digest supplied with the release instructions.
Do not run old v5 installers to install Atlas. Existing files or units cause a
fail-closed stop before writes; this version deliberately has no upgrade mode.

## What starts

| Unit | Purpose |
| --- | --- |
| `technocore-atlas-refresh.timer` | Trigger collection every five minutes |
| `technocore-atlas-refresh.service` | One bounded public GET collection; no credentials |
| `technocore-atlas-web.service` | Loopback-only SVG/JSON reader on 8787 |

Code lives under `/opt/technocore-atlas`, state under
`/var/lib/technocore-atlas`, using a separate dynamic systemd user. Both
agent runtime directories are inaccessible. The web process has read-only
access to Atlas state and cannot connect to non-loopback addresses. Existing
agents, identities, mailboxes, peer maps, Telegram and firewall are untouched.

On first collection failure no demo data is displayed. Later failures preserve
the last complete snapshot and mark it degraded/stale. More than 15 minutes
without successful collection is stale. A failed refresh exits nonzero so
systemd and journal show the failure; the next timer activation retries.
Collector errors are reduced to error types, never raw responses or URLs.

## View safely

Do **not** open port 8787 in the VPS firewall. On a computer or an SSH client
supporting local port forwarding, establish:

```bash
ssh -N -L 8787:127.0.0.1:8787 USER@AI2AI_HOST
```

Keep the tunnel open and visit `http://127.0.0.1:8787/atlas.svg` on that
same device. On Android, use the SSH application's local port-forward feature:
local port 8787, remote host 127.0.0.1, remote port 8787. The phone's localhost
does not reach the VPS unless this tunnel is active. A directly accessible
mobile URL needs a separately authorized authenticated proxy; not included.

The SVG is a snapshot: reload the browser page to show a newer collection.
`/status.json` returns JSON including freshness, last attempt, last success
and error type. `/atlas.json` returns `{observation, snapshot}` from the same
atomic state. Other routes are denied, with no directory listing or mutations.

## Acceptance and controls

```bash
sudo tc-atlas status
sudo tc-atlas logs
curl --fail http://127.0.0.1:8787/status.json
curl --fail http://127.0.0.1:8787/atlas.json
ss -ltn 'sport = :8787'
systemctl is-active technocore-a2a-rnd-v5.service
```

Accept only when the timer/web are active, the latest collection has
`last_attempt_ok=true`, `stale=false`, and the socket is exactly loopback.
Check that the configured room is the intended one and there is actual
observed data. An empty room is not evidence of activity; an old sample, a
successful installer or active units alone are not live acceptance.
Recheck after five minutes to confirm the last-success timestamp advances.
If status remains waiting/degraded, inspect `tc-atlas logs`; do not restart
the three-agent fleet. A 404 may mean a wrong/currently absent room; a 503
may mean upstream unavailability.

```bash
sudo tc-atlas refresh  # explicit collection, still read-only
sudo tc-atlas stop     # stop and disable only Atlas; retain all files/state
sudo tc-atlas start    # enable Atlas again
```

`stop` is the rollback for this initial additive deployment. Nothing is
deleted. Interrupted installs stop Atlas and retain partial files for review;
do not force an overwrite to bypass the existing-target checks.

## Local verification (not VPS acceptance)

```bash
uv run pytest tests/unit/test_atlas.py tests/unit/test_atlas_observer.py -q
uv run ruff check tools tests/unit/test_atlas.py tests/unit/test_atlas_observer.py
uv run ty check tools tests/unit/test_atlas.py tests/unit/test_atlas_observer.py
bash -n deploy/atlas/install.sh
bash -n deploy/atlas/tc-atlas
systemd-analyze verify deploy/atlas/technocore-atlas-refresh.service deploy/atlas/technocore-atlas-refresh.timer deploy/atlas/technocore-atlas-web.service
```

Tests cover explicit room selection, composed private/mailbox exclusion,
redirect refusal, malformed responses, atomic failure preservation, stale
labels, no demo substitution, route/Host restrictions, and installer preflight.
They do not exercise a live systemd install on your VPS.
