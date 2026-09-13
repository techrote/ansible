# Fixed-origin data-only slot transport

Issue #12 / implementation 0.2.0 adds an **operator-only**, explicitly enabled
transport. Execution remains `ansible.execution.v1`, trusted-noop-only. No worker
receives a credential or a new network capability. Existing numbered launchers,
local `refresh DIRECTORY`, and the panel's cached redraw behavior are unchanged.

## Source and deployment gate

The only approved source is `techrote/intrallm`, ref
`refs/heads/control/launcher-slots`, paths `slots/slot1.json` through
`slots/slot4.json`, over direct TLS to `api.github.com:443`. These identifiers
are constants in trusted code, not configurable URLs or task fields.

Read-only connector inspection on 2026-09-13 found source commit
`67a55d339863f603d333c7a327cd2eb7cb1f54b5`. Its first slot, blob
`5fc85cdebc456290634e9bf71a0ed42210d55499`, still uses the retired launcher schema:
`title`, `message`, and `minimum_launcher_version`, rather than the current
required `label`. It is also idle generation 1, unlike Ansible's armed generation
1 bootstrap. **This source is intentionally refused with
`REMOTE_SLOT_SCHEMA_INVALID`, not translated or silently assigned a new generation.**
Issue #16 tracks an explicitly authorized data-only producer migration and actual
host-authenticated deployment acceptance. This change does not modify intrallm.

## Operator interface

After reviewing the code and satisfying #16, add `"remote_slots_enabled": true`
to ignored `config/local.json`. It defaults to false; no network connection or
credential prompt occurs without this opt-in. Every refresh is an explicit action:

```powershell
py -3 -I -S -B run_kernel.py refresh-remote
py -3 -I -S -B run_kernel.py slot-source
```

The first command prompts without echo for a Contents-read credential limited to
the intrallm repository. There is no token argument, stored token, ambient
`GH_TOKEN`/`GITHUB_TOKEN` fallback, credential-helper execution, or netrc lookup.
For a trusted integration, `refresh-remote --token-stdin` reads one bounded ASCII
token line from stdin. Never paste tokens into chat, task JSON, source files or
shell command arguments. No automatic credential persistence is provided.

Use `python3` on Linux. Global `--state-root PATH` precedes the command. The
selected state root is canonicalized and checked before any fetch. Transport or
schema failure creates no state root. Publication uses the ordinary execution
lock only after the complete verified snapshot has arrived; concurrent execution
can cause `LOCK_BUSY` without changing the ledger.

`slot-source` is read-only and creates no missing directories. It returns the
latest effective remote provenance, or null for local/unbound state. Existing
`slots` output retains its prior shape.

## Verification and limits

The transport performs at most eight GETs, with no retries or redirects:

1. Resolve the fixed ref once to a commit object ID.
2. Read that exact commit's root tree identity.
3. Read and independently hash the nonrecursive root tree.
4. Read and independently hash its regular `slots` subtree.
5. Fetch four regular non-executable slot blobs by exact object ID; recompute
   their Git SHA-1 object IDs and separate SHA-256 content hashes.

The authenticated GitHub API attests the ref-to-commit and commit-to-root-tree
relationship. This is not independent verification of a signed/raw commit object.
Subsequent tree and blob hashes are independently reconstructed. Git SHA-1 IDs,
raw-byte SHA-256 hashes and canonical-slot SHA-256 digests have distinct roles.
No URL returned in any response is followed. Unselected tree entries are inert
hash material and are never materialized or executed.

Each response is limited to 65,536 bytes; trees are nonrecursive, at most 128
entries, with duplicate/ambiguous names and truncation refused. Parsed JSON uses
the existing depth-20/node-4096 decoder. All four slots must satisfy the current
schema and runtime checks. Selected symlink, submodule and executable entries
are refused. Content encoding other than identity is refused. Large otherwise
valid repositories outside these explicit limits are unsupported, not retried
with weaker checks.

A fixed nonforking helper runs with `-I -S -B`, a clean environment, closed
inherited descriptors and the existing Windows Job/Linux resource and parent-death
controls. The token travels over its stdin pipe after Windows assignment, never
in its command or environment. The parent enforces a 30-second helper deadline
plus bounded termination/pipe cleanup, covering DNS and slow-header stalls which
socket timeouts alone cannot bound. The reader also uses a 25-second budget and
socket-operation timeouts capped at five seconds. Output is capped at 64 KiB;
stderr is capped at 4 KiB and never echoed. No downloaded source is executed.
The helper writes no files; its working directory is the trusted checkout, with
bytecode disabled. Credentials exist in process memory; Python does not provide
a secure-erasure guarantee for those immutable buffers.

Direct `http.client` TLS does not use proxy or authentication-helper discovery.
Its certificate/hostname checks remain enabled; the helper environment excludes
proxy/CA override variables. Authentication errors, redirects, rate limits,
timeouts and protocol failures produce allowlisted codes, never raw HTTP bodies,
headers, exception strings or credentials.

## Durable publication and compatibility

The parent validates the bounded helper receipt again, detaches mutable input,
and publishes the complete quartet and provenance in one hash-chained
`slots_remote_refreshed` event. Generation rollback, same-generation content
replacement and once-reservation rules are unchanged. Any bad quartet preserves
the previous ledger. An identical source snapshot is idempotent; a different
commit with identical slot contents records new provenance once.

`ansible.slot-source.v1` records the fixed source/ref, commit/root/slots tree IDs,
per-path blob ID and byte count, raw content hash, canonical value hash and full
snapshot digest. The schema is `schemas/slot-source-v1.schema.json`. Replay
validates provenance shape and its binding to recorded values. This is trusted
host evidence, not a signature against a compromised host user. Original raw
response bodies, arbitrary metadata and authorization headers are not persisted.
A later changed local refresh removes the effective remote attribution.

Ansible 0.1.x does not understand the new event type and will fail closed when
reading such a ledger. Do not downgrade after remote publication without a
reviewed migration. No ledger deletion or once-claim reset is part of installation.

## Verification scope

Tests cover deterministic API fixtures, actual local TLS requests with the fixed
reader, certificate verification failure, credential-safe redirect refusal,
response bounds, schema/hash/path failures, native Git hash agreement, replay,
atomicity, idempotence, controls, real helper deadlines and output floods. The
loopback tests use a clearly test-only localhost certificate/key; it is never
loaded by production code and must not be installed as a system trust anchor.

The 35-check `qualify` command still qualifies **noop execution only**. It does
not certify authenticated transport deployment. The current producer inspection
used the authorized GitHub connector, not this helper with a live credential.
Actual producer migration and live transport/deployment evidence remain #16.
No unqualified live model or candidate-code runner is enabled.

## Primary references consulted 2026-09-13

- GitHub references: https://docs.github.com/en/rest/git/refs
- GitHub commit-to-tree API: https://docs.github.com/en/rest/git/commits
- GitHub tree modes and nonrecursive traversal: https://docs.github.com/en/rest/git/trees
- GitHub raw blob media type and read permission: https://docs.github.com/en/rest/git/blobs
- Python TLS/HTTP client: https://docs.python.org/3.13/library/http.client.html

API version is pinned to `2026-03-10`. Tests and actual host evidence, not these
references alone, establish the implemented behavior.
