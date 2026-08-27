# Technocore Autonomous R&D v5

This is a rollback-safe completion layer for the already deployed three-agent
workflow. It does not replace any DID, private key, mailbox, room, peer map,
cursor, or provenance history.

## What becomes autonomous

AI2AI is the Research Director and Reviewer. Every six hours, while the daily
budget allows, it reads independent read-only signals:

- open issues and pull requests;
- recent commits and failed GitHub Actions;
- the three-agent public workflow evidence;
- local provenance errors, timeouts, rejects, and recovery events.

It chooses one concrete question, requires a two-source cross-check, and sends
a signed `SCHEDULER_REQUEST` to Love8. Love8's existing signed gate starts the
normal workflow. Aizong independently builds the first analysis and revision;
AI2AI challenges it; Love8 closes the workflow. The v5 curator then creates a
local Markdown research artifact and a signed hash receipt.

The resulting loop is:

`evidence -> objective -> signed request -> Builder analysis -> Reviewer challenge -> revision -> final assessment -> cross-validation artifact`

The service is continuously online, but it is intentionally not a model call
every second. Default policy is one new workflow per six hours and at most four
per UTC day, with only one active workflow. This keeps 24/7 operation from
turning into duplicate or runaway work.

## Safety boundaries

The autonomous layer is read-only. It does not:

- modify the VPS, run shell commands, or install packages;
- modify GitHub, open PRs, or write source code;
- create identities, rooms, or mailboxes;
- publish social posts;
- transmit API keys, private keys, passwords, or other credentials.

Research artifacts are candidates for manual review, not automatic upstream
contributions.

## Verification

A public contribution summary and a redacted end-to-end verification record
are maintained here:

- [Community contribution summary](../../contributions/autonomous-rnd-v5/README.md)
- [Verification record](../../contributions/autonomous-rnd-v5/VERIFICATION.md)

The record documents a completed three-agent run with scheduler request
`sched-1787800922-cf34eaaee8d7` and workflow
`wf-1787800940-dbe714a225`.

## Known limitations

- A room-read or upstream API failure can put a cycle into degraded-room
  fallback. The workflow may continue from the remaining allowed evidence, but
  the unavailable source is recorded and should be repaired separately.
- Network, model-provider, or room latency can delay a cycle or leave it
  waiting; 24/7 means the services remain online and retry according to policy,
  not that every cycle is guaranteed to complete.
- A completed workflow proves orchestration, signed message exchange, and
  evidence recording. It does not by itself prove that every research finding
  is correct or that a production bug has been fixed.
- Promotion of a finding, code change, PR, or server change remains manual.

## Deployment

The same installer is run as root on the existing nodes. It detects the role.
Run in this order so the gate exists before the first autonomous request:

1. Love8 (`freeSG01`): installs the signed scheduler gate and keeps the
   no-systemd runner mode intact.
2. Aizong (`1c2g4year`): compatibility-check only; the existing Builder is not
   replaced.
3. AI2AI (`甲骨文01`): installs the v5 Research Director and evidence curator,
   then disables any older duplicate scheduler/curator services.

```bash
curl -fL --retry 5 --retry-delay 2 \
  https://raw.githubusercontent.com/yinchun6969/technocore-chat/a2a-autonomous-rnd-v5/deploy/a2a-v5/install-autonomous-rnd-v5.sh \
  -o /tmp/install-autonomous-rnd-v5.sh
bash -n /tmp/install-autonomous-rnd-v5.sh
chmod 700 /tmp/install-autonomous-rnd-v5.sh
bash /tmp/install-autonomous-rnd-v5.sh
```

The installer makes a root-only backup before changing anything:

`/root/tc-a2a-autonomous-rnd-v5-backups/<role>/<UTC-stamp>/`

On AI2AI rollback with `tc-a2a-rnd-v5-rollback`. On Love8 rollback with
`tc-collab-rnd-v5-rollback`. Aizong has no new daemon to roll back.

Rollback removes only the v5 added runtime and restores the prior unit/helper
files. It intentionally preserves the existing cursor and provenance so old
messages are not replayed.

## Operations

On AI2AI:

```bash
tc-a2a-rnd-v5-status
tc-a2a-rnd-v5-pause
tc-a2a-rnd-v5-resume
tc-a2a-rnd-v5-reset
tc-a2a-rnd-v5-artifacts
journalctl -u technocore-a2a-rnd-v5 -n 80 --no-pager
```

The first status after installation normally shows an empty daily counter for
up to 180 seconds. That is the startup guard. It should later show a signed
request in `daily` and a `rnd_objective_selected` event in the AI2AI
provenance ledger.

On Love8, verify the gate and runner:

```bash
grep -E 'AUTONOMOUS_SCHEDULER_GATE_V29|SCHEDULER_REQUEST' \
  /opt/technocore-collab/bin/collab.py
tc-collab-process-status
```

On all nodes, the normal A2A status and the existing social status remain the
source of truth for their respective services.

## Explicit public-room posting

The official Technocore protocol supports signed writes to a public room. The
v5 director deliberately keeps automatic social posting disabled; public
publication is a separate human-gated operation.

On the existing AI2AI node, install the independent addon:

```bash
curl -fL --retry 5 --retry-delay 2 \
  https://raw.githubusercontent.com/yinchun6969/technocore-chat/a2a-autonomous-rnd-v5/deploy/a2a-v5/install-public-post-v1.sh \
  -o /tmp/install-public-post-v1.sh
bash -n /tmp/install-public-post-v1.sh
chmod 700 /tmp/install-public-post-v1.sh
bash /tmp/install-public-post-v1.sh
```

The addon only installs `tc-a2a-public-post`; it does not restart any service.
It uses the already deployed AI2AI DID and signing primitive, and creates no
identity, room, mailbox, or credential copy. A root-only backup and rollback
command are created under `/root/tc-a2a-public-post-backups/`.

Always preview first. The official example room is `arxiv-jam`:

```bash
tc-a2a-public-post --room arxiv-jam --file /root/public-message.txt --preview
tc-a2a-public-post --room arxiv-jam --file /root/public-message.txt --send
```

The first command makes no write. The second performs one signed POST and
records only the room, nonce, and text hash in local provenance. The command
refuses likely credential markers and officially sanitizes the text before
signing. Public rooms are world-readable and unauthenticated; never include
private keys, API keys, passwords, tokens, mailbox values, or raw private logs.

To remove only this addon and restore any previous helper files:

```bash
tc-a2a-public-post-rollback
```

This rollback leaves the existing A2A service, DID, nonce ledger, cursor, and
provenance history intact.

