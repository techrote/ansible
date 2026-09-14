# Final continuation handover — implementation 0.2.7

This file is the current handover for the merged issue #38 state. The older
`CONTINUATION-HANDOVER.md` retains its pre-final-audit local verification snapshot
and is historical where it reports 305 tests / fingerprint `e6e970...`.

## Authoritative merged identity

- issue: #38, completed by PR #39
- final PR head: `45cd6b82277e1884d830c4b2f45c8edb003a843e`
- merged `main`: `168f32e4cbaffc81f98a55d706b429c9304e7272`
- exact tree: `3e83b058e6eee66789eefbe5d4e2aaeb79a53ee4`
- implementation: `0.2.7`
- runtime/source fingerprint: `135ef0ba86ea7df08711c40719b391d4c50183b5565b38999dc4abad6d187dc4`

Only `noop_v1` is enabled. `omp_blind_review_v1` remains disabled.
`runner_activation=false`, `deployment_qualified=false`, and
`real_agent_qualified=false` remain mandatory for the composition profile.

## #38 hardening delivered

`ansible.isolation-composition.v1` now:

- requires exact trusted probe SHA-256
  `f2af54591d9a45fb43418142dc4f1fd582d448108dafec19d48846a9dbcaec21`
  before executing the snapshot entrypoint;
- returns typed pre-execution refusal for substituted probe bytes, preserving only
  bounded expected/observed SHA-256 identities and explicit negative authority axes;
- shares one fixed Bubblewrap namespace/mount/environment boundary builder with the
  standalone `ansible.isolation.linux-bwrap.v1` qualification path;
- requires exactly seven named composition checks, all passing, so an incomplete
  setup/error trace cannot qualify by omission;
- re-verifies exact snapshot identity after every hostile mode and at completion;
- refuses composition state roots that overlap the source repository or trusted
  checkout in either dangerous containment direction; and
- keeps cleanup ownership-bound and qualification-significant.

No task/slot field can select a Bubblewrap flag, executable, mount destination,
environment policy, network policy, or resource envelope.

## Final exact-head verification

Authoritative PR workflow `34885939297` passed all four Ubuntu/Windows × Python
3.12/3.13 jobs. Both Ubuntu jobs passed standalone Bubblewrap qualification and the
live pinned-snapshot composition. Windows passed the general suite and PowerShell
5.1 smoke while remaining live-isolation unqualified.

Independent retained-artifact verification established:

- Ubuntu 3.12: 308 tests, OK, 1 expected skip;
- Ubuntu 3.13: 308 tests, OK, 1 expected skip;
- Windows 3.13: 308 tests, OK, 7 expected platform skips;
- 43/43 kernel qualification checks on every independently checked artifact;
- exactly 7/7 required composition checks on both checked Ubuntu artifacts;
- expected and observed probe digest equal the trusted digest above;
- Linux Bubblewrap profile fingerprint
  `2dc0056cc87719222910bfb109cfe2cc22f22194649d0efdc085c7409ad94c85`;
- all checked ZIP digests and inner checksums valid; and
- every checked source archive reconstructs exact tree
  `3e83b058e6eee66789eefbe5d4e2aaeb79a53ee4`.

Artifact ZIP SHA-256 values:

- Ubuntu 3.12: `bc521cbbfd7b30e5ae27248efc53a69af0dd13b7afe2d3daa66813a069116cd9`
- Ubuntu 3.13: `e2f119f53d1527afffb5ccb62fcc0cc227b1e4fb82790f7c56a69482e3703f8f`
- Windows 3.13: `157094fc9fc29418e5c8d6a605e0a493afb65b534e054389315f7b2aa21a2226`

The first post-merge Windows 3.13 attempt later hit the existing direct Job Object
CPU-limit test's 8-second external wall watchdog while waiting for one CPU-second of
user time on a hosted runner. The exact final PR head had already passed this test;
43/43 semantic qualification and the PowerShell smoke also passed in the affected
post-merge job. The failed job was rerun separately to distinguish host starvation
from a repeatable runtime defect; consult workflow `34886336984` when assessing that
post-merge retry rather than treating the first attempt as a composition failure.

## Completed external slot migration

Issue #16 is completed. `techrote/intrallm` `control/launcher-slots` producer commit
`20117f4601a5a553184452daf80f78089bbd2608` publishes four current-schema generation-2
idle assignments. The real Windows deployment accepted them via authenticated opt-in
refresh, retained exact `ansible.slot-source.v1` provenance, returned `changed=false`
on repeat refresh, and left the trusted checkout clean. The accidental blank-token
attempt failed closed with `TRANSPORT_CREDENTIAL_INVALID`.

## Remaining boundaries

Parent issue #1 remains open. Real model/OMP execution is still not qualified: no
current evidence proves a model performed a review, and the Ohmy integration remains
a disabled fixture-first seam. Windows hostile-code isolation is also unqualified;
hosted Windows reports `WINDOWS_SANDBOX_CLI_UNAVAILABLE` and there is no fallback to
Job Objects as a hostile-code sandbox.

Preserve existing once reservations and append-only state. Do not delete the ledger
to force a retry. New runner authority still requires explicit trusted-code changes
and fresh qualification.

See `ISOLATION-COMPOSITION.md` and `../evidence/continuation-v027-final.json` for the
final #38 qualification record.
