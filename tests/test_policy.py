from release_triage_agent.policy import assess_risk, classify_change, route_for


def test_classifies_service_and_change_type():
    change_type, service = classify_change("Deploy billing database migration to prod")

    assert change_type == "data_change"
    assert service == "billing"


def test_high_risk_requires_human_approval():
    risk = assess_risk(
        {
            "request": "Deploy billing database migration to prod",
            "service_context": {
                "owner": "payments-platform",
                "tier": "tier-1",
                "deploy_window": "Tue-Thu",
                "rollback": "Rollback playbook",
            },
        }
    )

    assert risk == "high"
    assert route_for({"request": "x", "risk_level": risk}) == "needs_human_approval"


def test_low_risk_can_auto_plan():
    risk = assess_risk(
        {
            "request": "Deploy notifications copy update",
            "service_context": {
                "owner": "growth-platform",
                "tier": "tier-2",
                "deploy_window": "Any weekday",
                "rollback": "Rollback worker",
            },
        }
    )

    assert risk == "low"
    assert route_for({"request": "x", "risk_level": risk}) == "auto_plan"
