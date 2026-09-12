# Control-plane policy

`techrote/ansible` is reserved for the human-initiated execution plane.

`techrote/intrallm` remains the agent-visible reference and task-data plane. Information may flow from `intrallm` into trusted orchestration as validated data, but runner selection and executable orchestration belong here.

Remote task slots must use a strict schema, fixed repository identifiers, pinned Git object IDs, bounded timeouts and an enumerated local runner registry. A slot must not be able to introduce a new runner implementation implicitly.

The local trusted checkout must not silently replace its own orchestration code when refreshing task data. Updating executable orchestration is a separate, explicit human action.

The initial `schemas/slot-v1.schema.json` records the data boundary. Executable runner/orchestrator files are intentionally separate from that schema.
