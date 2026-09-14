# Documentation index

## Start here

- [Current continuation handover](CONTINUATION-HANDOVER.md): implemented scope, merged work, verification, operational notes and next issue dependencies.
- [Release notes](RELEASE-NOTES.md): versioned runtime changes and local evidence.
- [Runtime contract](RUNTIME-CONTRACT.md): admission, lifecycle, five-axis results, replay and control semantics.
- [Read-only query contract](QUERY-CONTRACT.md): job inspection, event cursors and evidence-safe integration.
- [Security boundary](SECURITY.md) and [trusted policy](../POLICY.md): enabled versus unqualified authority.
- [CI evidence bundles](CI-EVIDENCE.md): retained reports, source/provenance/checksums and interpretation.

- [Fixed-origin slot transport](SLOT-TRANSPORT.md): opt-in data-only fetch, provenance, bounds and the separate producer/deployment gate #16.
- [Intrallm slot migration preview](INTRALLM-SLOT-MIGRATION.md): validated generation-2 idle candidate and the remaining authorized producer/deployment gate.

- [Job-bound evidence](EVIDENCE-BINDING.md): terminal anchors, legacy compatibility and success revalidation.
- [Ohmy readiness](OHMY-INTEGRATION-READINESS.md): pinned upstream inspection and remaining adapter gates.
- [Pinned inert snapshots](PINNED-SNAPSHOTS.md): exact Git object materialization, ownership-safe cleanup and unqualified future isolation profiles.
- [Snapshot/isolation composition](ISOLATION-COMPOSITION.md): exact snapshot → trusted probe → Linux Bubblewrap qualification and probe-hash binding.

## Historical evidence

[Implementation evidence](IMPLEMENTATION-EVIDENCE.md),
[initial hosted CI qualification](CI-QUALIFICATION.md),
[Big Pickle audit](BIG-PICKLE-AUDIT.md) and
[candidate reconciliation](RECONCILIATION.md) preserve their original context.
Their older test counts/fingerprints are not substitutes for current qualification.
Machine-readable versioned evidence is under `../evidence/`.

Parent issue #1 remains open. Issues #13, #14 and #32 are completed prerequisites; issue #38 hardens reusable composition evidence, while the remaining external integration gate is #16 producer migration and authenticated deployment.
Only noop execution is enabled today; a green test suite is not permission to
activate unqualified runners.
