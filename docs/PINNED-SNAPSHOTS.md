# Pinned inert repository snapshots

Implementation 0.2.3 / issue #22 provides the **preparation-only** slice of the
isolation gate in #13. It does not run candidate code and does not qualify a
sandbox. The output is inert repository data that a future, separately qualified
execution profile may receive as read-only input.

## Why this is not `git checkout`

The preparer deliberately does not use checkout, `git worktree add`, merge,
submodule, LFS, hooks or remote operations. Git attributes can associate paths
with `filter.<driver>.smudge` or long-running `filter.<driver>.process` commands;
checkout may therefore invoke configured external programs. For untrusted
candidate contents, preparation must not cross that executable boundary.

Instead, trusted code accepts only:

- repository ID `intrallm` or `dashminimix` from the existing fixed registry;
- an operator-resolved absolute ordinary Git checkout;
- a full 40-character lowercase commit object ID; and
- a host-generated 32-character lowercase job ID.

The Git executable is resolved by trusted host code. Its environment is rebuilt
from an allowlist with a scratch HOME/XDG config, system config disabled, prompts
and replace objects disabled, optional locking disabled, and a fixed empty hooks
path. No task field supplies a Git option, executable, URL, helper or destination.
The only object operations are exact `cat-file -t`, recursive NUL-delimited
`ls-tree`, and `cat-file --batch` blob reads against the pinned commit.

## Refusals and bounds

Version `ansible.snapshot.v1` refuses:

- short/mixed-case/non-commit object IDs;
- linked-worktree `.git` metadata and alternate object databases;
- symlink entries and gitlinks/submodules;
- unsupported tree modes or malformed object identities/output;
- `.git` path components, non-portable/control-character paths, DOS device names,
  case-insensitive collisions and file/directory prefix collisions;
- more than 20,000 files, tree/manifest data over 8 MiB, individual blobs over
  16 MiB, or total extracted bytes over 256 MiB; and
- unexpected hardlinks, symlink/reparse redirection or tampering in published
  snapshot state.

Git LFS pointer files remain ordinary inert blob bytes. The preparer never hydrates
LFS content. Executable mode (`100755`) is retained as metadata/host file mode;
that does **not** grant permission to execute the file.

## Publication, provenance and cleanup

Snapshots live under the private Ansible state root as:

`worktrees/<job-id>/<repository-id>/<commit-sha>/`

Preparation occurs in a random private `.prepare-*` sibling and is verified before
an atomic rename. Published state contains only `content/`, canonical
`manifest.jsonl` and `snapshot.json`. The marker binds the job, repository and
commit plus file count, total bytes and the SHA-256 of the complete manifest. Each
manifest row records the exact Git blob ID, mode, raw-byte SHA-256 and size.

Repeating the same identity verifies and reuses the snapshot. A mismatched or
tampered existing snapshot fails closed. Cleanup accepts no arbitrary filesystem
path: it derives the path from the same validated identifiers, revalidates marker,
manifest and all content, checks the fixed boundary, then removes only that exact
snapshot and empty identity parents.

This is integrity/provenance and cleanup containment under the existing trusted
host-user model. It is not protection from a malicious process already running as
the trusted user.

## Future execution profiles — selected, not qualified

Issue #13 still requires actual deployment-host isolation. The currently selected
profiles for later proof are:

### Linux candidate: Bubblewrap namespaces

A future provider may use Bubblewrap with all namespaces unshared, network left
unshared, a cleared environment, parent-death/new-session controls, read-only
candidate/reference binds, tmpfs/private writable scratch, and one dedicated result
output. Availability, mount policy, credential exclusion, descendant termination,
network-denial and escape tests must pass on each supported deployment host before
this profile can become qualified. CI merely having Linux process limits is not
that evidence.

### Windows candidate: Windows Sandbox

A future provider may use a `.wsb` profile with Networking, ClipboardRedirection,
AudioInput, VideoInput, PrinterRedirection and vGPU disabled, ProtectedClient where
supported, read-only mapped candidate/reference input and a dedicated writable
result mapping only. Windows Sandbox networking is otherwise enabled by default;
therefore omission of the explicit disable is a qualification failure. Feature
availability, mapped-folder boundaries, host credential visibility, process-tree
termination and negative network/filesystem tests must be demonstrated on the
actual deployment profile. A Windows Job Object alone is not this sandbox.

Neither profile is enabled by implementation 0.2.3. `omp_blind_review_v1` remains
disabled and `real_agent_qualified=false` until #13 plus the applicable #14 live
adapter/result gates are satisfied.

## Primary references

Consulted 2026-09-13:

- Git attributes and checkout filters: https://git-scm.com/docs/gitattributes
- Bubblewrap project/usage: https://github.com/containers/bubblewrap
- Windows Sandbox `.wsb` configuration: https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-configure-using-wsb-file
- Windows Sandbox command-line management: https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-cli

These documents describe available mechanisms. Repository tests plus actual host
negative tests—not documentation alone—establish qualification.
