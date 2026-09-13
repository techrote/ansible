# Ohmy integration readiness — observed 2026-09-13

This is a pinned read-only compatibility assessment for #14, not an adapter
implementation, upstream approval or live model qualification.

## Inspected publications

| Publication | Immutable revision / file identity | Observation |
|---|---|---|
| Ohmy main | `4e1a60f00c1c8850bd97b8e584f08f3e94df46f7` | Planning/docs only; no merged production runtime |
| Main `docs/INTERFACES.md` | blob `a8e3b3b910dd64b8136008cafb0bb6f63291a501` | Initial Ansible integration is explicitly fixture-first |
| Draft PR #50, `implementation/ohmy-v1-integrated` | head `9ff7e7f8c21569c18816a7eb8d49a42e8464ab5c` | Unmerged implementation frontier; live qualification not claimed |
| Draft `src/ohmy/events.py` | blob `9d7e8987771341fa7ee705b2b55cfd3bb96309d5` | Typed normalized events, run/session/sequence/provenance, counts and failure signals |

Primary repository references:
- https://github.com/techrote/ohmy/tree/4e1a60f00c1c8850bd97b8e584f08f3e94df46f7
- https://github.com/techrote/ohmy/pull/50
- https://github.com/techrote/ohmy/blob/9ff7e7f8c21569c18816a7eb8d49a42e8464ab5c/src/ohmy/events.py

These sources were read using the authorized GitHub connector. No upstream code
was imported/executed, no branch was merged, and no Ohmy repository was modified.
Re-read current publications before the next implementation; these pins describe
this inspection, not a promise that the draft interface will remain unchanged.

## Boundary implications

The draft event vocabulary distinguishes READY, PROMPT_RESOLVED, RUN_SETTLED,
message/tool/retry/fallback events and failures. Events have schema version 1,
run/session IDs, sequence, UTC observation time and SYNTHETIC/RECORDED/LIVE
provenance. Those fields are not the existing `ansible.worker.v1` terminal result.

In particular, MessageData records text/thinking character counts, tool-call
counts, stop reasons and failure signals. Counts are not final answer text. A
terminal event or a positive character count cannot be translated directly into
Ansible semantic success, nor can an unmerged event dataclass be presumed to be
a stable serialized adapter contract. An adapter still needs reviewed run-finality,
job/session binding, bounded result/artifact extraction and error precedence.

Continue to keep raw OMP parsing inside Ohmy. Ansible's host controls, infrastructure
observations and trusted registered predicate must remain independent. Provider
429/retry exhaustion after controller exit zero must remain failure; zero-tool
analysis can be valid, but does not prove implementation activity or artifact
correctness. Synthetic provenance is never live qualification.

## Work completed on the Ansible side

Issue #18 repairs a concrete prerequisite: success evidence is now job-bound and
anchored to its terminal journal event, rather than trusting a replaceable bundle's
internal hashes alone. Existing worker/outcome fixtures remain active; the new
22 regression tests add stale/copied/rehashed evidence and legacy-read protection.
See [EVIDENCE-BINDING.md](EVIDENCE-BINDING.md).

Actual isolated worktree/provider qualification (#13), stable upstream result
contract selection and live adapter acceptance (#14) remain open. This assessment
does not create a runnable adapter or enable `omp_blind_review_v1`.
