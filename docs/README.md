# Documentation index

## Start here

- [Current continuation handover](CONTINUATION-HANDOVER.md): implemented scope, merged work, verification, operational notes and next issue dependencies.
- [Release notes](RELEASE-NOTES.md): versioned runtime changes and local evidence.
- [Runtime contract](RUNTIME-CONTRACT.md): admission, lifecycle, five-axis results, replay and control semantics.
- [Read-only query contract](QUERY-CONTRACT.md): job inspection, event cursors and evidence-safe integration.
- [Security boundary](SECURITY.md) and [trusted policy](../POLICY.md): enabled versus unqualified authority.
- [CI evidence bundles](CI-EVIDENCE.md): retained reports, source/provenance/checksums and interpretation.

## Historical evidence

[Implementation evidence](IMPLEMENTATION-EVIDENCE.md),
[initial hosted CI qualification](CI-QUALIFICATION.md),
[Big Pickle audit](BIG-PICKLE-AUDIT.md) and
[candidate reconciliation](RECONCILIATION.md) preserve their original context.
Their older test counts/fingerprints are not substitutes for current qualification.
Machine-readable versioned evidence is under `../evidence/`.

Parent issue #1 remains open. The live next work is #12 (pinned data-only
transport), #13 (isolated pinned worktrees) and #14 (Ohmy adapter qualification).
Only noop execution is enabled today; a green test suite is not permission to
activate unqualified runners.
