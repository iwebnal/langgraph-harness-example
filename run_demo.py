from release_triage_agent.graph import graph


def print_result(title: str, result: dict) -> None:
    print(f"\n== {title} ==")
    print(f"risk: {result['risk_level']}")
    print(f"route: {result['route']}")
    print("plan:")
    for step in result["plan"]:
        print(f"- {step}")
    print("audit:")
    for event in result["audit"]:
        print(f"- {event}")


low_risk = graph.invoke(
    {
        "request": "Deploy notifications copy update for the weekly digest",
    }
)
print_result("Low-risk release", low_risk)

high_risk_without_approval = graph.invoke(
    {
        "request": "Deploy billing database migration to prod",
    }
)
print_result("High-risk release without approval", high_risk_without_approval)

high_risk_with_approval = graph.invoke(
    {
        "request": "Deploy billing database migration to prod",
        "approval": "approved",
    }
)
print_result("High-risk release with approval", high_risk_with_approval)
