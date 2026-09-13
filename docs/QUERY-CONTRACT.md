# Read-only job queries

Implementation 0.1.4 adds two local JSON query interfaces for clients such as
Omnipanel. They grant no execution, recovery, control, network or publication
authority. The full orchestration UI remains outside this kernel.

```powershell
py -3 -I -S -B run_kernel.py inspect JOB_ID
py -3 -I -S -B run_kernel.py events JOB_ID --after 0 --limit 100
```

On Linux use `python3` instead of `py -3`. `--state-root PATH` and
`--expect-contract ansible.execution.v1` are global options, before the command.
`contract` advertises `query_contracts` and `max_event_page_size` so clients can
negotiate the additive query interfaces without guessing the implementation.
Existing execution/result/status response shapes are unchanged.

## Job inspection: ansible.job-status.v1

`inspect` returns a single validated lifecycle snapshot with the following data:

| Field | Meaning |
|---|---|
| `state`, `terminal`, `event_count` | Observed journal phase, whether it is terminal, and number of transitions |
| `started_time_ns`, `last_event_time_ns` | First/latest recorded wall-clock timestamps; null when no event exists |
| `elapsed_ms` | Nonnegative wall-clock estimate since creation; freezes at the terminal event, not worker CPU time |
| `slot_context` | Immutable `{slot, generation}` from new host-recorded job metadata, or null for direct/legacy/unbound jobs |
| `control_requested` | Present cancel/contain marker, or null; this is not proof of termination |
| `verified_result` | Result validated against the execution result schema with success evidence rechecked, or null before terminal publication |

`job_id`, `contract_version`, `execution_contract` and `implementation_version`
identify the query and implementation. Full schema: `schemas/job-status-v1.schema.json`.
A non-null `verified_result` is separately checked against
`schemas/result-v1.schema.json`; its nested contract remains `ansible.execution.v1`.

Historical phase `completed` does not alone establish current semantic success.
For example, altered worker evidence yields `verified_result.worker_outcome =
invalid_result` even though the append-only phase remains `completed`. Never
reclassify success from an exit code, a phase name, or a control receipt.

Slot context is host-generated from a validated slot and contains no task text,
credentials, command or arbitrary path. It records the assignment at launch or
refusal, not the slot's current later generation. A refused idle/once-only launch
is still associated with the requested slot. Legacy histories are not rewritten
or assigned guessed slot identities.

## Event paging: ansible.events.v1

`events` returns `job_id`, `execution_contract`, `after`, `next_cursor`,
`total_events`, `has_more`, `terminal`, `events` and `verified_result`.
Schema: `schemas/events-v1.schema.json`.

Cursors are one-based event sequences expressed as a last-seen cursor: `after=0`
starts at the first event. Each returned event contains only `sequence`, `state`
and `time_ns`. Pass `next_cursor` as the next request's `--after`. Sequences are
stable across reader/controller restarts because the underlying journal is
append-only and sequence/hash checked. A page can be empty at the current end.
`has_more=false` does not mean the job has stopped; check `terminal` separately.

Page size is 1–128 (default 100). Cursors are integers from 0 to 2,147,483,647;
a cursor ahead of the current journal is refused rather than silently reset.
The journal is fully validated within its existing 16 MiB cap before slicing.
Pagination bounds returned event count, not total replay work. This is intended
for the current small local kernel, not a large telemetry streaming service.

Raw terminal result copies are deliberately omitted from individual events.
Only the top-level `verified_result` is appropriate for a success decision;
a caller cannot accidentally use an old unverified success nested in a page.

## Read-only and failure behavior

These commands do not take the controller's execution lock, create missing state
roots/job directories, create control markers, recover jobs, or append records.
They therefore work while a controller is running. Lifecycle and terminal result
are projected from the same validated event snapshot. Evidence and control-marker
reads are current observations, not an atomic snapshot of the entire filesystem.

A poll can intersect an append or incomplete job creation and receive a typed
local-state/IO error. Retry the read without changing state; a persistent torn or
corrupt journal requires operator investigation. Queries never truncate or
repair it. Wall-clock changes can affect active elapsed estimates; negative
estimates are clamped to zero and are not a deadline/enforcement mechanism.

Successful queries exit 0 even for an active or failed job: it means the query
completed, not that work succeeded. Semantic query errors exit 3 with the existing
JSON error envelope (`STATE_ROOT_NOT_FOUND`, `UNKNOWN_JOB`,
`INVALID_EVENT_CURSOR`, `EVENT_CURSOR_AHEAD`, `INVALID_EVENT_PAGE_SIZE`,
`INVALID_SLOT_CONTEXT`, or existing state/IO errors). CLI syntax errors retain
argparse's usage/exit-2 behavior. Contract negotiation refusals remain exit 2.

No hostile-code isolation or live Ohmy/OMP execution is added. Only `noop_v1`
remains enabled and `real_agent_qualified=false` remains mandatory.
