# Kernel continuation release notes

## 0.2.3 — pinned inert repository snapshots

Issue #22 adds the non-executing preparation slice of isolation issue #13. Exact
40-character commits from the fixed local repository registry are materialized by
reading Git commit/tree/blob objects only; ordinary checkout/worktree operations
are deliberately not used. Symlinks, gitlinks, `.git` path components, case/prefix
collisions, alternate object databases, linked-worktree metadata, oversized data
and malformed plumbing output fail closed. Executable mode and exact blob bytes are
preserved in a private, ownership-marked state snapshot. Cleanup accepts only the
derived identity tuple and verifies the marker/content before bounded removal.

The preparer grants no execution authority. `omp_blind_review_v1` remains disabled,
`real_agent_qualified=false`, and actual filesystem/network/credential isolation
remains issue #13. Candidate future profiles are documented in `PINNED-SNAPSHOTS.md`
and remain unqualified until deployment-host negative tests prove their controls.

Focused pre-publication Linux tests: 11/11 using real temporary Git repositories,
including malicious checkout filter/hook configuration, symlink/gitlink rejection,
case/path collisions, size bounds, alternate-object-database refusal, tampered
ownership/content and cleanup containment. Full hosted matrix evidence is recorded
on the implementation PR before merge.

## 0.2.2 — disabled pinned Ohmy conformance seam

Issue #20 / merged PR #21 adds `ansible.ohmy-summary.v1`, a fixture-first local
conformance seam pinned to the inspected Ohmy draft PR #50 head and OMP v18.1.18
revision. It accepts only bounded sanitized normalized facts, preserves provider/
retry/protocol failure precedence, and projects into the generic worker contract.
It does not import or launch Ohmy/OMP and never qualifies live execution.

The corrected PR head passed all four Windows/Linux Python 3.12/3.13 jobs, including
Windows PowerShell 5.1 smokes. Linux/Windows Python 3.13 evidence bundles were
independently checksum/source verified. The release has 261 tests, 43/43 local/
hosted qualification checks, and runtime fingerprint
`774c1a32c5839273a99233c96585c2b3906785fabc59997c51886096ed5b85e6`.

## 0.2.1 — anchored job-bound success evidence

Issue #18 repairs a reproduced cross-job evidence mix-up. New manifests bind the
job, runner, source and metadata; terminal journal events anchor their exact hash.
Success queries also revalidate job identity, the registered predicate and host
axes. Legacy noop histories remain readable without invented anchors or mutation.
See `EVIDENCE-BINDING.md` for compatibility and limitations.

Local verification: 243 tests, 242 passed and one Windows-only skip; 35/35 noop
qualification checks. Twenty-two new tests reproduced 20 reported failures on
v0.2.0, then passed after repair. `OHMY-INTEGRATION-READINESS.md` records the actual
pinned main/draft upstream inspection; no live adapter is enabled.

## 0.2.0 — opt-in pinned slot transport

Issue #12 adds the fixed intrallm source, explicit credential pipe/prompt,
independent tree/blob hashes, bounded direct TLS in a supervised helper, atomic
provenance publication and read-only `slot-source`. Launchers and local/offline
refresh remain unchanged. No worker network or credential authority is granted.

The existing remote source was inspected read-only and uses the retired schema.
It is deliberately rejected; #16 tracks a separately authorized data-only
migration and live authenticated deployment. No other repository was changed.
See `SLOT-TRANSPORT.md` for limits, trust boundaries and verification scope.

Local suite: 221 tests, 220 passed and one Windows-only skip; all 35 noop
qualification checks passed. Fifty-five added tests include real loopback TLS,
invalid certificate rejection, real helper kill/flood probes and native Git
hash agreement. Hosted matrix evidence is recorded on the implementation PR.

The runtime fingerprint now also covers `run_slot_transport.py`. New remote
journal events fail closed on older kernels; do not delete reservations or
silently downgrade a state root after remote publication.

## 0.1.5 — canonical state-root isolation and handover

Issue #11 shares one platform-default state-root policy between configuration and
Store. The CLI now checks defaults as well as configured/explicit roots against
known repositories before creation, and uses the exact canonical checked path.
This also repairs a quoted-tilde mismatch between the path validated and the path
Store actually used. Config output reports the concrete default on both systems.

