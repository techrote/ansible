# Pinned snapshot → Linux isolation composition — implementation 0.2.7

`ansible.isolation-composition.v1` is a **host-only qualification surface**. It is
not an execution runner, is not addressable by slot/request data, and does not
qualify Ohmy, OMP, a model, deployment authority, or publication authority.

It closes one specific trust gap: proving that bytes read from an exact approved
Git commit by `ansible.snapshot.v1` can be executed only through the already
qualified `ansible.isolation.linux-bwrap.v1` boundary.

## Authority and trusted probe identity

The trusted operator/CI supplies only:

- a fixed known repository identifier (`intrallm` or `dashminimix`);
- an absolute ordinary local repository checkout;
- an exact 40-character lowercase commit object ID; and
- a private Ansible state root outside that repository and the trusted checkout.

The executable filename is fixed in trusted code as `ansible_sandbox_probe.py`.
The snapshot file must also match trusted SHA-256
`f2af54591d9a45fb43418142dc4f1fd582d448108dafec19d48846a9dbcaec21`
before execution. The commit therefore cannot substitute a self-reporting program,
select the host executable, alter Bubblewrap arguments/mounts/environment/network
policy, or choose the result/resource envelope. The system Python runs the verified
snapshot file with `-I -S -B` inside the sandbox.

A hash mismatch is a typed pre-execution refusal. Refusal evidence contains only
bounded expected/observed SHA-256 identities, never raw substituted source, and
explicitly keeps `deployment_qualified=false`, `runner_activation=false`, and
`real_agent_qualified=false`.

## Composition proof

Qualification performs these host-controlled steps:

1. Materialize the exact commit with the existing Git commit/tree/blob plumbing;
   checkout, hooks, filters, LFS, submodules, remotes and credential helpers are
   not invoked.
2. Verify the published snapshot and hash the fixed entrypoint bytes.
3. Require the snapshot entrypoint digest to equal the trusted probe digest, then
   bind the snapshot read-only at `/input` and one host-created result directory at
   `/output` through the same trusted Bubblewrap boundary builder used by the
   standalone `linux-bwrap-v1` qualifier.
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

A positive composition result requires **exactly** these seven named checks, all
passing; an incomplete setup/error trace cannot qualify by omission:

1. `snapshot_filesystem_network_credentials_pid`
2. `output_bound`
3. `deadline_descendant_containment`
4. `memory_limit`
5. `cpu_limit`
6. `snapshot_identity_preserved`
7. `ownership_bounded_cleanup`

Only bounded machine evidence is returned. Host paths, raw stderr/stdout, secret
contents and provider credentials are not included. The report records the commit,
snapshot manifest digest/counts, expected and observed fixed entrypoint SHA-256,
runtime fingerprint, Bubblewrap profile fingerprint/version/binary SHA-256,
resource envelope and the complete required check set.

## State-root containment

The composition state root is rejected if it is inside the source repository or
trusted Ansible checkout, if the source repository is inside it, or if it contains
the trusted checkout as an ancestor. These checks occur before materialization.

## Qualified CI scope

PR #39 final head `45cd6b82277e1884d830c4b2f45c8edb003a843e`, tree
`3e83b058e6eee66789eefbe5d4e2aaeb79a53ee4`, passed authoritative pull-request
workflow `34885939297` on Ubuntu/Windows × Python 3.12/3.13. Its GitHub synthetic
merge commit `be8bb16ed0dbc8617c5a6f09f5bd936908087089` had the same exact tree.
PR #39 merged to `main` as `168f32e4cbaffc81f98a55d706b429c9304e7272`, also with that tree.

Hosted Ubuntu creates a **synthetic local Git fixture with no remote**, commits the
tracked hostile probe as the fixed entrypoint, materializes that exact commit and
executes the live composed qualification. Both Ubuntu 3.12 and 3.13 final-head jobs
passed the standalone Bubblewrap profile and composed qualification. Each composition
report contained the exact trusted probe digest above and all seven required checks.
The Linux Bubblewrap profile fingerprint is
`2dc0056cc87719222910bfb109cfe2cc22f22194649d0efdc085c7409ad94c85`.

Final-head retained artifacts independently verified:

- Ubuntu 3.13: 308 tests, OK (1 expected skip), artifact ZIP SHA-256
  `e2f119f53d1527afffb5ccb62fcc0cc227b1e4fb82790f7c56a69482e3703f8f`;
- Ubuntu 3.12: 308 tests, OK (1 expected skip), artifact ZIP SHA-256
  `bc521cbbfd7b30e5ae27248efc53a69af0dd13b7afe2d3daa66813a069116cd9`;
- Windows 3.13: 308 tests, OK (7 expected platform skips), artifact ZIP SHA-256
  `157094fc9fc29418e5c8d6a605e0a493afb65b534e054389315f7b2aa21a2226`.

Every checked artifact matched GitHub's ZIP digest, every inner checksum verified,
and each retained `source.tar` reconstructed exact tree
`3e83b058e6eee66789eefbe5d4e2aaeb79a53ee4`. All checked artifacts report 43/43
kernel qualification checks and runtime fingerprint
`135ef0ba86ea7df08711c40719b391d4c50183b5565b38999dc4abad6d187dc4`.

Windows does not run this Linux-only composed probe. Its Windows Sandbox capability
report remains fail-closed with `WINDOWS_SANDBOX_CLI_UNAVAILABLE`,
`profile_qualified=false`, `deployment_qualified=false`, `runner_activation=false`,
and `real_agent_qualified=false`.

This hosted Linux evidence proves the composition mechanism on those hosts; it is
not evidence that the real `dashminimix` repository, Ohmy/OMP, a model, or a Windows
hostile-code sandbox was exercised. `noop_v1` remains the only enabled runner.
