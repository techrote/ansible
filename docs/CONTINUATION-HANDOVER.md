# Continuation handover — 2026-09-14

## Current continuation: 0.2.7

Implementation 0.2.7 is the issue #38 hardening follow-up to PR #37. PR #37's
hosted Ubuntu composition evidence remains valid for the exact trusted fixture used by CI;
`omp_blind_review_v1` remains disabled and `real_agent_qualified=false`.

The post-merge audit identified one reusable-qualifier validity gap: the host-only
composition API recorded the snapshot entrypoint SHA-256 but did not require it to
match trusted hostile-fixture bytes. Issue #38 / implementation 0.2.7 binds that
entrypoint to the trusted digest and makes standalone/composed Linux isolation share
one fixed Bubblewrap boundary builder, eliminating duplicated namespace/mount policy.
It also requires the exact complete composition check set and refuses a state root
that contains the trusted checkout. No runner, provider, model or publication authority
is added. See [ISOLATION-COMPOSITION.md](ISOLATION-COMPOSITION.md).

Final local verification for the #38 tree is **305 tests: 301 passed, 4 explicit
platform/mechanism skips**, plus **43/43** kernel qualification checks. Runtime
fingerprint is `e6e97008a20314fa06ebcc3bb85dd1c280c12181bafb50462329ee9739b17990`.
Because the local container lacks Bubblewrap, the changed isolation profile and
composition must both re-pass real hosted Linux qualification before merge.

Issue #31 / merged PR #36 already prepared the #16 `intrallm` producer migration
offline without cross-repository authority. Generation-2 idle payloads pass production
schema/transport preview and idempotence simulation, but #16 still requires explicit
permission to modify `techrote/intrallm`, a real deployment-ledger generation check,
and authenticated deployment-host refresh/provenance verification.

Issues #13, #14 and #32 are completed prerequisites; #38 is a fail-closed hardening
follow-up. Parent #1 remains open behind #16 and any current hardening work. Only
`noop_v1` is enabled.

## Transport continuation

Implementation 0.2.0 adds the opt-in transport described in
[SLOT-TRANSPORT.md](SLOT-TRANSPORT.md). Issue #12's code is implemented; actual
producer migration and live authenticated deployment are tracked in #16.
The producer currently uses the retired schema and is intentionally refused.
Only noop execution remains enabled. The following v0.1.5 section preserves the
previous completed run; use current `contract`/`qualify` output for source identity.

## Prior implementation

**Historical 0.1.5 / ansible.execution.v1 / trusted-noop-only.** Only `noop_v1` is enabled.
`omp_blind_review_v1` still returns `RUNNER_NOT_QUALIFIED` and
`real_agent_qualified` remains false. Omnipanel owns orchestration and the full UI;
Ohmy owns provider-specific normalization. This continuation did not change other
repositories, activate network/credential capabilities, or remerge the audited
Big Pickle candidate.

PR #2 was already merged when this continuation began. Earlier documents calling
it a draft are historical; they must not block use of the merged noop kernel or
be mistaken for permission to enable real agents. Parent issue #1 remains open.

## Implemented continuation work

| Issue | Implementation | Verification record |
|---|---|---|
| #3 | Reproducible CI bundles, exit records, source archive, provenance and checksums | Merged PR #4; four-job run 34732120868 |
| #5 | Bootstrap/effective generation enforcement, semantic replay validation, duplicate claim refusal, idempotent refresh | Merged PR #6; four-job run 34732430446 |
| #7 | Bounded config reads, strict Unicode/complexity checks, pre-open special-file refusal, descriptor cleanup | Merged PR #8; four-job run 34732613327 |
| #9 | Read-only job inspection, bounded event cursors, immutable slot binding and current evidence validation | Merged PR #10; four-job run 34732968190 |
| #11 | Shared concrete state-root defaults and use of the exact canonical checked path, plus handover reconciliation | v0.1.5 local evidence; final hosted result and merge identity are recorded on its associated PR |

