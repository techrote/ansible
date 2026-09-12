# Issue #1 and candidate reconciliation

## Observed baseline

Repository inspected: `techrote/ansible`, private. Initial inspection found only
`main` at `9f27ca4f4c9317ed8246851f2961adc8bdb2de74`, no published PRs and no
published implementation branches. Issue #1 was open with no comments. Its title
was “Implement trusted launcher slots and integrated orchestrator panel.”
The complete baseline comprised README, POLICY, .gitattributes, .gitignore and
`schemas/slot-v1.schema.json`; there was no published executable candidate.
All five fetched baseline files were verified against their Git blob IDs locally.

Earlier context identifies an unpushed Big Pickle worktree on the user's Windows
machine, `ansible-i01p`, branch `impl/01-trusted-orchestrator-pickle`. That worktree
is not mounted or remotely published here. Library searches found no retrievable
copy. **Its code was not inspected, replaced, deleted, or judged correct/incorrect.**
Reconcile it file-by-file before integrating this branch into that local worktree.
No claim is made that useful unpublished work was salvaged.

## A-E disposition of available material

| Material | Disposition | Action |
|---|---|---|
| Existing trust/data-plane policy | A, with boundary clarification | Preserve data/code separation; rename overarching orchestration responsibility to Omnipanel |
| Text normalization and local ignores | A | Preserve; extend ignores for local test/cache outputs |
| Legacy slot schema | B | Preserve exact schema; add stricter runtime cross-field, generation, path and registry checks |
| Issue #1 richer orchestrator ambitions | C | Full scheduling/model/project TUI belongs in Omnipanel; implement only local slots/status/control |
| Historical executable prototype in intrallm | D as architectural role, not a code audit | Do not execute, delete or edit it in this run |
| Task-supplied shell/script/runner authority | E | Refuse at every request boundary |
| Unpublished Big Pickle implementation | Uninspected, not A-E classified | Requires access before correctness or salvage claims |

The user's “Trusted Execution Kernel Implementation Kickoff” supersedes the
older richer-panel wording for this run. This branch is an isolated implementation
candidate, not an update of `main`, and does not close Issue #1.

## Delivered versus remaining acceptance

Implemented: immutable registry; strict runtime request validation; fixed noop;
versioned five-axis results; generic success predicates and false-success fixtures;
durable job states; at-most-once reservations; append-only status/ledger; evidence
manifests; controls; resource-limited local provider; minimal CLI/panel; four stable
launchers; local data-only refresh; qualification and cross-platform CI definition.

Not delivered/qualified: live Ohmy/OMP execution; hostile code isolation; network
and filesystem enforcement for general workers; pinned repository/reference
fetch and review worktrees; exact Git post-run review invariants; VM providers;
credential-bearing runners; remote slot transport; arbitrary Git candidate export;
repository auto-discovery/config/local.json functionality; Windows execution
qualification on the user's machine; unpublished candidate reconciliation.
The historical `Invoke-TaskSlot.ps1` filename is replaced in this candidate by the
shared fixed `launchers/Invoke-Kernel.ps1` wrapper, not by a script path in data.

Retiring executables on another repository was deliberately not performed: their
actual state and consumers have not been audited. Existing experimental OMP work
and other project branches remain untouched.

## Integration sequence and issue ownership

Keep Issue #1 open as the execution-substrate acceptance target. Review this PR
as the noop-only foundation, qualify on Windows, then reconcile the unpublished
candidate without a blind reset. Ohmy may implement normalized fixtures in parallel;
Omnipanel may target the published contract and refused-capability behavior.
Enabling a real agent must be serialized after a qualified isolation/provider
boundary and adapter-specific success/evidence tests. Do not loosen the registry
or treat a passing noop profile as permission to bypass those gates.
