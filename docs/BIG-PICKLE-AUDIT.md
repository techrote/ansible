# Big Pickle worktree audit and A-E reconciliation

Source supplied by the operator: `ansible-i01p.zip`, an archive of the unpublished
`ansible-i01p` worktree previously identified as branch
`impl/01-trusted-orchestrator-pickle`. Archive SHA-256:
`58456ec16a581fc31a67637c91b5b1ab4081a416ab3de87bed112043abc16157`.
The archive contained 35 files / 182,886 bytes. Its archive hash, file count and
local reconciliation results are recorded in `evidence/reconciliation-v011.json`.
The archive itself was treated read-only and was not reset, rewritten, or used as
an executable trust source.

This audit applies the current Ansible/Omnipanel boundary rather than the older
Issue #1 product shape. A means correct/in-scope, B means useful but repair or
qualification is required, C belongs primarily in Omnipanel, D is obsolete or
prototype material, and E is unsafe or architecturally invalid for the trusted
kernel.

## Executive finding

Big Pickle contains useful engineering, especially repository resolution, fixed
runner IDs, strict-ish slot validation, Git snapshots, append-oriented status and
stable Windows launchers. It also contains a critical semantic mismatch: the file
and registry entry named `omp_blind_review_v1` **never invoke OMP, a model, Ohmy,
or another agent process**. Instead it performs deterministic Git/search/lint/test
operations and writes a synthetic review record. It can then report the runner as
successful.

That implementation must not be re-enabled under the OMP runner name. More
importantly, its optional pytest step executes Python from the candidate worktree
under the operator account without a filesystem/network sandbox. That is outside
the trust boundary required for a real model/repository worker. The current v0.1.x
kernel is therefore retained as the authority: `noop_v1` remains the only enabled
runner and `omp_blind_review_v1` remains fail-closed.

## A-E classification

| Big Pickle component | Class | Disposition |
|---|---|---|
| `config/local.json` concept with only fixed repository IDs and sibling discovery | A/B | Salvaged and tightened in v0.1.1: strict schema, duplicate-key refusal, absolute explicit paths, symlink/reparse checks, fixed `intrallm`/`dashminimix` IDs, state-root isolation |
| Stable `launcher1.cmd` ... `launcher4.cmd` and one PowerShell entry script | A | Concept retained; current Python-kernel wrappers are simpler and already cross-platform/PowerShell-5.1 CI qualified |
| Enumerated local runner registry | A | Retained concept; current immutable registry is stronger because task data cannot supply script paths and unqualified runners are disabled |
| Slot validation of fixed repositories, SHAs, refs, paths, timeouts | A/B | Useful rules retained/reimplemented; current parser additionally bounds JSON complexity, rejects duplicate keys/floats, and couples validation to immutable runner policy |
| Append-only `status.jsonl` | A/B | Concept retained; current journal adds sequence/hash chaining, fsync, OS locking and fail-closed replay |
| Git before/after snapshots (`HEAD`, branch, status, refs, local config, origin heads) | B | Preserve as design material for a future repository-review runner; do not activate until worktree/hook/environment/isolation boundaries are qualified |
| Owned disposable-worktree marker | B | Useful cleanup/ownership idea; future implementation must also neutralize Git hooks and run within a qualified isolation boundary |
| Exact object-SHA lookup and blob reads | B | Useful primitive; future reference handling must prove the claimed ref+path resolves to the pinned blob, not merely prove that the blob exists somewhere in the repo |
| Minimal slot/status/control presentation | B | Useful UX ideas may inform the small local emergency panel |
| Richer orchestrator/status presentation | C | Overall orchestration/presentation growth belongs in Omnipanel; do not make Ansible the project/model TUI |
| Old README/POLICY claiming the executable layer is not committed | D | Stale after implementation; superseded by current docs |
| PowerShell PID-file slot lock and success-only once marker | B/D | Superseded by OS locks plus durable pre-launch at-most-once reservations; PID reuse/parse cleanup and crash retry semantics are weaker |
| Direct refresh from `intrallm` slot files without monotonic generation/content enforcement | B/E | Do not reuse as-is; generation rollback/same-generation rewrite must fail closed |
| `omp_blind_review_v1` as an OMP/model runner | E | Do not enable. It does not launch OMP/model/Ohmy and therefore cannot establish model-review success |
| Candidate-worktree `python -m pytest` execution | E | Executes candidate-controlled Python under the host user without qualified filesystem/network isolation |
| Native process helper environment isolation | E for hostile workers | It overwrites selected environment variables but does not clear the inherited environment; credential stripping is incomplete by construction |
| Native process helper resource/output containment | E for hostile workers | Wall timeout only; no hard RAM/CPU envelope and stdout/stderr are drained unbounded into controller memory |
| Worktree creation via ordinary `git worktree add` | B/E | Local Git hooks are not neutralized; do not use for untrusted candidate material until hardened |
| Production `ANSIBLE_TEST_MUTATE` mutation hook in the review runner | D/E | Test-only behavior should not live in a production trusted runner |