Each merged implementation PR above was merged only after all four Windows/Linux
and Python 3.12/3.13 jobs passed, including both Windows PowerShell 5.1 launcher
smokes. Every runtime change has its own local evidence JSON under `evidence/`.
The v0.1.5 local suite runs **166 tests: 165 pass and one Windows-only test is
skipped on Linux**. All 35 execution qualification checks pass. Tests increased
from 87 at intake by 79; do not count a platform skip as a pass.

The added regression tests reproduced concrete failures before repair: eight slot
history failures, nine bounded-I/O failures plus one error, and eleven root-policy
failures (including subtests). The 28 query tests include observing a real running
controller without acquiring its execution lock or changing on-disk state.

Exact tested trees were compared with the uploaded Git trees before publication.
PR #4's downloaded Linux/Python 3.13 artifact was independently checked: its ZIP
matched GitHub's digest, all inner checksums verified, and its tracked source
reconstructed tree `e77357f6982fcbe882bb31a2d133300879d17fc3` exactly. Later CI
bundles use the same retained evidence workflow. Artifact retention is 14 days;
compact checked-in reports and PR comments retain the durable execution record.

## Important operational behavior

Use a reviewed checkout and the existing isolated entrypoint:

```powershell
py -3 -I -S -B run_kernel.py contract
py -3 -I -S -B run_kernel.py qualify
py -3 -I -S -B run_kernel.py config
py -3 -I -S -B run_kernel.py status
py -3 -I -S -B run_kernel.py inspect JOB_ID
py -3 -I -S -B run_kernel.py events JOB_ID --after 0 --limit 100
```

On Linux use `python3` in place of `py -3`. `--state-root PATH` precedes the
command. Config now reports the concrete default on both platforms; all
CLI-selected defaults/configured/explicit roots are canonicalized, checked
against known repositories, and that same checked path is used by Store.
Quoted `~` no longer causes the checked path and actual state path to diverge.

Existing once reservations remain consumed across upgrades/restarts. Do not
remove the ledger to rerun a bootstrap slot: use a deliberately larger reviewed
slot generation when another attempt is intended. First v0.1.1 observations are
preserved; later generation rollback/content changes and duplicate reservations
fail closed. Identical repeat refreshes do not needlessly append records.

Read-only queries do not create state roots or take the execution lock. A transient
read can intersect journal publication; retry reads without truncating or repairing
state. Inspect/event results revalidate evidence. Historical phase `completed`
and a cancel/contain marker alone never establish current semantic success or
verified termination. See [query contract](QUERY-CONTRACT.md).

## Next work and dependency boundaries

| Open issue | What can proceed | Gate which must remain closed |
|---|---|---|
| #16 — producer migration and deployment | Authorized data-only producer migration and actual authenticated acceptance of the implemented transport | No implicit producer writes, generation translation or claim of live qualification from fixtures |

Issues #13, #14 and #32 are completed prerequisites. Issue #38 hardens reusable
composition evidence without activating a runner. Real-runner activation remains
closed; no current source or CI report proves that a model performed a review. VM
providers and general candidate publication/export also remain outside the current
implemented profile.

Qualification of the user's own Windows installation is separate from hosted CI.
The current noop commands are available for that host-specific verification; this
continuation did not operate the user's desktop or certify its environment.

## Evidence and review entry points

Start with [release notes](RELEASE-NOTES.md), [runtime contract](RUNTIME-CONTRACT.md),
[query contract](QUERY-CONTRACT.md), [security](SECURITY.md) and
[CI bundle format](CI-EVIDENCE.md). The old [implementation report](IMPLEMENTATION-EVIDENCE.md)
and [CI report](CI-QUALIFICATION.md) retain their historical fingerprints, not the
current one. Use the current `contract`/`qualify` output and version-matched
evidence for the new runtime. Do not borrow another commit's or host's qualification.
