# Kernel continuation release notes

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
`real_agent_qualified=false` remains mandatory. No network/credential transport,
arbitrary repository execution, live model adapter or hostile-code sandbox is
added. Omnipanel remains the orchestration owner; Ohmy owns provider parsing.
Issue #1 remains open for the remaining qualified execution capabilities.
