# Cross-platform isolation profile registry — implementation 0.2.5

Issue #25 is deliberately reconciled with the Linux work already merged by issue
#24 / PR #29. The registry does not create a second Linux sandbox implementation
and does not promote profile evidence into runner authority.

`python -I -S -B run_kernel.py isolation` reports the current platform's applicable
profile capability. The contract lists both profile contracts and always keeps
`runner_activation=false` / `real_agent_qualified=false`.

## Linux

The authoritative Linux profile is `ansible.isolation.linux-bwrap.v1` in
`ansible_kernel/isolation_bwrap.py`. Full negative qualification remains:

```text
python -I -S -B run_isolation.py qualify --state-root <private-state-root>
```

The generic registry calls only the existing availability probe. It intentionally
sets `profile_qualified=false` and `qualification_not_run=true`; it never infers a
past qualification from mechanism presence. See [ISOLATION-LINUX-BWRAP.md](ISOLATION-LINUX-BWRAP.md)
for the filesystem/network/credential/PID, output, deadline/descendant, memory and
CPU qualification contract and its actual hosted evidence.

## Windows

`ansible.isolation.windows-sandbox.v1` is a fail-closed configuration and
capability profile. Trusted host code generates the `.wsb` configuration; task
or model data cannot supply flags, commands, environment or sandbox destinations.
It explicitly sets:

- `VGpu=Disable`;
- `Networking=Disable`;
- `AudioInput=Disable`;
- `VideoInput=Disable`;
- `ProtectedClient=Enable`;
- `PrinterRedirection=Disable`;
- `ClipboardRedirection=Disable`;
- candidate and reference mappings read-only; and
- a separate result mapping writable.

Host directory inputs must be absolute ordinary directories with no symlink/reparse
redirection. The capability probe looks only for the trusted host `wsb`/`wsb.exe`
binary and records its SHA-256. Absence returns `WINDOWS_SANDBOX_CLI_UNAVAILABLE`.
Presence still returns `profile_qualified=false` with
`WINDOWS_LIVE_NEGATIVE_PROBE_NOT_RUN`; this release does not launch Windows
Sandbox or attempt to enable/install the optional Windows feature.

A future #13 slice must run hostile-code negative tests on an actual supported
Windows deployment host, including host-file/credential denial, read-only input,
result-only writes, network denial, descendant termination and resource/deadline
controls. Hosted GitHub Windows capability evidence is not a substitute.

## CI evidence

The existing Linux qualification artifact `isolation-linux-bwrap.json` is retained.
Implementation 0.2.5 additionally records `isolation-platform.json` on every matrix
leg and includes both fixed names in `checksums.json` when present. Arbitrary files
are not swept into the evidence bundle.

## Authority boundary

Only `noop_v1` is enabled. A profile report is never a runner registration,
admission decision or live model qualification. #13 remains open for Windows live
qualification and final runner composition; #14 remains the Ohmy/live-result gate.
