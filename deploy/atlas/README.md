# Atlas v2 workflow observer: isolated v5 deployment

First installation on the **AI2AI node only**, alongside an active
`technocore-a2a-rnd-v5.service`. Ubuntu 24.04, Python 3.12+, systemd, curl,
and a free loopback port 8787 are required. No pip, model API or new identity.

Atlas v2 renders a mobile-first workflow dashboard: the three fixed roles,
five signed workflow stages, stage progress and allow-listed narrative fields.
It is an observation tool, not a live service-health agent. It cannot prove
that all three agents are online. `ok` means the configured observations are
fresh, not that research claims are correct. Sender DID and nonce are checked,
but server-returned signature metadata is not independent cryptographic
verification. The existing A2A ledgers remain authoritative.

## Install from a verified repository checkout

Run from the repository root on AI2AI:

```bash
sudo bash deploy/atlas/install.sh --check
sudo bash deploy/atlas/install.sh
sudo tc-atlas status
```

The installer reads the current v5 public identity-room name from the
dedicated room-name state file (or its dedicated systemd drop-in). If neither
exists, it stops before writes. For an older deployment, pass
`--room exact-public-room` to both commands. It also reads only the two required
DID-to-mailbox values from the existing pinned `state/peers.json`; it never
loads agent credentials, private keys or `.env`.
The root-only `/etc/technocore-atlas.conf` records the public room and three
fixed workflow sources (`d-aizong` plus the two pinned peer mailboxes).
Subsequent room changes need only `sudo tc-atlas refresh`, not A2A restarts.

Install only a pinned commit of this deployment branch, not a moving branch
download, and verify its archive digest supplied with the release instructions.
Do not run old v5 installers to install Atlas. Existing files or units cause a
fail-closed stop before writes. An existing Atlas v1 must use the dedicated,
backup-first upgrade:

```bash
sudo bash deploy/atlas/upgrade-v2.sh
```

## What starts

| Unit | Purpose |
| --- | --- |
| `technocore-atlas-refresh.timer` | Trigger collection about every 30 seconds |
| `technocore-atlas-refresh.service` | Bounded GETs from one public room and fixed workflow sources; no credentials |
| `technocore-atlas-web.service` | Loopback-only HTML/SVG/JSON reader on 8787 |

Code lives under `/opt/technocore-atlas`, state under
`/var/lib/technocore-atlas`, using a separate dynamic systemd user. Both
agent runtime directories are inaccessible to both Atlas services. The
installer copies only validated room names into the root-only Atlas config.
The web process has read-only
access to Atlas state and cannot connect to non-loopback addresses. Existing
agents, identities, mailbox contents, peer maps, Telegram and firewall are
never modified.

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

Keep the tunnel open and visit `http://127.0.0.1:8787/` on that
same device. On Android, use the SSH application's local port-forward feature:
local port 8787, remote host 127.0.0.1, remote port 8787. The phone's localhost
does not reach the VPS unless this tunnel is active. A directly accessible
mobile URL needs a separately authorized authenticated proxy; not included.

The v2 HTML dashboard refreshes itself every 30 seconds. It shows only the
primary field for each accepted stage: `goal`, `build_result`, `challenge`,
`revised_result`, or `final_summary`. Unknown fields, invalid senders, unsigned
messages, unrelated chat and credential-shaped text are excluded or redacted.
`/atlas.svg` retains the v1 overview for compatibility.
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
Recheck after about one minute to confirm the last-success timestamp advances.
If status remains waiting/degraded, inspect `tc-atlas logs`; do not restart
the three-agent fleet. A 404 may mean a wrong/currently absent room; a 503
may mean upstream unavailability.

```bash
sudo tc-atlas refresh  # explicit collection, still read-only
sudo tc-atlas stop     # stop and disable only Atlas; retain all files/state
sudo tc-atlas start    # enable Atlas again
```

`stop` disables Atlas without deleting code or state. The v1-to-v2 upgrader
creates a timestamped backup under `/opt/technocore-atlas/backups` and restores
v1 automatically if a local upgrade step fails. It never restarts A2A or TG.

## Local verification (not VPS acceptance)

```bash
uv run pytest tests/unit/test_atlas.py tests/unit/test_atlas_observer.py -q
uv run ruff check tools tests/unit/test_atlas.py tests/unit/test_atlas_observer.py
uv run ty check tools tests/unit/test_atlas.py tests/unit/test_atlas_observer.py
bash -n deploy/atlas/install.sh deploy/atlas/upgrade-v2.sh
bash -n deploy/atlas/tc-atlas
systemd-analyze verify deploy/atlas/technocore-atlas-refresh.service deploy/atlas/technocore-atlas-refresh.timer deploy/atlas/technocore-atlas-web.service
```

Tests cover explicit room selection, pinned-source resolution, expected signer
checks, stage deduplication, field allow-listing, credential redaction, HTML
escaping, composed private/mailbox exclusion, redirect refusal, malformed
responses, atomic failure preservation, stale labels, no demo substitution,
route/Host restrictions, and installer preflight.
They do not exercise a live systemd install on your VPS.
