"""End-to-end flow tests in mock mode (no GCP / Twilio needed)."""
import asyncio

import pytest

from app.core.events import hub
from app.core.simulator import SCENARIOS, run_scenario

EXPECT = {
    "credit_card_fraud": {"route": "credit_card", "band": {"CRITICAL"}, "status": "PENDING_AGENT", "codes": {"GEO_VELOCITY", "SIM_SWAP_RECENT", "UNUSUAL_AMOUNT"}},
    "debit_card_fraud": {"route": "debit_card", "band": {"CRITICAL", "HIGH"}, "status": "PENDING_AGENT", "codes": {"ATM_VELOCITY", "CASH_OUT_PATTERN"}},
    "loan_hardship": {"route": "loan", "band": {"CRITICAL", "HIGH"}, "status": "PENDING_AGENT", "codes": {"EMI_BOUNCES", "SALARY_STOPPED"}},
    "account_query": {"route": "account", "band": {"LOW"}, "status": "RESOLVED_BY_AI", "codes": set()},
}


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_scenario(scenario):
    session = asyncio.run(run_scenario(scenario))
    events = hub.events_for(session.call_id)
    types = [e["type"] for e in events]
    for t in ["call.started", "identity.update", "customer.snapshot", "intent.classified", "orchestrator.started",
              "agent.started", "agent.tool_call", "agent.completed", "risk.scored", "case.assembled", "call.ended",
              "case.logged"]:
        assert t in types, f"{scenario}: missing {t}"
    case = next(e for e in events if e["type"] == "case.assembled")["data"]
    exp = EXPECT[scenario]
    assert case["route"] == exp["route"]
    assert case["risk"]["band"] in exp["band"], case["risk"]
    assert case["status"] == exp["status"]
    codes = {r["code"] for r in case["risk"]["reasons"]}
    assert exp["codes"] <= codes, codes
    # every key finding cites evidence that exists
    ids = {c["id"] for c in case["citations"]}
    for f in case["summary"]["key_findings"]:
        assert set(f["citations"]) <= ids
    # parallel agents all started before the first one completed (fan-out)
    started = [i for i, e in enumerate(events) if e["type"] == "agent.started" and e["data"].get("parallel")]
    completed = [i for i, e in enumerate(events) if e["type"] == "agent.completed"]
    assert len(started) >= 4 and max(started) < min(completed)
