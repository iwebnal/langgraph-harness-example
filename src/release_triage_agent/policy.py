from .state import AgentState, RiskLevel, Route


HIGH_RISK_TERMS = ("payment", "auth", "database", "migration", "delete", "prod")
MEDIUM_RISK_TERMS = ("api", "schema", "cache", "dependency", "background job")


def classify_change(request: str) -> tuple[str, str | None]:
    text = request.lower()

    service = None
    for candidate in ("billing", "checkout", "identity", "notifications"):
        if candidate in text:
            service = candidate
            break

    if "rollback" in text:
        change_type = "rollback"
    elif "migration" in text or "schema" in text:
        change_type = "data_change"
    elif "deploy" in text or "release" in text:
        change_type = "release"
    else:
        change_type = "investigation"

    return change_type, service


def assess_risk(state: AgentState) -> RiskLevel:
    request = state["request"].lower()
    service_context = state.get("service_context")

    if any(term in request for term in HIGH_RISK_TERMS):
        return "high"

    if service_context and service_context["tier"] == "tier-1":
        return "medium"

    if any(term in request for term in MEDIUM_RISK_TERMS):
        return "medium"

    return "low"


def route_for(state: AgentState) -> Route:
    risk = state.get("risk_level")

    if risk == "high":
        return "needs_human_approval"

    if risk in {"low", "medium"}:
        return "auto_plan"

    return "blocked"
