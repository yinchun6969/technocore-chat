# Research / alert integrity repair v5.5.4

Compatibility revision: when the Director lacks the v3.1 room outbox,
compose the validated Director-only room transformer before the context patch.
Both are compiled before any service changes and committed in one transaction.
Do not install or replace agent.py to satisfy this Director dependency. The
pre-v3.1 fixture comes from commit 0c49098 of this repository. Tests cover its
upgrade, repeat install and rollback as well as the v3.1 layout. Unsupported
layouts still fail closed. Offline fixture logs are now saved separately so
their mock installation messages cannot be mistaken for production success.

This additive repair targets AI2AI installations already running action-center.3.
The observed Director had no research-context patch: all five recent goals selected
historical workflow labels, while artifacts explicitly lacked independent evidence.

## Changes / 修复内容

- Apply and verify the missing Director source-backed selection patch. Automatic
  research needs a real GitHub candidate; old workflows are history, not new bugs.
- Mark sorted stage labels as unordered, not execution chronology.
- Retain source URLs, excerpts, pinned commit diffs and research-card associations.
  A background diff is not automatically evidence for the selected issue.
- Stop using the vocabulary score as an alert threshold. Display it as a text
  checklist score, not bug confidence. Signed receipts authenticate provenance,
  not reproduction or the truth of model claims.
- Classify findings rather than titles; reject explicitly uncertain/negated
  findings and verify the artifact content hash. Only high-impact P0/P1 candidates
  are eligible, with manual confirmation still required. Minor bugs stay silent.
- Add several cross-tenant impact terms; refresh qualifying legacy records without
  losing acknowledgement, snooze or closure state. No bulk replay of old alerts.
- Deduplicate repeated artifact/Director errors by event type and UTC hour using
  the existing persistent notification outbox. Failed delivery remains retryable.
- Compile every replacement before stopping services; preserve file permissions;
  back up code and automatically restore it on installation/startup failure.

## Install / 安装

On AI2AI only, as root, from the immutable repair checkout:

```bash
bash deploy/a2a-v5/install-integrity-v554.sh --check
bash deploy/a2a-v5/install-integrity-v554.sh --install
```

Love8 and Aizong do not need this repair. The installer never restores or rewinds
identity, keys, peers, mailbox cursors, workflow state or notification offsets.
It restarts only services that were active before installation. If an expected
service was already inactive, it stays inactive and is reported as such.

Rollback (refuses to overwrite code edited since installation):

```bash
/usr/local/bin/tc-a2a-research-integrity-v554-rollback
```

The installation log includes offline test fixture messages first; these are not
VPS service checks. The actual installation ends with
`RESEARCH_ALERT_INTEGRITY_V554_INSTALLED` and the three real service states.

Do not rerun an older pinned suite/alert installer after this repair without
reapplying the repair: older installers replace the same code files.

## Validation and remaining boundaries

Offline tests cover source selection, source failures, evidence cards, patch
idempotency, queue preservation, hash binding, negation, severity independent of
vocabulary score, classification-to-Telegram rendering, and install/rollback.
No test sends real Telegram messages or calls a model.

The core repository suite passes (321 tests; coverage 97.42%). New repair Python
files pass Ruff and type checking. Repository-wide Ruff/format/type commands were
also run but report pre-existing deployment-script issues; do not describe this
branch as globally CI-green or merge it around required CI gates.

This repair does not grant agents a code-execution sandbox and cannot guarantee
they find or reproduce a severe bug. Conservative text classification remains
heuristic and can miss synonyms or reject mixed confirmed/unconfirmed findings.
Provider read timeouts remain a separate runtime issue: rate limiting their
notifications does not repair the provider/network. Deployment acceptance needs
a new source-backed task and real provider/Telegram observations on AI2AI.

中文：本包修复已确认的选题与警报链路缺陷，不把“服务启动”当作研究有效或
通知已送达的证明。部署后需确认新任务有候选链接；模型仍超时时继续排查上游，
不能把没有严重漏洞报警解释为系统一定正常。
