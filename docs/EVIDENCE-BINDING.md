# Job-bound evidence and success revalidation

Issue #18 / implementation 0.2.1 repairs a reproduced cross-job artifact mix-up.
Previously, copying `worker.json`, `provider.json` and their internally consistent
manifest from job A over successful job B left B reporting success. Hash agreement
inside a replaceable bundle did not bind it to the original job or terminal event.

## New manifest and journal anchor

Every new run with normalized worker output writes `ansible.evidence-manifest.v2`.
The manifest binds the host job ID, fixed runner ID/contract/provider, source
fingerprint, request-byte SHA-256 and the hashes of exactly `metadata.json`,
`worker.json` and `provider.json`. The schema admits only the current noop runner;
adding an adapter requires an explicit reviewed schema/predicate implementation.

The exact manifest bytes are SHA-256 hashed before terminal publication. That
hash is stored as `manifest_sha256` alongside the terminal event's result in the
existing hash-chained journal. It is not part of the execution-result wire object,
so existing result and query response shapes remain compatible. Rejected jobs or
failures without normalized output do not invent a manifest/anchor.

On success queries, the reader validates the anchor, manifest schema and job ID,
fixed file whitelist, all file hashes, metadata binding, normalized worker schema
and job identity. It then re-runs the registered noop success predicate using the
same file snapshot and stored host infrastructure observations. Success requires
admitted/completed host axes, complete evidence, matching transport, a genuinely
successful normalized message and host provider enforcement evidence.

A complete-but-swapped bundle, a rehashed changed output, metadata drift or
contradictory stored success therefore returns `invalid_result` or a typed state
refusal. Queries do not rewrite the journal or result file. Historical phase
`completed` can coexist with a now-invalid result, and must not be used alone as
a success signal. `result`, `inspect`, `events` and `status` share this check.
Forensic export still includes original file contents plus the separately verified
result; raw historical copies are not a second success authority.

## Compatibility and limits

Published versions 0.1.0 through 0.1.5 and 0.2.0 generated the legacy two-file hash
map. Their valid histories remain readable without mutation or invented anchors.
The reader now checks their worker schema/job identity, registered noop predicate
and host success axes too. Legacy records do not acquire the new metadata/hash
anchor guarantees retroactively. Unknown/new result versions cannot select the
legacy exemption; new success results require their terminal anchor.

The internal `verify_evidence` method verifies pre-publication integrity and job
binding. It is not a terminal success decision: integration clients must use the
versioned result/query interfaces. Failed/rejected results remain available as
diagnostics and are not transformed into successes by this mechanism.

New anchor fields and manifest format are not understood by old readers. Do not
silently downgrade a state root after running 0.2.1. Preserve existing reservation
records and evidence; no automatic rewrite, truncation or once-claim reset occurs.

This is integrity/association protection under the documented trusted-host-user
model, not a cryptographic signature against someone who can rewrite the entire
journal and trusted code. It does not enforce hostile-code filesystem/network
isolation or prove model execution. Those remain #13/#14 gates.

## Verification

Twenty-two new tests produced 20 reported failures (including subtest failures)
against v0.2.0. After repair, all pass. Coverage includes swapped bundles,
rehashed output/metadata, missing/bad/premature anchors, legacy compatibility and
wrong-job output, provider/retry errors, contradictory success axes, fixed paths,
all query surfaces, no query mutation, and single lifecycle-snapshot reads.

Local Linux/Python 3.13.5: 243 tests, 242 passed and one Windows-only skip; all 35
noop qualification checks passed. Hosted results are recorded on the repair PR.

A separate local integration check generated a real noop result using the reviewed
v0.1.5 source tree `03860f850bd314d7eb7f333a859205c717beb2a1`, then read it with
v0.2.1. The result and every state-file hash were unchanged. This complements the
synthetic legacy conversion tests; no historical state was upgraded in place.
