from typing import Literal, NotRequired, TypedDict


RiskLevel = Literal["low", "medium", "high"]
Route = Literal["auto_plan", "needs_human_approval", "blocked"]


class ServiceContext(TypedDict):
    owner: str
    tier: str
    deploy_window: str
    rollback: str


class AgentState(TypedDict):
    request: str
    service: NotRequired[str]
    change_type: NotRequired[str]
    service_context: NotRequired[ServiceContext]
    risk_level: NotRequired[RiskLevel]
    route: NotRequired[Route]
    approval: NotRequired[Literal["approved", "rejected"]]
    plan: NotRequired[list[str]]
    audit: NotRequired[list[str]]
