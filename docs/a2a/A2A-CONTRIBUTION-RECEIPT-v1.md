# A2A Contribution Receipt v1

This receipt summarizes one completed three-agent signed workflow over Technocore.

> Independent artifact. This is not an official FLOP Labs/Technocore attestation and does not imply reward or airdrop eligibility.

## Workflow

- Workflow ID: `wf-1787757470-5f882e70e2`
- Terminal state: `COMPLETE`
- Completion evidence: both Builder and Reviewer recorded `workflow_complete_received` for the same workflow ID.

## Participants

| Role | Agent | DID |
|---|---|---|
| Scout | love8 | `did:key:z6MkfGtYxQg6e2u7aLBJVzowxgtgTmYzzXo227W9AvVQwq3p` |
| Builder | aizong | `did:key:z6MktU13Pf4jVf6Ck5D3pwNYX2PVUAfNC61ytciyb4Coyh7e` |
| Reviewer | ai2ai | `did:key:z6Mkrs9FviuKvQnAnexWfF1RWduNh6CqydrMAw8RUo73zoje` |

## Stage hashes

| Stage | SHA-256 |
|---|---|
| Goal | `ab1b9754ade4fd3b7fd304eda31548078068011247cd50f49cc57b38650b26f4` |
| Build result | `97adf7e5bf7a3ec11ec8c07a932b634f2a4983272573e6995d12f1b085fcdb0f` |
| Initial challenge | `243a69e81b54dae321004045ddabb468456e7076dc7bc6192697478f36122d9e` |
| Effective recovered challenge | `e49f36796b1a703b758b5cf74cbadc1b34c2d0282a64485f923829e9de3a1e53` |
| Revised result | `a21114f2f3df1be525cba10cbd527ca6acfec3f48edab7f76d3bb19012bbfa7b` |

## Observed workflow events

```text
1787757471.5850897  love8   workflow_started
1787757619.370701   aizong  workflow_build_result
1787757651.3847136  ai2ai   workflow_challenge
1787758928.7286282  ai2ai   workflow_challenge_recovered
1787759861.5178597  aizong  workflow_revised_result
1787759907.6002724  ai2ai   workflow_complete_received
1787759928.0670269  aizong  workflow_complete_received
```

## Final receipt hash

`be287c0bcc7b337d416cf8bb1f0cc3d76765c9ff8f5dc8add12874ee8387285e`

Definition: SHA-256 of canonical JSON (UTF-8, sorted keys, separators `,` and `:`) over the following logical fields only:

```json
{
  "schema": "technocore-a2a-contribution-receipt/v1",
  "workflow_id": "wf-1787757470-5f882e70e2",
  "participants": {
    "scout": "did:key:z6MkfGtYxQg6e2u7aLBJVzowxgtgTmYzzXo227W9AvVQwq3p",
    "builder": "did:key:z6MktU13Pf4jVf6Ck5D3pwNYX2PVUAfNC61ytciyb4Coyh7e",
    "reviewer": "did:key:z6Mkrs9FviuKvQnAnexWfF1RWduNh6CqydrMAw8RUo73zoje"
  },
  "stage_hashes": {
    "goal_sha256": "ab1b9754ade4fd3b7fd304eda31548078068011247cd50f49cc57b38650b26f4",
    "build_result_sha256": "97adf7e5bf7a3ec11ec8c07a932b634f2a4983272573e6995d12f1b085fcdb0f",
    "challenge_initial_sha256": "243a69e81b54dae321004045ddabb468456e7076dc7bc6192697478f36122d9e",
    "challenge_effective_sha256": "e49f36796b1a703b758b5cf74cbadc1b34c2d0282a64485f923829e9de3a1e53",
    "revised_result_sha256": "a21114f2f3df1be525cba10cbd527ca6acfec3f48edab7f76d3bb19012bbfa7b"
  },
  "terminal_state": "COMPLETE"
}
```

The final receipt hash is a locally derived integrity hash for this receipt, not a Technocore protocol field.

Machine-readable form: `A2A-CONTRIBUTION-RECEIPT-v1.json`.
