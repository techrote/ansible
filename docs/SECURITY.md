# Security boundary and deliberately unavailable authority

## Threat model

Untrusted task/slot/reference/model data may be malformed, replayed, misleading or
try to introduce executable authority. The host OS, local user, interpreter,
trusted checkout and private local state directory are trusted. The service is a
local CLI, not an authenticated network endpoint or a multi-user daemon.
A process already running as the same user could replace trusted files or state;
locks, hashes and path checks do not defeat that attacker.

The only production child is the fixed standalone noop worker. It receives only
a host-generated job ID and bounded duration on stdin. Resource arguments come
from the validated registry envelope. The absolute interpreter and script path
come from trusted local code. `-I -S -B`, an explicit environment allowlist,
`close_fds`, no shell, and a per-job working directory exclude ordinary ambient
Python imports, credential variables and inherited descriptors. Entry-point
startup refuses omission of isolated/no-site flags.

**These are not filesystem/network sandbox guarantees.** A modified or arbitrary
child under this OS user could access files or network resources. The existing
worker contains no such operations and task data cannot add them. Therefore the
live OMP runner, repository tests/builds and adversarial code are disabled.
Do not expand the runner merely by changing its enabled flag.

## Resource and termination primitives

Linux uses RLIMIT_AS (address space, not resident RAM), RLIMIT_CPU (CPU seconds,
not CPU percentage), no core dumps, and a bounded file-size limit. The trusted
worker sets these before consuming the request. PR_SET_PDEATHSIG plus a parent-ID
race check kills it when its spawning controller thread dies. Each worker owns a
new process group for hard termination. This is suitable only for the fixed
non-forking worker, not a replacement for cgroups/namespaces/seccomp or a VM.

Windows code assigns the child to a Job Object before releasing stdin. Limits
include committed memory, user CPU time, one active process, and kill-on-close.
No breakaway is enabled. Failure to set/assign limits fails closed. The bootstrap
interpreter runs trusted code before assignment; no untrusted request is delivered
until assignment. Hosted Windows CI has exercised the code and PowerShell
wrapper (see `docs/CI-QUALIFICATION.md`). The committed local container report
establishes Linux behavior only; deployment-host qualification is still required.

CPU/memory caps apply to the child, not the controller or aggregate machine.
The controller enforces wall time and drains stdout/stderr with 32 KiB caps each;
an output flood causes containment. No VM fleet, CPU-rate allocation, network
denial, restricted Windows token, or general process sandbox is implemented.

## State and evidence

The default Windows root is `%LOCALAPPDATA%\techrote-ansible`; on Linux it is
`~/.local/state/techrote-ansible`. POSIX root permissions must exclude group/other
access. Windows relies on the operator's private application-data ACL; the code
does not install a restricted-token/ACL sandbox. State on network shares is not a
qualified configuration. Only the kernel's own checkout is mechanically excluded;
operators must also keep custom roots outside other repositories.

State paths reject traversal IDs, symlinks, Windows reparse points and regular-file
hardlinks. Open operations use O_NOFOLLOW where available. This detects common
redirection mistakes; it is not a complete hostile same-user TOCTOU defense.
Append-only journals are sequence/hash chained, fsynced and OS-lock serialized.
They detect partial writes/corruption, not malicious rewriting by the trusted user.
Windows directory-entry durability is weaker than a POSIX directory fsync; storage
power-loss guarantees have not been hardware-qualified.

Interrupted results are unknown, not successful. A torn journal blocks replay.
Preserve evidence and investigate before repairing; do not delete reservation
records to make a once-only task run again. The controller never kills a stored
PID during recovery. Fixed-worker parent-death/job-close primitives prevent the
usual orphan continuation; there is no general adoption service.

## Credentials and integration gates

No credential-bearing capability is registered. Child environment variables do
not include tokens, PATH, Git configuration overrides or SSH-agent handles.
The worker's environment isolation does not stop same-user filesystem credential
access by arbitrary code; that is another reason arbitrary workers remain refused.
Do not put secrets in task data or final model output. There is no universal
semantic secret redactor for future model output in this release.

Before a real Ohmy/OMP adapter can be enabled, qualify enforced filesystem/write
and network boundaries, credential handling, trusted normalized-event provenance,
resource limits including descendants, cooperative and emergency termination,
job-bound artifact validation, and the historical false-success case end to end.
Maintain OMP-specific parsing in Ohmy, not this kernel.

## Primary references consulted (2026-09-12)

- Python resource limits: https://docs.python.org/3/library/resource.html
- Python isolated/no-site flags: https://docs.python.org/3/using/cmdline.html
- Python subprocess environment and lifecycle: https://docs.python.org/3/library/subprocess.html
- Linux PR_SET_PDEATHSIG: https://man7.org/linux/man-pages/man2/PR_SET_PDEATHSIG.2const.html
- Windows Job Objects: https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
- Windows Job Object limits: https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_limit_information
- Windows extended memory limits: https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information

These references describe OS/API behavior. Repository tests and host reports,
not the existence of these APIs, establish implementation qualification.
