# Implementation evidence: 0.1.1 trusted-noop-only

Historical v0.1.1 report. Current scope, verification and next work are in the
[continuation handover](CONTINUATION-HANDOVER.md). Preserve the old fingerprints
below as historical evidence, not current runtime identity.

Date: 2026-09-12 (UTC). Remote starting commit:
`9f27ca4f4c9317ed8246851f2961adc8bdb2de74`.
Implementation branch: `impl/01-trusted-kernel-contract-v1`.

## Actual local execution

Host: Linux, Python 3.13.5. Standard-library runtime and unittest suite.

| Verification | Observed result |
|---|---|
| `python -B -m unittest discover -s tests -v` | 87 tests run: 86 passed, 1 skipped; no failures/errors |
| `python -I -S -B run_kernel.py qualify` | All 35 checks passed |
| Windows Job Object kill-on-close test | Skipped locally; passed in hosted Windows CI after correcting the exit-code assertion |
| Windows PowerShell 5.1 wrappers / CI matrix | Passed on hosted Windows CI; not executed in this Linux container |
| Live OMP/Ohmy adapter | Not implemented or qualified; runner refused |

The v0.1.0 local unittest transcript remains in `evidence/unittest-linux.txt` and
its machine-readable profile remains in `evidence/qualification-linux.json`.
The v0.1.1 Big Pickle reconciliation was then tested locally: 87 tests run, 86
passed, one platform skip, and the unchanged 35-check execution qualification
passed. Its compact current evidence is `evidence/reconciliation-v011.json`.
The v0.1.1 reconciliation adds nine dedicated config/repository tests. Hosted
results for the previous qualified runtime and the Windows correction are recorded
in [CI qualification](CI-QUALIFICATION.md); v0.1.1 CI is recorded after publication.
The report pins source fingerprint
`d5215e7ec0c17d7714d2d87a0f87b51fd8ac891178ecd8c988977f22c311675c`.
That fingerprint covers kernel Python code, wire schemas and the trusted entry
point. It excludes docs, launchers and tests; their exact bytes are identified
by the Git commit. Re-run qualification after trusted executable changes.

## Regression and integration coverage

Twenty named semantic cases cover genuine success; the historical clean-controller
provider 429/retry failure; retry exhaustion; absent/whitespace output; analytical
zero-tool success; missing and present implementation activity; worker errors;
malformed transport; missing evidence; wrong job/version; nonzero exit/controller
failure; cancellation, containment and timeout; and worker self-asserted containment.
Raw OMP observations are fixture provenance, not parsed by the runtime.

Additional checks exercise bounded JSON, duplicate/unknown fields, types,
capability and runner refusals, path/ref traversal, legacy-slot cross-field
requirements, monotonic generations, replay refusal, exclusive locks, hash chains,
torn journals, lifecycle replay, symlinks/hardlinks, immutable result storage,
evidence mutation/removal, controller exceptions, startup isolation and CLI exits.
A seeded 400-case combination check additionally checks the success invariant.

Real Linux subprocess tests exercise noop completion, timeout, cooperative
cancellation, hard containment, actual memory and CPU limit enforcement, parent-
death termination and output-flood containment. Those are not just mocked success
flags. Test-only probes are never registered production runners.

## Qualification boundary

`profile_qualified: true` applies only to this host/source and the
`trusted-noop-only` profile. `real_agent_qualified: false` is intentional.
No claim is made for hostile worker filesystem/network isolation, general child
process trees, provider-specific protocol parsing, Git review/worktree safety,
VM providers, remote slot fetch or qualification on the user's Windows machine.

The implementation has not been subjected to an independent security review,
hardware power-loss qualification, or deployment on the user's Windows machine.
The previously unavailable Big Pickle worktree has now been supplied as an archive,
inventoried and reconciled in `docs/BIG-PICKLE-AUDIT.md`. Its safe fixed-repository
configuration concept was reimplemented; its mislabeled/unsafe OMP review runner
remains disabled. Issue #1 stays open for the real-agent/isolation gates.

## Reproduction and review

Use a clean reviewed checkout and an external private local state directory.
Run the two commands above. The CI definition repeats them on Windows/Linux and
Python 3.12/3.13 and smoke-tests the Windows PowerShell wrapper. The observed
passing matrix is linked in `docs/CI-QUALIFICATION.md`; later revisions must
re-run it rather than borrowing an older commit's qualification.

Review `docs/RECONCILIATION.md` for scope changes and unavailable work.
This original implementation was proposed on a separate branch and later merged
as PR #2. The continuation handover records subsequent verified merges. The
audited candidate was not deleted and other project repositories were not changed.
