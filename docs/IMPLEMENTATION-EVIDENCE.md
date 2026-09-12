# Implementation evidence: 0.1.0 trusted-noop-only

Date: 2026-09-12. Remote starting commit:
`9f27ca4f4c9317ed8246851f2961adc8bdb2de74`.
Implementation branch: `impl/01-trusted-kernel-contract-v1`.

## Actual local execution

Host: Linux, Python 3.13.5. Standard-library runtime and unittest suite.

| Verification | Observed result |
|---|---|
| `python -B -m unittest discover -s tests -v` | 78 tests run: 77 passed, 1 skipped; no failures/errors |
| `python -I -S -B run_kernel.py qualify` | All 35 checks passed |
| Windows Job Object kill-on-close test | Skipped: no Windows host in this session |
| Windows PowerShell 5.1 wrappers / CI matrix | Added, not locally executed |
| Live OMP/Ohmy adapter | Not implemented or qualified; runner refused |

The full local unittest output is in `evidence/unittest-linux.txt` and the
machine-readable profile is in `evidence/qualification-linux.json`.
The report pins source fingerprint
`4bc956a8dcd696732d224d722ff9a1578f167c3d7294a9cf53d4e7e36b5b9c01`.
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
VM providers, remote slot fetch or Windows host qualification.

The implementation has not been subjected to an independent security review,
hardware power-loss qualification, or deployment on the user's Windows machine.
The unpublished Big Pickle candidate was inaccessible; its reconciliation remains
open. Issue #1 must remain open until its retained acceptance gates are met.

## Reproduction and review

Use a clean reviewed checkout and an external private local state directory.
Run the two commands above. The CI definition repeats them on Windows/Linux and
Python 3.12/3.13 and smoke-tests the Windows PowerShell wrapper. CI results must
be read from the PR; the workflow's presence is not evidence that it passed.

Review `docs/RECONCILIATION.md` for scope changes and unavailable work.
The implementation is proposed on a separate branch; there is no direct main
update, merge, candidate deletion or change to other project repositories.
