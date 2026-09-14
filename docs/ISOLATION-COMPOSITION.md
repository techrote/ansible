# Pinned snapshot → Linux isolation composition — implementation 0.2.7

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
The snapshot file must also match trusted SHA-256
`f2af54591d9a45fb43418142dc4f1fd582d448108dafec19d48846a9dbcaec21`
before execution. The commit therefore cannot substitute a self-reporting program,
select the host executable, alter Bubblewrap arguments/mounts/environment/network
policy, or choose the result/resource envelope. The system Python runs the verified
snapshot file with `-I -S -B` inside the sandbox.

## Composition proof

Qualification performs these host-controlled steps:

1. Materialize the exact commit with the existing Git commit/tree/blob plumbing;
   checkout, hooks, filters, LFS, submodules, remotes and credential helpers are
   not invoked.
2. Verify the published snapshot and hash the fixed entrypoint bytes.
3. Require the snapshot entrypoint digest to equal the trusted probe digest, then
   bind the snapshot read-only at `/input` and one host-created result directory at
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
contents and provider credentials are not included. The report records the commit, snapshot manifest digest/counts, expected and observed
fixed entrypoint SHA-256, runtime fingerprint, Bubblewrap profile fingerprint/version/
binary SHA-256, resource envelope and the complete required check set.

## CI scope

Hosted Ubuntu creates a **synthetic local Git fixture with no remote**, commits the
tracked hostile probe as the fixed entrypoint, materializes that exact commit and
executes the live composed qualification. This proves the composition mechanism on
that hosted Linux environment; it is not evidence that the real `dashminimix`
repository, Ohmy/OMP, a model, or a deployment host was exercised.

Windows does not run this Linux-only composed probe. Its existing Windows Sandbox
capability report remains fail-closed and separately unqualified until a supported
Windows deployment host performs live negative qualification.

Local Linux/Python 3.13.5 verification for 0.2.7 runs **305 tests: 301 passed,
4 platform/mechanism skips**, plus **43/43** kernel qualification checks. The local
container has no Bubblewrap, so standalone/composed live checks remain hosted gates
rather than local successes. Runtime fingerprint is
`e6e97008a20314fa06ebcc3bb85dd1c280c12181bafb50462329ee9739b17990`;
the changed Linux isolation profile fingerprint is
`2dc0056cc87719222910bfb109cfe2cc22f22194649d0efdc085c7409ad94c85`
and therefore must be re-qualified in hosted Linux CI before merge.

`runner_activation=false`, `deployment_qualified=false` and
`real_agent_qualified=false` remain mandatory.
