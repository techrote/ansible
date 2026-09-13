# Runtime contract: ansible.execution.v1

## Interface and negotiation

`run_kernel.py contract` reports the contract identifier, implementation version,
source fingerprint, registry and supported concurrency. Supply
`--expect-contract ansible.execution.v1` before commands. Unknown versions return
`INCOMPATIBLE_CONTRACT`; request and normalized-worker versions are checked
independently. A source hash identifies bytes, not semantic compatibility.

`run FILE` or `run -` accepts exactly one JSON request. An admitted job produces a
terminal JSON result synchronously and durable status events. Its random 32-hex
job ID binds normalized output, evidence and queries. Job IDs are host-generated;
request IDs are data and used only through a digest for replay protection.

## Strict request boundary

`schemas/execution-v1.schema.json` defines the exact envelope. All fields are
required. `parameters` is then validated using the registry-owned runner schema.
Unknown properties fail at each object boundary. The wire dialect is UTF-8 JSON,
maximum 65,536 bytes, depth 20 and 4,096 visited nodes; duplicate names, floats,
nonfinite numbers and malformed Unicode are refused. Booleans are not integers.
The built-in validator accepts only the explicitly implemented schema subset;
new schema keywords require a trusted validator change.

Production registry metadata in `ansible_kernel/contract.py` is immutable:

| Runner | Status | Predicate / authority |
|---|---|---|
| `noop_v1` | enabled | Exact output `trusted noop complete`; no task-controlled paths or commands |
| `omp_blind_review_v1` | disabled | `RUNNER_NOT_QUALIFIED`; no attempt to invoke OMP |

For noop, `provider_id` must be `trusted_local_v1`, capabilities must be empty,
parameters must be exactly `duration_ms` (integer 0-5000), timeout is 1-30 seconds,
memory is 64-256 MiB and CPU time 1-2 seconds. The outer schema's wider maxima do
not grant a larger registry envelope. `ansible.runner.noop.v1` names its predicate.
No environment, executable, module, shell, worktree or output path is a request field.

## Trusted local configuration

`config/local.json` is optional, ignored by Git, and belongs to the trusted operator
plane. It is not part of the execution request contract. The config v1 schema accepts only
fixed repository identifiers `intrallm` and `dashminimix`, optional safe slot/model
metadata, and an optional absolute local-state path. Unknown/duplicate keys and
invalid types fail closed. Explicit repository paths must be absolute existing Git
checkouts; otherwise only same-parent sibling directories with those fixed names
are discoverable. Symlink/reparse redirection is refused. Every CLI-selected state root, including platform defaults and explicit overrides,
is canonicalized and checked before creation. The exact checked path is used by
Store and may not sit inside the trusted checkout or a resolved known repository.

These settings do not grant execution authority. In particular, approved model
names cannot enable the disabled OMP runner, and repository resolution never
selects a script, command, hook, or arbitrary repository identifier from task data.

## Five separate outcome axes

| Axis | Purpose |
|---|---|
| admission | `admitted` or a typed schema/policy/runner/capability refusal |
| infrastructure | Host-observed state, exit code, controller completion |
| transport | Normalized readiness/protocol/connection/retry outcome |
| worker_outcome | Semantic success, failure, missing/invalid result, cancellation, timeout or containment |
| evidence | Complete, partial, missing or invalid evidence for this run |

See `schemas/result-v1.schema.json` for exact enums. There is deliberately no
ambiguous `ok` boolean. For an admission rejection, complete evidence describes
the rejection record; it does not assert that a worker ran.

Worker messages must match `schemas/worker-v1.schema.json`, including
`ansible.worker.v1`, the exact job ID, generic error class, retry flag, final
output, tool count and implementation-activity assertion. Raw OMP frames,
`stopReason`, provider status numbers and UI events are not accepted wire fields.
Ohmy will translate those into the generic contract. There is no live adapter yet.
A worker cannot self-certify `contained`; containment is a trusted host outcome.

## Success predicate and precedence

