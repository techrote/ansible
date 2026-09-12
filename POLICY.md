# Trusted execution policy

`techrote/ansible` contains trusted executable code beneath Omnipanel.
`techrote/intrallm`, model output, repository contents and task assignments are
inert data. They cannot register runners, supply commands/modules/hooks,
select executables, alter an environment, or update the trusted checkout.

Trusted-code updates are explicit operator actions, separate from slot-data
refreshes. Ansible does not fetch or execute code from `intrallm` in this release.
Request validation must include the published schema **and** runtime registry,
capability, resource, generation and path checks.

Ansible does not depend on Omnipanel. It does not schedule DAGs, Race/Diversity,
rank models, adjudicate candidates, or provide the full orchestration TUI.
Provider-specific parsing belongs to Ohmy. Generic worker outcome assertions
are insufficient without the registered runner's trusted success predicate and
host-observed infrastructure/evidence checks.

Only `noop_v1` is enabled. Its provider is trusted-code-only, not an untrusted
execution sandbox. No network, credential, repository test/build, publication,
VM, arbitrary-path export or live model capability is granted. Adding any of
these requires a trusted implementation change and its own qualification gate.

An operator control receipt is not task success or proof of containment.
Controller exit 0, agent-end markers and clean transport must never establish
semantic success on their own. Corrupt or interrupted state fails closed.

Keep runtime state outside source checkouts. Keep secrets out of requests and
logs. The host user, installed interpreter, checkout, state directory and OS
are trusted; this implementation does not defend against their compromise.
