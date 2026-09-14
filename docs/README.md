# Documentation index

## Start here

- [Final 0.2.7 continuation handover](CONTINUATION-HANDOVER-027-FINAL.md): merged identity, final qualification evidence, completed #16 deployment and remaining trust boundaries.
- [0.2.7 final qualification note](RELEASE-NOTES-0.2.7-FINAL.md): final PR/merge verification; it supersedes the provisional local-verification paragraph in the historical release notes.
- [Release notes](RELEASE-NOTES.md): versioned runtime history; older point-in-time verification paragraphs remain historical rather than being rewritten after later audit fixes.
- [Runtime contract](RUNTIME-CONTRACT.md): admission, lifecycle, five-axis results, replay and control semantics.
- [Read-only query contract](QUERY-CONTRACT.md): job inspection, event cursors and evidence-safe integration.
- [Security boundary](SECURITY.md) and [trusted policy](../POLICY.md): enabled versus unqualified authority.
- [CI evidence bundles](CI-EVIDENCE.md): retained reports, source/provenance/checksums and interpretation.

- [Fixed-origin slot transport](SLOT-TRANSPORT.md): opt-in data-only fetch, provenance and bounded authenticated refresh.
- [Intrallm slot migration preview](INTRALLM-SLOT-MIGRATION.md): generation-2 migration preparation; issue #16 records the completed producer publication and real deployment acceptance.

- [Job-bound evidence](EVIDENCE-BINDING.md): terminal anchors, legacy compatibility and success revalidation.
- [Ohmy readiness](OHMY-INTEGRATION-READINESS.md): pinned upstream inspection and remaining adapter gates.
- [Pinned inert snapshots](PINNED-SNAPSHOTS.md): exact Git object materialization, ownership-safe cleanup and unqualified future isolation profiles.
- [Snapshot/isolation composition](ISOLATION-COMPOSITION.md): exact snapshot → trusted probe → shared Linux Bubblewrap boundary, exact check set and final #38 qualification.

## Evidence generations

[Implementation evidence](IMPLEMENTATION-EVIDENCE.md),
[initial hosted CI qualification](CI-QUALIFICATION.md),
[Big Pickle audit](BIG-PICKLE-AUDIT.md) and
[candidate reconciliation](RECONCILIATION.md) preserve their original context.
Their older test counts/fingerprints are not substitutes for current qualification.
Machine-readable versioned evidence is under `../evidence/`.

For issue #38, `../evidence/continuation-v027.json` is the preserved pre-final-audit
local snapshot. The merged/final identity is recorded in
`../evidence/continuation-v027-final.json`.

Parent issue #1 remains open. Issues #13, #14, #16, #32 and #38 are completed.
The producer/deployment migration is no longer an external gate. Only noop execution
is enabled today; a green test suite is not permission to activate unqualified runners.
