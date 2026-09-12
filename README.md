# techrote/ansible

Private human-initiated execution plane for trusted local orchestration.

This repository deliberately separates executable launcher/controller code from `techrote/intrallm`, which remains the agent-visible reference/data plane.

## Trust boundary

- `ansible` may execute trusted local orchestration code.
- `intrallm` may supply untrusted task/reference data only.
- Nothing retrieved from `intrallm` is executed as code.
- Remote slot assignments select only enumerated local runner types.
- Arbitrary shell commands, script paths, hooks, executable payloads, and path traversal are rejected.

See `POLICY.md` for the security model and `orchestrator/README.md` for the TUI.