Local verification: 166 tests, 165 passed and one Windows-only skip; 35/35
qualification checks. Twelve new tests reproduced eleven failures (including
subtests) against v0.1.4 on Linux and pass after repair. All fixtures use temporary
home/state directories. See `evidence/continuation-v015.json`.

The current handover and documentation index reconcile merged PR #2 and the
continuation work. Issues #12/#13/#14 define remaining transport, isolation and
adapter gates; parent #1 remains open. No new execution authority is enabled.

## 0.1.4 — read-only inspection and event cursors

Issue #9 adds versioned job inspection, bounded event paging, immutable minimal
slot/generation association for new jobs, and read-only Store construction.
Queries share one validated lifecycle snapshot and independently revalidate
success evidence. Event pages omit stale raw result copies. Control markers are
reported as requests, never proof of termination. Existing status/execution
response shapes remain compatible. See `docs/QUERY-CONTRACT.md`.

Local verification: 154 tests, 153 passed and one Windows-only skip; 35/35
qualification checks. The 28 query tests include real concurrent observation,
evidence tampering, restart cursors, binding/refusal metadata, malformed state,
read-only roots and unchanged on-disk data. See `evidence/continuation-v014.json`
and the hosted implementation PR checks.

## 0.1.3 — bounded configuration and regular-file I/O

Issue #7 bounds local configuration reads before allocation, shares the strict
JSON decoder, refuses special files before opening, and closes descriptors when
post-open validation fails. Existing symlink/reparse and hardlink checks remain;
nonblocking open flags provide additional FIFO-race protection where available.
No hostile same-user or network-filesystem sandbox guarantee is implied.

Local verification: 126 tests, 125 passed and one Windows-only skip; 35/35
qualification checks. Sixteen new tests reproduced nine failures and one error
against v0.1.2, including an externally deadline-bounded real FIFO hang. The
repaired suite passes. See `evidence/continuation-v013.json` and hosted PR checks.

Configuration remains optional operator-owned metadata. It accepts at most 32 KiB
of UTF-8 JSON and now shares the request decoder's depth-20/node-4096 limits.
Malformed Unicode is refused. Duplicate/nonfinite error codes are preserved;
oversized data returns `CONFIG_TOO_LARGE`, excessive complexity returns
`CONFIG_COMPLEXITY`, and special-file paths return `NONREGULAR_STATE_FILE`.

Python file-descriptor interfaces reference (consulted 2026-09-13):
https://docs.python.org/3/library/os.html#os.open

These are implementation hardening changes, not new task authority.

## 0.1.2 — slot-generation and reservation replay

Issue #5 repairs first-refresh bootstrap-generation replacement, validates
monotonic immutable slot observations during ledger replay, and refuses duplicate
job/request/once claims before further execution. Effective slot snapshots include
durable `slot_seen` observations rather than falling back incorrectly to checkout
defaults. An identical refresh is idempotent after its first durable snapshot.

New state compares refreshes against the shipped generation-1 snapshot. Change
contents only with a larger generation. Legacy v0.1.1 first observations are kept
as recorded: the upgrade does not rewrite history or invalidate that first record
merely because it differs from today's bundled defaults. Inconsistent subsequent
observations fail closed. Preserve the ledger for investigation; do not delete a
once reservation to retry an interrupted task.

Local verification: 110 tests, 109 passed and one Windows-only skip; 35/35
qualification checks. The 16 new tests produced eight failures against the old
code and all pass against the repair. See `evidence/continuation-v012.json`.
Hosted results are recorded in the implementation PR and its CI bundles; this
local report does not assert a Windows result.

## Reproducible CI evidence

Issue #3 / merged PR #4 adds private, 14-day Actions evidence bundles without
changing the execution profile. All four matrix jobs passed run 34732120868.
The retrieved Linux/Python 3.13 artifact's ZIP and inner checksums were verified;
its source reproduced tree `e77357f6982fcbe882bb31a2d133300879d17fc3` exactly.
See `docs/CI-EVIDENCE.md` and PR #4 for the detailed provenance.

## Preserved scope

Only `noop_v1` is enabled. Contract `ansible.execution.v1` is unchanged and
`real_agent_qualified=false` remains mandatory. The opt-in operator transport
does not grant worker network/credential authority. Arbitrary repository
execution, a live model adapter and a hostile-code sandbox remain unavailable. Omnipanel remains the orchestration owner; Ohmy owns provider parsing.
Issue #1 remains open for the remaining qualified execution capabilities.