Success requires all of: admitted request; valid job-bound normalized result;
worker outcome success; no provider/worker error or retry exhaustion; acceptable
transport; nonblank final output satisfying the trusted runner predicate;
completed infrastructure with process exit 0 and controller completion; complete
verified evidence; and no host cancellation, timeout or containment.

Provider/worker errors override a worker success claim. Retry exhaustion remains
visible on the transport axis even when the worker classification is provider_error.
Known failure evidence is retained when infrastructure also fails; the axes can
both report a problem. A purely analytical predicate permits zero tool calls.
The implementation-task test predicate additionally requires implementation
activity and at least one tool call. Neither tool activity nor final prose proves
code correctness; future runners must validate their own required artifacts/tests.

The historical 429 case is represented in `tests/fixtures/runtime-v1.json` as a
**synthetic normalization fixture**, not a captured live adapter transcript:

```json
{"infrastructure":{"state":"completed","exit_code":0,"controller_completed":true},
 "transport":"retry_exhausted","worker_outcome":"provider_error"}
```

Missing final output after exit 0 becomes `no_result`, not success. Malformed,
wrong-job or incompatible normalized messages become `invalid_result`.

## Lifecycle, replay and control

State transitions are explicit and replay-validated. Typical progression is
created -> validated -> admitted -> starting -> running -> completed/failed.
Rejected, cancelled, timeout and contained are distinct terminal states; terminal
records are immutable. The reserved `cancelling` state is accepted by the state
machine, but this provider records a cancellation marker and terminal outcome
rather than emitting a separate cancelling transition.

One OS-held kernel lock spans admission, execution and finalization per state root.
The append-only ledger reserves request IDs and once-only slot generations before
launch. A crash consumes that attempt; retries need a new request ID/generation.
This is **at-most-once admission**, not exactly-once task completion. Slot generation
rollback and changes within an observed generation are refused. New refreshes
compare against the effective snapshot, including bootstrap defaults for slots
not yet recorded. Journal replay rejects cross-event generation changes and
duplicate job/request/once reservations. Existing v0.1.1 first observations remain
authoritative; no historical records are rewritten. An identical repeat refresh
is successful without another append after the first full snapshot is recorded.

Cancel creates an atomic empty marker and grants the fixed worker 0.5 seconds to
cooperate before escalation. Contain has priority and immediately requests hard
termination. Timeout is independent. Control and final publication share a lock:
a late request cannot rewrite an already terminal result. Control receipts are not
termination evidence. Unknown jobs are not killed by remembered PIDs.

Recovery runs under the kernel lock. Orphaned nonterminal jobs become infrastructure
unknown / worker unknown / `OWNER_LOST_REQUIRES_REVIEW`, never success. Torn/hash-
invalid journals block further execution until reviewed; no automatic truncation.

## Evidence and exit codes

Each job has `metadata.json`, `status.jsonl`, a fixed work directory, and where
available `provider.json`, `worker.json`, `manifest.json`, `result.json`.
Provider evidence records limit mode and output hashes; raw stderr and exception
strings are not stored. Request contents are not stored, only their digest.
The terminal status event is authoritative; `result.json` is a convenience copy.
New manifests bind the job, runner, metadata and source identity; terminal journal
events anchor their exact SHA-256. Success queries verify that anchor, worker job
identity, the registered noop predicate and host success axes. Known legacy noop
histories remain readable without fabricated anchors. See `EVIDENCE-BINDING.md`. Export reads a fixed filename whitelist
and returns an `ansible.evidence.v1` JSON snapshot; no arbitrary paths or Git patches.

For execution/result commands: 0 = semantic success; 1 = admitted non-success or
no terminal result; 2 = admission/contract refusal; 3 = local state/IO failure.
Other commands' exit 0 only means that command completed (e.g. a control receipt).
Always interpret the typed response, not an exit code from an unrelated command.

Qualification is host- and source-specific. `profile_qualified` applies only to
`trusted-noop-only`; `real_agent_qualified` is always false in the trusted-noop profile. Omnipanel must
pin this contract plus the intended qualified runner/provider profile and must
not treat noop qualification as permission to execute real model work.
