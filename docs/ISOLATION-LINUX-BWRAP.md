# Linux isolation profile: `ansible.isolation.linux-bwrap.v1`

Implementation 0.2.4 adds a separately qualified Linux Bubblewrap profile as one
slice of issue #13. It does **not** enable a real model/repository runner and does
not change `ansible.execution.v1`. `omp_blind_review_v1` remains disabled and
`real_agent_qualified=false` remains mandatory.

## Fixed trusted profile

Task/model data cannot supply Bubblewrap flags, a command, mounts, environment,
network policy, host paths or an executable. Trusted code constructs the profile:

- a new user namespace with further user-namespace creation disabled;
- separate PID, IPC, network and UTS namespaces (cgroup namespace when available);
- all capabilities dropped;
- empty Bubblewrap root, host `/usr` and required merged-/usr compatibility paths
  read-only;
- fixed trusted probe/runtime read-only;
- inert input read-only at `/input`;
- one private host-owned writable result directory at `/output`;
- private tmpfs `/tmp`, minimal `/dev`, new `/proc`;
- completely cleared child environment followed by a small fixed allowlist;
- no host networking (`--unshare-net`), new terminal session and parent-death kill;
- host RLIMIT address-space, CPU, core and output-file limits plus a hard wall clock;
- bounded controller capture and process-group hard termination.

Bubblewrap itself documents that it creates an empty filesystem namespace and that
sandbox strength depends on the arguments supplied. `--unshare-net` creates a new
network namespace; `--new-session` protects the controlling terminal boundary; and
`--die-with-parent` provides parent-death termination. For that reason arbitrary
Bubblewrap arguments are deliberately not part of any Ansible wire schema.

Primary mechanism references consulted 2026-09-14:

- https://manpages.debian.org/unstable/bubblewrap/bwrap.1.en.html
- https://github.com/containers/bubblewrap/blob/main/README.md
- https://github.com/ubuntu/ubuntu-release-notes/blob/main/docs/24.04/index.md

## Host prerequisites

The profile is **fail closed** unless the Bubblewrap binary can actually create its
required namespaces. Merely installing `bwrap` is insufficient. `availability`
performs a fixed namespace smoke test before reporting `available=true`.

Ubuntu 24.04 enables AppArmor restrictions on unprivileged user namespaces. Do not
globally disable that security feature merely to make this profile pass. A supported
host should provide an AppArmor policy granting `/usr/bin/bwrap` the required
user-namespace operation while retaining the restriction for sandbox children.
On Noble systems where it is not already installed/loaded, Ubuntu's experimental
`apparmor-profiles` package supplies `bwrap-userns-restrict` under
`/usr/share/apparmor/extra-profiles/`; install it as `/etc/apparmor.d/bwrap-userns-restrict`
and load it with `apparmor_parser`. CI performs this explicit host provisioning
before qualification. If a bwrap policy is already active, CI does not overwrite it.

If the namespace smoke still fails, the profile reports a typed unavailability such
as `USER_NAMESPACE_DENIED`, `BWRAP_FEATURE_UNAVAILABLE`, or
`SANDBOX_MOUNT_SETUP_FAILED`; it does not silently fall back to an unrestricted
process provider.

## Qualification

Run on the **deployment host** from a reviewed checkout:

```text
python -I -S -B run_isolation.py availability
python -I -S -B run_isolation.py qualify --state-root /private/ansible-state
```

`availability` is not qualification. `qualify` executes fixed negative probes and
requires all of these host observations:

1. read-only input is readable but cannot be written;
2. an unmounted host-secret sentinel is not readable;
3. common credential-bearing environment variables are absent;
4. an external IPv4 connection cannot be established;
5. HOME is the private sandbox home and PID namespace creation is observed;
6. a descendant can write only the dedicated output mapping;
7. a stdout flood is forcibly contained by the controller bound;
8. a hanging process tree is terminated at the wall deadline with no observed
   surviving descendants;
9. memory and CPU limits cause non-success before the workload can complete.

The report records platform/kernel, Bubblewrap path/version, implementation version,
profile fingerprint and fixed limits. A report is host-specific. CI qualification
on GitHub-hosted Ubuntu does not qualify another Linux installation.

## Explicit non-goals / remaining #13 gates

This profile trusts the host kernel, the reviewed Bubblewrap binary and the
host's namespace security policy. It is not a VM boundary and does not claim
resistance to a kernel exploit. It does not yet execute candidate code in
production: the fixed probe is the only executable wired to this profile.
Composition with #22 pinned snapshots and an actual registered runner remains
separately gated by #14 success/evidence semantics.

Windows is deliberately unsupported by `linux_bwrap_v1`; there is no fallback to
the Job Object provider. Windows Sandbox remains a separate #13 qualification gate.