## Critical runner findings

### The OMP runner does not run OMP

`lib/runners/omp-blind-review-v1.ps1` records the manifest's model name, resolves
repositories and pinned objects, creates a worktree, runs Git/search operations,
optionally runs ruff/pytest, checks mutations, and writes a deterministic text
`review.txt`. There is no OMP/Ohmy/model executable invocation. The registry's
statement that this is a “Generic bounded OMP blind-review runner” is therefore
not an accurate executable contract.

This matters independently of implementation quality: a deterministic inspection
runner could eventually be valuable, but it must have its own honest runner ID and
success predicate. Renaming controller activity into an OMP review would recreate
the exact controller-success/task-success ambiguity that the current runtime
contract exists to eliminate.

### Candidate tests cross the trust boundary

The runner can execute `python -m pytest` against allowlisted repository-relative
paths from the candidate worktree. Restricting the path prevents simple traversal,
but it does not make Python test code safe: imported test/application code has the
same user-level filesystem and network authority as the process. This cannot be
accepted as a trusted review primitive until a real sandbox/provider boundary is
qualified.

### Process containment is not sufficient for untrusted workers

`Invoke-NativeBounded` uses `ProcessStartInfo`, asynchronous `ReadToEndAsync`, a
wall-clock timeout and `Kill()`. The environment dictionary modifies inherited
variables rather than constructing a new allowlist. Output is accumulated in
memory without a size cap. There is no hard memory or CPU accounting. Those are
reasonable prototype conveniences for trusted utilities, not sufficient
containment for model/candidate-controlled execution.

### Success is still controller-centric

Ruff/pytest non-zero exit codes are recorded as operation results but, unless an
operation times out or a Git invariant fails, the runner can proceed to its final
success result. Missing tools may be recorded as skipped. There is no normalized
provider/worker result or runner-specific model-output predicate. Consequently the
historical provider-429/no-result failure cannot be represented correctly by this
runner. The current typed v1 contract remains authoritative.

## Salvage implemented in v0.1.1

The repository/configuration portion has been reimplemented rather than copied
verbatim. `ansible_kernel/config.py`, `schemas/config-v1.schema.json`, and
`config.example.json` add:

- operator-owned `config/local.json`, still ignored by Git;
- only the fixed repository identifiers `intrallm` and `dashminimix`;
- explicit paths must be absolute existing Git checkouts;
- otherwise discovery is limited to fixed sibling directory names;
- duplicate/unknown config keys, malformed types and unsafe relative slot paths
  fail closed;
- config/repository symlink or Windows reparse redirection is refused;
- optional local state path must be absolute and cannot be inside the trusted
  checkout or a resolved known repository;
- model allowlist data is configuration metadata only and grants no runner or
  execution capability while the model runner remains disabled.

Nine dedicated cross-platform tests now cover config defaults, strict schema/refusal,
fixed repository discovery, explicit-path precedence, symlink refusal and configured
state-root isolation. The existing 35-check execution qualification remains focused
on the execution contract rather than operator configuration plumbing.

## Explicitly not salvaged yet

The Git snapshot/worktree/reference primitives are retained as reviewed design
material, not copied into the production kernel in this change. A future runner
may reimplement them after the isolation boundary exists. At that point it should
also bind `reference.ref` + `reference.path` to the exact blob SHA, neutralize
hooks, control descendant processes, prove network/filesystem restrictions, and
apply a runner-specific success predicate to the actual normalized worker result.

The richer PowerShell TUI likewise remains reference material. The current small
status/control panel is intentionally kept small; Omnipanel owns broader operator
orchestration.
