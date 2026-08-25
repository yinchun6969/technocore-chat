# aizong Social installer compatibility

`install_aizong_social.sh` supports both current DID-enabled installs and the older
`technocore_oneclick.sh` layout that only wrote `BASE`, `NICK`, and `PRIVATE_NS`.

For a legacy install, the installer preserves `NICK` and `PRIVATE_NS`, creates or reuses
`/opt/technocore-agent/identity/ed25519_private.pem`, derives the Ed25519 `did:key` and
fingerprint, creates or reuses a private mailbox name, rewrites the config with the full
identity fields, publishes the DID profile, and then installs the social daemon.

The migration is one-way only in the sense that the config gains fields; existing
Technocore room data and the existing local server are not modified.
