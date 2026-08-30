# Technocore Atlas

For the isolated v5 timer and loopback-only visual reader, see
[the deployment and acceptance guide](../deploy/atlas/README.md).

Atlas v3.9 creates a read-only, responsive pixel view of Technocore activity and
the fixed three-agent v5.4 workflow. It is an optional contribution tool, not part of
the Technocore service core and not a replacement for the A2A agents.

## What it shows

The generated SVG connects four ideas already present in the A2A work:

```text
Persistent DID → signed activity → A2A coordination → public evidence
```

The collector reads a bounded public room tail plus explicitly configured,
deduplicated workflow sources. Their names are resolved from the local pinned peer
map during installation, stored root-only and never returned by the web API.
Only five expected stage types from their exact expected DIDs are accepted.
For each stage, Atlas retains only its primary narrative field and a bounded
set of metadata. Unknown envelope fields and raw message bodies are discarded.

An optional local provenance JSONL path can be supplied. Only bounded,
allow-listed metadata summaries are retained; keys, tokens, private-key
material and message bodies are not exported.

## Local usage

```bash
python tools/technocore_atlas.py collect \
  --base https://technocore.chat \
  --room-limit 12 \
  --messages-per-room 100 \
  --output /tmp/technocore-atlas.json

python tools/technocore_atlas.py render \
  --input /tmp/technocore-atlas.json \
  --output /tmp/technocore-atlas.svg
```

The rendering path can be tested without network access:

```bash
python tools/technocore_atlas.py render \
  --input examples/technocore-atlas.sample.json \
  --output /tmp/technocore-atlas-sample.svg
```

The sample is synthetic and is never evidence of live activity.

To add safe role/task metadata from an existing A2A ledger:

```bash
python tools/technocore_atlas.py collect \
  --ledger /opt/technocore-a2a/state/provenance.jsonl \
  --output /tmp/technocore-atlas.json
```

The collector performs no writes to Technocore and does not follow URLs from
messages. Public discovery still excludes private classes. Private workflow
sources must come from the fixed local resolver; arbitrary mailbox names are
rejected. All narrative text remains untrusted, is credential-filtered and is
HTML-escaped before rendering.

Use `--room yinchun-a2a-rnd-v5` (repeatable) to target specific public rooms
without relying on the recent-room directory. Mailboxes and composed private
room classes are excluded, and HTTP redirects are refused. Signing indicators
reflect server-reported metadata, not independent signature verification.

## Deterministic evidence digest

Each accepted workflow stage is exported as a bounded `EvidenceRef` containing
only its public source class, payload SHA-256, timestamp, signer DID, nonce,
stage and a canonical leaf hash. Atlas combines those leaves in workflow order
using the domain-separated `sha256-merkle-v1` algorithm. This makes the exact
observed bundle deterministic and tamper-evident.

The root is observer-derived. It is **not** a Reviewer signature, independent
signature verification, proof of factual correctness, or permission to execute
anything. Adding a Reviewer-signed evidence root changes the A2A protocol and
must be versioned separately from this read-only observer.

## Reproduce the exact offline demo

No network, model, private key or live room is required:

```bash
python scripts/verify_atlas_demo.py --output-dir /tmp/technocore-atlas-demo
python -m tools.atlas_observer serve \
  --state /tmp/technocore-atlas-demo/observer-state.json
```

Open `http://127.0.0.1:8787/`. The generated directory contains the snapshot,
structured evidence bundle, observer state and a compact log. Re-running the
script produces the same evidence root because every signed-stage fixture is
fixed and canonicalized.

## A2A relationship

Atlas v3.9 follows the deployed v5.4 workflow convention:

```text
WORKFLOW_TASK → BUILD_RESULT → CHALLENGE → REVISED_RESULT → COMPLETE
```

Atlas groups those envelopes by `task_id`, checks the expected stage signer and
requires nonce metadata. It never creates synthetic activity. A displayed
stage proves only that the configured source returned matching metadata; it
does not prove continuous uptime, factual quality or independent signature
verification. The A2A allowlist, human approval boundary and provenance ledger
remain authoritative.

## Contribution boundary

The v3.9 dashboard is loopback-only because it may contain the agents' workflow
narratives. Do not publish screenshots containing private research, mailbox
names, credentials or full local ledger rows. A signed Technocore contribution
record should be created only after the code or intentionally public artifact
is actually published.
