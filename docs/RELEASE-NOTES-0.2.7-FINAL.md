# 0.2.7 final qualification note

This note supersedes only the **provisional local-verification paragraph** in the
0.2.7 section of `RELEASE-NOTES.md`. That historical paragraph was written before
the final refusal-evidence audit and is preserved rather than rewritten as if it
had observed later bytes.

## Final merged implementation

Issue #38 / PR #39 merged as `168f32e4cbaffc81f98a55d706b429c9304e7272`
with exact tree `3e83b058e6eee66789eefbe5d4e2aaeb79a53ee4`. Final PR head was
`45cd6b82277e1884d830c4b2f45c8edb003a843e`; GitHub's synthetic merge commit
`be8bb16ed0dbc8617c5a6f09f5bd936908087089` had the same tree.

The final audit added bounded refusal evidence for substituted probe bytes: early
composition refusals now explicitly retain `deployment_qualified=false`,
`runner_activation=false`, and `real_agent_qualified=false`, and expose only the
validated expected/observed 64-hex SHA-256 probe identities. No raw substituted
source is returned.

Final runtime fingerprint:
`135ef0ba86ea7df08711c40719b391d4c50183b5565b38999dc4abad6d187dc4`.

## Final verification

Authoritative pull-request workflow `34885939297` passed all four
Ubuntu/Windows × Python 3.12/3.13 jobs.

- Ubuntu 3.12: 308 tests, OK (1 expected skip), 43/43 kernel qualification,
  standalone Bubblewrap qualified, composition 7/7 qualified.
- Ubuntu 3.13: 308 tests, OK (1 expected skip), 43/43 kernel qualification,
  standalone Bubblewrap qualified, composition 7/7 qualified.
- Windows 3.13: 308 tests, OK (7 expected platform skips), 43/43 kernel
  qualification, PowerShell 5.1 smoke passed, Windows Sandbox remained explicitly
  unqualified with `WINDOWS_SANDBOX_CLI_UNAVAILABLE`.

Both Ubuntu composition reports bind expected and observed probe SHA-256
`f2af54591d9a45fb43418142dc4f1fd582d448108dafec19d48846a9dbcaec21`
and require the exact complete seven-check set. Linux Bubblewrap profile fingerprint:
`2dc0056cc87719222910bfb109cfe2cc22f22194649d0efdc085c7409ad94c85`.

Independent artifact verification matched GitHub ZIP digests and all inner
checksums, and reconstructed the exact final tree from each checked `source.tar`:

- Ubuntu 3.12 ZIP SHA-256 `bc521cbbfd7b30e5ae27248efc53a69af0dd13b7afe2d3daa66813a069116cd9`
- Ubuntu 3.13 ZIP SHA-256 `e2f119f53d1527afffb5ccb62fcc0cc227b1e4fb82790f7c56a69482e3703f8f`
- Windows 3.13 ZIP SHA-256 `157094fc9fc29418e5c8d6a605e0a493afb65b534e054389315f7b2aa21a2226`

Only `noop_v1` remains enabled. `omp_blind_review_v1` remains disabled. No model,
OMP, candidate publication, Windows hostile-code isolation, or broader runner
authority is qualified by this release.

Machine-readable final evidence is `../evidence/continuation-v027-final.json`.
