# Issue #1 and candidate reconciliation

## Baseline and candidates inspected

Repository: `techrote/ansible`. The original published baseline was `main` at
`9f27ca4f4c9317ed8246851f2961adc8bdb2de74`, containing policy/docs, normalization
rules, local ignores and `schemas/slot-v1.schema.json`. PR #2 (since merged) introduced the
versioned trusted execution kernel on `impl/01-trusted-kernel-contract-v1`.

The previously unpublished Big Pickle worktree has now been supplied as
`ansible-i01p.zip`. Its `.git` worktree pointer names `ansible-i01p`, matching the
previously identified local candidate. The archive was inspected as source/evidence
only and was not reset, modified, or treated as trusted executable code. Its archive hash/count and local verification are in
`evidence/reconciliation-v011.json`, and the detailed A-E assessment is in
`docs/BIG-PICKLE-AUDIT.md`.

## Reconciliation result

The current Python kernel remains the authoritative implementation. Big Pickle has
useful pieces, but merging it wholesale would regress the most important trust and
runtime-result properties added by the kickoff:

- its `omp_blind_review_v1` does not invoke OMP/model/Ohmy at all;
- it can run candidate-controlled pytest code without a qualified sandbox;
- its process helper lacks hard RAM/CPU limits, preserves most inherited
  environment variables and accumulates child output without a bound;
- ruff/pytest failures can be recorded without necessarily making the runner fail;
- it has no five-axis normalized worker/result contract capable of representing
  the historical provider-429/no-result false-success case;
- once-only completion is recorded after success rather than reserved before
  launch, and slot refresh does not enforce monotonic immutable generations;
- its PID-file lock and plain JSONL status are weaker than the current OS locks,
  hash-chained/fsynced journals and fail-closed replay.

Consequently `omp_blind_review_v1` remains registered but disabled with
`RUNNER_NOT_QUALIFIED`; `real_agent_qualified=false` remains mandatory.

## A-E disposition summary

| Material | Disposition | Action |
|---|---|---|
| Trust/data-plane separation | A | Preserve and strengthen |
| Stable launcher-slot concept | A | Retain current smaller wrappers |
| Fixed local runner registry | A | Retain current immutable registry |
| Big Pickle `config/local.json` + fixed sibling repo discovery | A/B | Reimplemented and qualified in v0.1.1 |
| Slot/path/SHA validation ideas | A/B | Preserve rules; current parser/runtime checks remain authoritative |
| Append-only status concept | A/B | Preserve; current hash-chained/fsynced/locked journal supersedes implementation |
| Git snapshots and disposable-worktree ownership marker | B | Keep as future runner design input; harden hooks/isolation/provenance before activation |
| Richer integrated orchestrator presentation | C | Keep as reference; broader orchestration UI belongs in Omnipanel |
| Stale README/POLICY and duplicated PowerShell prototype plumbing | D | Superseded |
| Big Pickle `omp_blind_review_v1` as an OMP runner | E | Do not enable or merge as-is |
| Unsandboxed candidate pytest execution | E | Excluded until a qualified execution provider exists |
| Task-supplied shell/script/runner authority | E | Continue to refuse at every boundary |

## Salvage performed

Version 0.1.1 adds `ansible_kernel/config.py`, `schemas/config-v1.schema.json` and
`config.example.json`, based on the useful Big Pickle configuration concept but
implemented against the current trust model. It supports only the fixed repository
IDs `intrallm` and `dashminimix`, operator-supplied absolute paths or fixed sibling
discovery, strict config validation, symlink/reparse refusal and configured-state
isolation. Configuration does not enable a runner or grant executable authority.

The cross-platform test suite now covers safe config defaults, fixed repository
discovery and state-root isolation; the 35-check execution qualification remains
focused on execution-contract semantics. The Git snapshot/worktree/reference helpers were not
copied in this change because their security prerequisites are not yet met.

## Delivered versus remaining acceptance

Delivered/qualified for the trusted-noop profile: immutable registry; bounded
strict request validation; fixed noop; versioned five-axis results; generic success
predicates and false-success fixtures; durable explicit job states; at-most-once
reservations; append-only/hash-chained status and ledger; evidence manifests;
cancellation/containment; resource-limited fixed provider; minimal local panel;
four stable launchers; operator-local fixed repository resolution; qualification
and Windows/Linux CI.

Still unavailable or unqualified: live Ohmy/OMP execution; hostile-code
filesystem/network isolation; credential-bearing runners; arbitrary repository
build/test execution; hardened pinned review worktrees; ref+path-to-blob provenance;
VM providers; remote slot/reference transport; general candidate snapshot export;
and qualification on the user's own Windows installation.

## Integration sequence

Keep Issue #1 open as the execution-substrate acceptance target. PR #2 is merged;
its noop-only scope did not require enabling real agents. Current continuation
changes and evidence are in `docs/CONTINUATION-HANDOVER.md`; remaining transport,
isolation/worktree and adapter work is tracked by #12, #13 and #14. Omnipanel may target
the published contract and refused-capability behavior now. Ohmy may implement the
normalized OMP/provider adapter in parallel. Enabling a real runner must remain
serialized behind enforced isolation and adapter-specific outcome/evidence tests.
Do not reinterpret Big Pickle's deterministic review record as evidence that OMP
performed a review.
