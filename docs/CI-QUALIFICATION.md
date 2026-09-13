# Hosted CI qualification: trusted-noop-only

Historical initial-kernel report. For the current implementation, see
[continuation handover](CONTINUATION-HANDOVER.md), [release notes](RELEASE-NOTES.md)
and the corresponding implementation PR checks. The fingerprint below is historical.

Observed on 2026-09-12 (UTC). Tested commit:
`7915ad647cae922e8b8618dc3f32ac73e2f79168`.
Tested tree: `e1ac513d2fbf778b3e046dc8c072b90b67596d40`.

[PR workflow run 34724665447](https://github.com/techrote/ansible/actions/runs/34724665447)
completed all four matrix jobs successfully. These are observed job/step results,
not a claim based solely on the existence of a workflow file.

| Host / Python matrix | Tests | 35-check qualification | Windows PowerShell 5.1 launcher smoke |
|---|---|---|---|
| Ubuntu / 3.12 | passed | passed | not applicable |
| Ubuntu / 3.13 | passed | passed | not applicable |
| Windows / 3.12 | passed | passed | passed |
| Windows / 3.13 | passed | passed | passed |

The exact job IDs and source commit are retained in
`evidence/ci-summary.json`. The runtime fingerprint remains
`4bc956a8dcd696732d224d722ff9a1578f167c3d7294a9cf53d4e7e36b5b9c01`.
The follow-up after the first implementation commit changed test code only,
not the runtime, schemas, launcher code or contract semantics.

## Windows failure investigated and repaired

The initial push run, 34724451501, passed both Linux jobs. Each Windows job
reported one failure: `test_windows_job_close_terminates` assumed that a process
terminated by closing its Job Object must have a nonzero exit code. The observed
exit code was 0. Other Windows runtime/resource tests passed, including the
executable qualification invoked by the test suite.

The corrected test does not remove or skip the enforcement check. It waits for a
readiness handshake, confirms the worker is alive, closes the Job Object, and
requires the 30-second test workload to terminate within three seconds without
emitting its completion sentinel. Both Windows versions then passed the full
suite, the standalone qualification command and the PowerShell wrapper smoke.
This reinforces the runtime rule: an OS process exit code alone is not evidence
that the requested work completed.

Microsoft documents that closing the final handle with
`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` terminates the associated processes:
https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
The test checks that behavior directly rather than imposing an exit-code value.

## Scope remains narrow

This qualifies the hosted machines for the fixed `noop_v1` profile and exercises
the included Windows provider/PowerShell wrapper. It does not qualify the user's
own desktop, a hostile-code sandbox, a live Ohmy/OMP adapter, credential-bearing
execution or a general descendant process tree. The report must continue to say
`real_agent_qualified: false`. PR #2 was a draft at the time of this report and
has since merged. Issue #1 remains open for the unimplemented profile gates.

The local source ZIP and patch are separate convenience deliverables. Patch
verification reconstructed the exact original five-file baseline, applied the
patch, verified its normalized Git tree, and ran the 78-test suite successfully
on Linux (77 passed, one Windows-specific skip). Git's declared CRLF handling for
`.cmd` files is preserved rather than mistaken for a source-content difference.
