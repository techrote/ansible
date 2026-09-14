"""Cross-platform isolation profile registry without runner activation authority."""
from __future__ import annotations

import platform

from . import VERSION
from .isolation_bwrap import PROFILE_CONTRACT as LINUX_CONTRACT, availability as linux_availability
from .isolation_windows import PROFILE_CONTRACT as WINDOWS_CONTRACT, availability as windows_availability

REGISTRY_CONTRACT = "ansible.isolation-registry.v1"
PROFILE_CONTRACTS = (LINUX_CONTRACT, WINDOWS_CONTRACT)


def host_report() -> dict:
    system = platform.system()
    if system == "Linux":
        value = linux_availability()
        return {"registry_contract": REGISTRY_CONTRACT, "implementation_version": VERSION,
                "profile_contract": LINUX_CONTRACT, "platform": system,
                "available": value.get("available") is True,
                "profile_qualified": False, "qualification_not_run": True,
                "qualification_command": "run_isolation.py qualify",
                "runner_activation": False, "real_agent_qualified": False,
                "deployment_qualified": False, "reason": value.get("reason"),
                "mechanism": {key: value[key] for key in ("bwrap_path", "bwrap_version", "kernel") if key in value}}
    if system == "Windows":
        value = windows_availability()
        return {"registry_contract": REGISTRY_CONTRACT, **value}
    return {"registry_contract": REGISTRY_CONTRACT, "implementation_version": VERSION,
            "profile_contract": "unsupported", "platform": system, "available": False,
            "profile_qualified": False, "runner_activation": False,
            "real_agent_qualified": False, "deployment_qualified": False,
            "reason": "ISOLATION_PLATFORM_UNSUPPORTED"}
