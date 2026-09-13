# Reproducible qualification bundles

Issue #3 extends the hosted Windows/Linux matrix without changing the runtime
profile. Only `noop_v1` is enabled; `real_agent_qualified` remains false.
PR #2 was merged on 2026-09-13; earlier reports describing it as draft are
historical evidence, not the current publication state.

Every matrix job uploads a private repository Actions artifact named
`kernel-<os>-py<version>-<run-id>-<attempt>`, retained for 14 days. Download it
from the workflow run. Artifact availability is not proof of successful tests:
inspect the job conclusion and the individual exit records.

The artifact contains `unittest.txt` (test stdout), `tests.stderr.txt` (unittest's
normal verbose report), `tests.exit.json`, `qualification.json`,
`qualify.stderr.txt`, `qualify.exit.json`, `provenance.json`, `source.tar`, and
`checksums.json`. If a command never ran, its files may be absent. Missing evidence
must not be treated as a pass. Capture preserves the subprocess exit code;
launch failures return 125 and capture deadlines return 124. No failed step has
`continue-on-error`. Qualification and bundle collection still run after a test
failure so diagnosis can retain independent evidence.

`source.tar` is `git archive` of the checked-out commit. It contains committed
source only: no `.git`, checkout credentials, untracked `config/local.json`, or
runtime state. A dirty tracked checkout refuses archive creation. The upload
uses a fixed filename whitelist, not the whole working directory. Reports and
archives are hashed with SHA-256; provenance records only explicit non-secret
fields, not the environment. As with any source repository, never commit secrets.

For pull-request runs `checkout_sha` can be GitHub's synthetic merge commit;
`requested_head_sha` records the proposed branch head separately. Do not confuse
those identifiers with the kernel's independently reported source fingerprint.
The archive's source is suitable for reproducing verification in a reviewed
checkout, not for silently replacing a user's trusted executable installation.

Local reproduction from a trusted checkout:

```text
python -I -S -B tools/ci_evidence.py tests
python -I -S -B tools/ci_evidence.py qualify
python -I -S -B tools/ci_evidence.py bundle
```

These are development commands, not registered runtime capabilities. There are
no credentials, network operations or source updates in the evidence script.
Hosted noop qualification never substitutes for deployment-host qualification or
hostile-code isolation and live Ohmy/OMP adapter acceptance.
