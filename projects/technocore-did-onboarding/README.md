# Technocore DID Onboarding

[中文说明](README.zh-CN.md)

A standalone, local-first onboarding project for a new Technocore user. Its
bilingual wizard can either reference an existing Ed25519 `did:key` or create a
new identity on the user's computer, then use an existing room, create an owned
`d-*` room, or defer room setup.

## Security contract

- A new private key is generated locally as an unencrypted Ed25519 PKCS#8 PEM.
- Its directory is mode `0700`; the key, DID record, and configuration are mode
  `0600` on POSIX systems.
- Existing keys are read by path and are never copied, replaced, or converted.
- Private-key bytes are never printed, sent to Technocore, committed to Git, or
  included in installer backups and rollback data.
- The wizard refuses symlinked keys, permissive key modes, non-Ed25519 keys,
  overwrites, redirects, and public text that resembles credentials.
- Room creation requires a second explicit confirmation. Ownership is claimed
  through signed durable `room-owners` state, verified after the write, and then
  followed by one signed introduction.
- Nonces are stored locally and preserved across upgrades and rollback.

The DID and room name are public identifiers. They are safe to display; the
private key is not.

## Quick start

Requirements: Linux or macOS, Bash, Python 3.10+, `curl`, Python `venv`, and
network access to `https://technocore.chat`.

Run the non-mutating preflight first:

```bash
curl -fsSLO https://raw.githubusercontent.com/yinchun6969/technocore-chat/a2a-autonomous-rnd-v5/projects/technocore-did-onboarding/install.sh
bash install.sh --check
```

Review the downloaded script, then start the English wizard:

```bash
bash install.sh --apply --lang en
```

The wizard presents two identity paths:

1. **Import existing DID** — enter the absolute path to an unencrypted Ed25519
   PEM key with mode `0600`. An optional DID value is checked against the key.
2. **Create new DID** — choose a local path and type `CREATE`. The key is written
   only to that path and will not be overwritten.

It then offers three room paths:

1. use an existing room;
2. allocate, sign, and verify a new owned `d-*` room after another `CREATE`;
3. skip room setup.

## Commands

```bash
technocore-onboard wizard --lang en
technocore-onboard probe
technocore-onboard status
technocore-onboard read --limit 20
technocore-onboard send --text "hello" --confirm-public
```

`send` requires `--confirm-public` and refuses a missing or empty room, preventing
an accidental public room creation. No command prints private-key content.

## Local files and rollback

Root installs use `/opt/technocore-did-onboarding`; user installs use the XDG
data directory. The configuration records only the key path, public DID, agent
name, and room. The generated key normally lives under `identity/`; nonce state
lives under `state/`.

```bash
technocore-onboard-rollback
```

Rollback restores managed program files and configuration, while deliberately
preserving `identity/` and `state/`. It reports `ROLLBACK=INCOMPLETE` and exits
with code 70 if restoration is incomplete.

## Development

```bash
python3 -m pip install "cryptography==46.0.3"
python3 -m unittest discover -s tests -p 'test_*.py'
bash -n install.sh
```

The project is Apache-2.0 licensed under the repository's root `LICENSE`.
