# Ansible: trusted execution kernel

A small local execution substrate beneath Omnipanel, **not** the Red Hat Ansible
project. Omnipanel owns orchestration. Ohmy owns provider-specific normalization.
Ansible owns admission, fixed runner selection, execution lifecycle and evidence.

**Implementation 0.1.0 / `ansible.execution.v1` / trusted-noop-only profile.**
The enabled runner is `noop_v1`. `omp_blind_review_v1` is deliberately disabled;
requests for it return `RUNNER_NOT_QUALIFIED`. This is working kernel code, not a
production sandbox for agents or arbitrary repository code. See
[the verified scope](docs/IMPLEMENTATION-EVIDENCE.md) before integrating it.

## Run on Windows

Install a trusted Python 3.12+ interpreter with the Windows `py.exe` launcher.
From a reviewed checkout, run `launcher1.cmd` for the once-only bootstrap smoke,
or `orchestrator.cmd` for the minimal local status/control panel. These wrappers
use Windows PowerShell 5.1 and a fixed script; no multiline paste is needed.
A repeated launch of the same once-only generation is refused, even after a
crash. Runtime state stays under `%LOCALAPPDATA%\techrote-ansible`.

Each command below is a separate invocation from the repository root:

```powershell
py -3 -I -S -B run_kernel.py contract
py -3 -I -S -B run_kernel.py qualify
py -3 -I -S -B run_kernel.py status
```

The wrappers and Job Object implementation are included but require Windows
qualification; the committed local execution evidence was produced on Linux.

## Other commands

On Linux substitute `python3` for `py -3`; state defaults to
`~/.local/state/techrote-ansible`. A trusted operator may select an external
state directory with `--state-root PATH` before the command. Do not point it
inside a repository or share it with an untrusted worker.

```text
python -I -S -B run_kernel.py run examples/noop-request.json
python -I -S -B run_kernel.py run -
python -I -S -B run_kernel.py result JOB_ID
python -I -S -B run_kernel.py cancel JOB_ID
python -I -S -B run_kernel.py contain JOB_ID
python -I -S -B run_kernel.py export JOB_ID
python -I -S -B run_kernel.py recover
python -I -S -B run_kernel.py refresh DIRECTORY_WITH_FOUR_SLOT_JSON_FILES
```

`run -` reads one bounded JSON document from stdin and executes synchronously.
Query/control commands can run in another terminal. A control receipt means
**requested**, not verified termination. `result` revalidates success evidence;
the convenience `result.json` file alone is not authoritative.

`refresh` reads only `slot1.json` through `slot4.json`. It neither downloads remote
code nor updates the trusted checkout. There is currently **no remote fetch**.
Slot 1 starts armed; slots 2-4 start idle. The panel's R key redraws cached data,
not a network refresh. Q leaves active controller processes running.

## Development and evidence

Runtime and tests use the Python standard library only. No `pip install` is needed.

```text
python -B -m unittest discover -s tests -v
python -I -S -B run_kernel.py qualify
```

See [runtime contract](docs/RUNTIME-CONTRACT.md), [security boundary](docs/SECURITY.md),
[Issue #1 reconciliation](docs/RECONCILIATION.md), and
[implementation evidence](docs/IMPLEMENTATION-EVIDENCE.md).
Never enable real agents solely because the noop qualification profile passes.
