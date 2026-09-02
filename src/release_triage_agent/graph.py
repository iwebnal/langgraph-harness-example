from langgraph.graph import END, START, StateGraph

from .policy import assess_risk as assess_policy_risk
from .policy import classify_change, route_for
from .state import AgentState
from .tools import lookup_service


def append_audit(state: AgentState, event: str) -> list[str]:
    return [*state.get("audit", []), event]


def intake(state: AgentState) -> AgentState:
    change_type, service = classify_change(state["request"])
    return {
        "change_type": change_type,
        "service": service,
        "audit": append_audit(state, f"intake: change_type={change_type}, service={service}"),
    }


def retrieve_context(state: AgentState) -> AgentState:
    service = state.get("service")
    if not service:
        return {
            "service_context": {
                "owner": "unknown",
                "tier": "unknown",
                "deploy_window": "unknown",
                "rollback": "Ask for the affected service before changing anything.",
            },
            "audit": append_audit(state, "retrieve_context: no service detected"),
        }

    context = lookup_service.invoke({"service": service})
    return {
        "service_context": context,
        "audit": append_audit(state, f"retrieve_context: owner={context['owner']}, tier={context['tier']}"),
    }


def assess_risk(state: AgentState) -> AgentState:
    risk_level = assess_policy_risk(state)
    route = route_for({**state, "risk_level": risk_level})
    return {
        "risk_level": risk_level,
        "route": route,
        "audit": append_audit(state, f"assess_risk: risk={risk_level}, route={route}"),
    }


def human_approval(state: AgentState) -> AgentState:
    approval = state.get("approval")
    if approval == "approved":
        event = "human_approval: approved"
    elif approval == "rejected":
        event = "human_approval: rejected"
    else:
        event = "human_approval: approval required"

    return {"audit": append_audit(state, event)}


def draft_plan(state: AgentState) -> AgentState:
    context = state["service_context"]
    plan = [
        f"Confirm owner: {context['owner']}.",
        f"Use deploy window: {context['deploy_window']}.",
        "Run unit, integration, and smoke tests before merging.",
        f"Prepare rollback: {context['rollback']}",
    ]

    if state["risk_level"] == "high":
        plan.insert(0, "Require explicit approval from the service owner.")

    return {
        "plan": plan,
        "audit": append_audit(state, "draft_plan: plan created"),
    }


def blocked_plan(state: AgentState) -> AgentState:
    return {
        "plan": ["Do not execute. Ask for missing service, owner, and rollback details."],
        "audit": append_audit(state, "blocked_plan: insufficient information"),
    }


def approval_route(state: AgentState) -> str:
    if state.get("route") == "needs_human_approval":
        return "human_approval"
    if state.get("route") == "auto_plan":
        return "draft_plan"
    return "blocked_plan"


def after_approval_route(state: AgentState) -> str:
    if state.get("approval") == "approved":
        return "draft_plan"
    return "blocked_plan"


def build_graph():
    builder = StateGraph(AgentState)
    builder.add_node("intake", intake)
    builder.add_node("retrieve_context", retrieve_context)
    builder.add_node("assess_risk", assess_risk)
    builder.add_node("human_approval", human_approval)
    builder.add_node("draft_plan", draft_plan)
    builder.add_node("blocked_plan", blocked_plan)

    builder.add_edge(START, "intake")
    builder.add_edge("intake", "retrieve_context")
    builder.add_edge("retrieve_context", "assess_risk")
    builder.add_conditional_edges(
        "assess_risk",
        approval_route,
        {
            "human_approval": "human_approval",
            "draft_plan": "draft_plan",
            "blocked_plan": "blocked_plan",
        },
    )
    builder.add_conditional_edges(
        "human_approval",
        after_approval_route,
        {
            "draft_plan": "draft_plan",
            "blocked_plan": "blocked_plan",
        },
    )
    builder.add_edge("draft_plan", END)
    builder.add_edge("blocked_plan", END)

    return builder.compile()


graph = build_graph()
