from langchain_core.tools import tool


SERVICE_CATALOG = {
    "billing": {
        "owner": "payments-platform",
        "tier": "tier-1",
        "deploy_window": "Tue-Thu 10:00-16:00 UTC",
        "rollback": "Run billing rollback playbook and verify ledger drift.",
    },
    "checkout": {
        "owner": "commerce",
        "tier": "tier-1",
        "deploy_window": "Mon-Thu 09:00-15:00 UTC",
        "rollback": "Revert release flag, then rollback checkout service.",
    },
    "identity": {
        "owner": "security-platform",
        "tier": "tier-0",
        "deploy_window": "Manual approval only",
        "rollback": "Use identity emergency rollback playbook.",
    },
    "notifications": {
        "owner": "growth-platform",
        "tier": "tier-2",
        "deploy_window": "Any weekday",
        "rollback": "Rollback worker image and replay failed messages.",
    },
}


@tool
def lookup_service(service: str) -> dict:
    """Return service ownership, tier, deploy window, and rollback notes."""
    return SERVICE_CATALOG.get(
        service,
        {
            "owner": "unknown",
            "tier": "unknown",
            "deploy_window": "unknown",
            "rollback": "No rollback playbook found.",
        },
    )
