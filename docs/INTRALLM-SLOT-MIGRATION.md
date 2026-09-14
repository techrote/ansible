# Intrallm launcher-slot migration preview

This document records the **read-only, offline preparation** for issue #16. It is
not producer publication and it is not deployment-host qualification. The current
continuation is authorized for `techrote/ansible`; no write to `techrote/intrallm`
was performed while preparing this record.

## Read-only source observation — 2026-09-14

The fixed producer ref remains:

- repository: `techrote/intrallm`
- ref: `refs/heads/control/launcher-slots`
- resolved commit: `67a55d339863f603d333c7a327cd2eb7cb1f54b5`

The four observed slot blobs are:

| Path | Blob SHA | Observed generation | Status |
|---|---|---:|---|
| `slots/slot1.json` | `5fc85cdebc456290634e9bf71a0ed42210d55499` | 1 | legacy schema, idle |
| `slots/slot2.json` | `f40be08f6f472988ceb37d4572d74551147950d1` | 1 | legacy schema, idle |
| `slots/slot3.json` | `c9e60abf713fec274529337d8744a270060e86ed` | 1 | legacy schema, idle |
| `slots/slot4.json` | `5e809dd3390804153be7d424d2282b8567f2951a` | 1 | legacy schema, idle |

Those files still contain the retired `minimum_launcher_version` / `title` /
`message` shape. Current Ansible slot validation rejects them; there is no runtime
translation path.

Current Ansible `main` when this preview was produced is implementation 0.2.5 at
merge commit `566569c31eab85b27716cd67bc72214819b2b283`. Its four shipped slot
defaults are generation 1. The repository-visible migration floor is therefore 1.

## Candidate generation

The candidate uses **generation 2** for all four slots and leaves every assignment
idle. This is intentionally the smallest monotone migration from the recorded
repository state; it does not consume an arbitrary large generation range.

Generation 2 is only publishable after the actual deployment state is checked.
Before a producer PR is opened, run the current kernel against the deployment state
root and verify that no effective slot generation is already greater than 1. If a
deployment ledger has advanced further, regenerate the candidate at `max + 1`
instead of rewriting or deleting that ledger.

Exact candidate values:

```json
{"generation":2,"label":"Idle","schema_version":1,"slot":1,"state":"idle","task_id":"slot-1-intrallm-migration-g2"}
```

```json
{"generation":2,"label":"Idle","schema_version":1,"slot":2,"state":"idle","task_id":"slot-2-intrallm-migration-g2"}
```

```json
{"generation":2,"label":"Idle","schema_version":1,"slot":3,"state":"idle","task_id":"slot-3-intrallm-migration-g2"}
```

```json
{"generation":2,"label":"Idle","schema_version":1,"slot":4,"state":"idle","task_id":"slot-4-intrallm-migration-g2"}
```

No runner, model, target, reference, preflight or executable authority is present.

## Offline production-code validation

`tools/intrallm_slot_migration_preview.py` is credential-free and performs no
network operation. It:

1. validates all four values through the production `slot()` contract;
2. constructs exact Git blob/tree objects in memory;
3. feeds those objects through the production fixed-origin `collect_snapshot()`
   verifier, exercising the same eight-read ref → commit → root tree → slots tree →
   four blobs shape used by authenticated transport;
4. creates a temporary kernel state from shipped generation-1 defaults;
5. consumes the existing slot-1 generation-1 once task;
6. publishes the synthetic remote snapshot once, then repeats it.

For generation 2 the preview produced:

- transport fixed reads: **8**
- synthetic slots tree: `c69d92180b201b0190edc3766fb087250413a884`
- synthetic root tree: `13bebdad5a947448418096293a6bb1d5f08afee1`
- normalized slots digest:
  `b72aebe2e67e1925d9b729f7c7671d5384b0b6492bbed703586b2467939d96b8`
- first refresh: changed
- repeated refresh: unchanged, with ledger bytes unchanged
- effective generations after refresh: `[2, 2, 2, 2]`
- all effective slots after refresh: idle
- original once reservation `1:1`: preserved

The synthetic commit identity is deliberately not presented as authenticated
GitHub provenance. The full machine-readable record is
`evidence/intrallm-slot-migration-preview-v1.json`.

## Verification of this preparation slice

On Linux / Python 3.13.5, after adding the preview tooling/tests:

- test suite: **291 tests**, all passing except the existing 3 mechanism/platform
  skips;
- kernel qualification: **43/43** checks passing;
- runtime fingerprint remains
  `64e99a0b6bbf337f33a0a85a186d9b8d6c218812640f4f786881472811a5cd8f`;
- `real_agent_qualified=false` remains unchanged.

The preview files live under `tools/`, `tests/`, `docs/` and `evidence/`; no kernel
runtime file or runner registry is changed by this preparation slice.

## Remaining #16 publication/deployment gate

The following work is intentionally **not** done by this preview:

1. Re-check the producer ref and all four blobs immediately before publication.
2. Check the real deployment state with:
   `python -I -S -B run_kernel.py --state-root <PATH> slots`.
3. If every effective generation is at most 1, use generation 2; otherwise regenerate
   at the real maximum plus one.
4. With explicit authority for `techrote/intrallm`, open a **data-only** producer PR
   changing exactly the four `slots/slotN.json` files. Do not touch launcher scripts
   or the Lightning branch.
5. Re-resolve the merged producer ref and prove all four files are from one commit.
6. On the deployment host, opt in to remote slots and run authenticated refresh with
   a read-only Contents token supplied through stdin/prompt, never arguments/files.
7. Verify `slot-source` reports that exact producer commit and file provenance.
8. Repeat refresh and prove it is idempotent.
9. Verify trusted Ansible checkout files are unchanged and existing once reservations
   remain intact.

Only those real producer/deployment steps can close #16. A connector inspection or
this offline transport preview is not a substitute for them.
