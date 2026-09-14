# Pinned snapshot → Linux isolation composition — implementation 0.2.6

`ansible.isolation-composition.v1` is a **host-only qualification surface**. It is
not an execution runner, is not addressable by slot/request data, and does not
qualify Ohmy, OMP, a model, or publication authority.

It closes one specific trust gap: proving that bytes read from an exact approved
Git commit by `ansible.snapshot.v1` can be executed only through the already
qualified `ansible.isolation.linux-bwrap.v1` boundary.

## Authority

The trusted operator/CI supplies only:

- a fixed known repository identifier (`intrallm` or `dashminimix`);
- an absolute ordinary local repository checkout;
- an exact 40-character lowercase commit object ID; and
- a private Ansible state root outside that repository.

The executable filename is fixed in trusted code as `ansible_sandbox_probe.py`.
The commit supplies that file's bytes, but cannot select the host executable,
Bubblewrap arguments, mounts, environment, network policy, result path or resource
envelope. The system Python runs the snapshot file with `-I -S -B` inside the
sandbox.

## Composition proof

Qualification performs these host-controlled steps:

1. Materialize the exact commit with the existing Git commit/tree/blob plumbing;
   checkout, hooks, filters, LFS, submodules, remotes and credential helpers are
   not invoked.
2. Verify the published snapshot and hash the fixed entrypoint bytes.
3. Bind the snapshot read-only at `/input` and one host-created result directory at
   `/output` through `linux_bwrap_v1`.
4. Run five fixed hostile modes: baseline boundary checks, output flood, descendant
   deadline evasion, memory exhaustion and CPU exhaustion.
5. Re-verify the complete snapshot after every mode and at completion.
6. Remove the snapshot only through its ownership-bound cleanup API. Cleanup is a
   required qualification check.

The baseline fixture must prove snapshot readability, snapshot immutability,
host-secret denial, credential-environment removal, network denial, private HOME,
PID isolation, result-only writing and a confined child write. The controller then
proves bounded output, deadline/descendant termination, memory/CPU enforcement,
unchanged snapshot identity and bounded cleanup.

Only bounded machine evidence is returned. Host paths, raw stderr/stdout, secret
contents and provider credentials are not included. The report records the commit,
snapshot manifest digest/counts, fixed entrypoint SHA-256, runtime fingerprint,
Bubblewrap profile fingerprint/version/binary SHA-256, resource envelope and named
checks.

## CI scope

Hosted Ubuntu creates a **synthetic local Git fixture with no remote**, commits the
tracked hostile probe as the fixed entrypoint, materializes that exact commit and
executes the live composed qualification. This proves the composition mechanism on
that hosted Linux environment; it is not evidence that the real `dashminimix`
repository, Ohmy/OMP, a model, or a deployment host was exercised.

Windows does not run this Linux-only composed probe. Its existing Windows Sandbox
capability report remains fail-closed and separately unqualified until a supported
Windows deployment host performs live negative qualification.

`runner_activation=false` and `real_agent_qualified=false` remain mandatory.
