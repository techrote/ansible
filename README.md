# techrote/ansible

Private human-initiated orchestration plane.

This repository separates trusted human-facing orchestration from `techrote/intrallm`, which remains the agent-visible reference/data plane.

## Trust boundary

- `ansible` owns trusted launcher/orchestrator code and runner selection.
- `intrallm` supplies validated reference/task data only.
- Slot assignments use `schemas/slot-v1.schema.json` and may select only runner types already installed in the trusted local checkout.
- Updating task data and updating executable orchestration are separate operations.

## Current committed foundation

The repository currently contains the trust policy, text-normalization rules, local-state ignore rules and strict slot schema. The executable launcher/orchestrator layer is not yet committed.
