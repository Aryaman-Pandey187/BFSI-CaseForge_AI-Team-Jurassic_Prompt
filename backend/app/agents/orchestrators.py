"""
Specialist orchestrators.

Each orchestrator fans out its sub-agents **in parallel** (``asyncio.gather``),
then runs the deterministic Risk Scoring Agent over the collected evidence,
optionally resolves simple requests (Account Queries), and finally hands
everything to the Case Assembler.

    Intent ─► Orchestrator ─┬─► Customer Profile ┐
                            ├─► Txn Enricher     │  (parallel, tool calling)
                            ├─► Prior Fraud      ├─► Risk Scoring ─► Case Assembler ─► desktop + Firestore
                            └─► Identity/Channel ┘
"""
from __future__ import annotations

import asyncio
import time

from app.agents import risk as risk_mod
from app.agents import subagents as sa
from app.agents.assembler import assemble_case
from app.agents.textnum import spoken_date, spoken_inr
from app.agents.tools import CaseContext, inr

ORCHESTRATORS = {
    "credit_card": {
        "title": "Credit Card Remediation Orchestrator",
        "agents": lambda: [sa.profile_agent(), sa.txn_agent("credit_card"), sa.fraud_agent(), sa.identity_channel_agent()],
        "scorer": lambda ctx: risk_mod.score_card_fraud(ctx, "credit_card"),
    },
    "debit_card": {
        "title": "Debit Card Remediation Orchestrator",
        "agents": lambda: [sa.profile_agent(), sa.txn_agent("debit_card"), sa.atm_agent(), sa.linked_agent(),
                           sa.fraud_agent(), sa.identity_channel_agent()],
        "scorer": lambda ctx: risk_mod.score_card_fraud(ctx, "debit_card"),
    },
    "loan": {
        "title": "Loan Agent Orchestrator",
        "agents": lambda: [sa.profile_agent(), sa.emi_agent(), sa.repay_agent(), sa.hardship_agent(), sa.identity_channel_agent(7)],
        "scorer": risk_mod.score_loan,
    },
    "account": {
        "title": "Account Queries Orchestrator",
        "agents": lambda: [sa.c360_agent(), sa.sr_agent(), sa.identity_channel_agent(7), sa.fraud_agent()],
        "scorer": risk_mod.score_account,
    },
}

SIMPLE_QUERIES = {"balance", "cheque_book", "fd_maturity", "service_request_status", "card_status"}


async def run_orchestrator(ctx: CaseContext, intent: dict, customer: dict) -> dict:
    route = intent["route"]
    cfg = ORCHESTRATORS[route]
    agents = cfg["agents"]()
    t0 = time.perf_counter()
    ctx.publish("orchestrator.started", {"route": route, "title": cfg["title"],
                                         "agents": [{"agent_id": a.id, "title": a.title, "icon": a.icon, "tools": a.tools}
                                                    for a in agents]})
    brief = (f"Customer {customer['full_name']} ({customer['customer_id']}), home city {customer['city']}. "
             f"Intent {intent['intent']}: {intent['summary']}. Entities: {intent['entities']}")

    # ---- 1. Parallel fan-out ---------------------------------------------
    results = await asyncio.gather(*[sa.run_subagent(ctx, a, brief, route) for a in agents], return_exceptions=True)
    findings = []
    for a, r in zip(agents, results):
        if isinstance(r, Exception):
            ctx.publish("agent.completed", {"agent_id": a.id, "title": a.title, "status": "error", "headline": str(r),
                                            "findings": [], "group": route})
        else:
            findings.append(r)

    # ---- 2. Risk scoring (deterministic, explainable) ----------------------
    ctx.publish("agent.started", {"agent_id": "risk_scoring", "title": "Risk Scoring Agent", "group": "risk", "icon": "gauge",
                                  "tools": ["velocity", "geo_velocity", "unusual_spend", "composite_score"], "parallel": False})
    rt0 = time.perf_counter()
    risk = await cfg["scorer"](ctx)
    ctx.publish("risk.scored", risk)
    ctx.publish("agent.completed", {"agent_id": "risk_scoring", "title": "Risk Scoring Agent", "status": "ok", "group": "risk",
                                    "headline": f"Score {risk['score']}/100 · {risk['band']} · {len(risk['reasons'])} reason codes",
                                    "findings": [{"text": f"{x['code']} (+{x['points']}): {x['detail']}", "evidence": x["evidence"]}
                                                 for x in risk["reasons"][:6]],
                                    "duration_ms": round((time.perf_counter() - rt0) * 1000), "engine": "deterministic"})

    # ---- 3. Route-specific panel + AI resolution --------------------------
    panel = build_route_panel(ctx, route, intent, customer)

    # ---- 4. Case assembly --------------------------------------------------
    case = await assemble_case(ctx, intent=intent, customer=customer, findings=findings, risk=risk, panel=panel,
                               orchestrator=cfg["title"])
    case["timings"] = {"orchestration_ms": round((time.perf_counter() - t0) * 1000)}
    return case


def _emi(p: float, annual_rate: float, months: int) -> float:
    r = annual_rate / 1200
    return p * r * (1 + r) ** months / ((1 + r) ** months - 1)


def build_route_panel(ctx: CaseContext, route: str, intent: dict, customer: dict) -> dict:
    if route == "loan":
        emi = ctx.latest("get_emi_schedule").data["loans"]
        rep = {r["loan_id"]: r for r in ctx.latest("get_repayment_history").data["loans"]}
        hs = ctx.latest("get_hardship_signals").data
        options = []
        for ln in emi:
            rem = max(ln["remaining_installments"], 1)
            ext = min(rem + 60, 360 - (ln["tenure_months"] - rem)) if ln["type"] == "HOME_LOAN" else rem + 12
            new = _emi(ln["outstanding"], ln["interest_rate"], ext)
            options.append({"loan_id": ln["loan_id"], "type": ln["type"], "current_emi": ln["emi_amount"],
                            "options": [
                                {"name": "Tenure extension", "new_emi": round(new), "detail": f"Extend by {ext - rem} months → EMI {inr(new)} ({round(100 * (1 - new / ln['emi_amount']))}% lower)"},
                                {"name": "3-month EMI holiday", "new_emi": 0, "detail": "Interest accrues; overdue regularised; requires hardship proof (relieving letter)"},
                                {"name": "Penal charge waiver", "new_emi": ln["emi_amount"], "detail": f"Waive bounce charges ({inr(sum(b['charge'] for b in rep[ln['loan_id']]['bounce_history']))})"},
                            ], "eligible": bool(ln.get("restructure_eligible"))})
        return {"type": "loan", "loans": emi, "repayment": list(rep.values()), "hardship": hs, "relief_options": options}
    if route == "account":
        c360 = ctx.latest("get_customer_360").data
        srs = ctx.latest("get_service_requests").data["service_requests"]
        qtypes = intent["entities"].get("query_types") or ["other"]
        answers = []
        sav = next((a for a in c360["accounts"] if a["type"] == "savings"), None)
        fd = next((a for a in c360["accounts"] if a["type"] == "fixed_deposit"), None)
        ev360, evsr = ctx.latest("get_customer_360").id, ctx.latest("get_service_requests").id
        for q in qtypes:
            if q == "balance" and sav:
                answers.append({"query": "balance", "evidence": [ev360],
                                "answer": f"Savings ••{sav['account_id'][-4:]} available balance {inr(sav['available_balance'])}",
                                "spoken": f"your savings account ending {' '.join(sav['account_id'][-4:])} has an available balance of {spoken_inr(sav['available_balance'])}"})
            elif q == "cheque_book":
                sr = next((s for s in srs if s["type"] == "CHEQUE_BOOK_REQUEST"), None)
                if sr:
                    answers.append({"query": "cheque_book", "evidence": [evsr], "answer": f"{sr['sr_id']}: {sr['detail']}",
                                    "spoken": f"your cheque book was dispatched on {spoken_date(sr['created'])} by BlueDart, and it should reach you by {spoken_date(sr['eta']) if sr.get('eta') else 'in two working days'}"})
                else:
                    answers.append({"query": "cheque_book", "evidence": [evsr], "answer": "No cheque book request on file",
                                    "spoken": "I don't see a cheque book request on your account yet"})
            elif q == "fd_maturity" and fd:
                answers.append({"query": "fd_maturity", "evidence": [ev360],
                                "answer": f"FD {fd['account_id']} matures {fd['maturity_date']} for {inr(fd['maturity_amount'])}",
                                "spoken": f"your fixed deposit matures on {spoken_date(fd['maturity_date'])} with a maturity amount of {spoken_inr(fd['maturity_amount'])}"})
        simple = set(qtypes) <= SIMPLE_QUERIES and len(answers) == len(qtypes)
        return {"type": "account", "query_types": qtypes, "answers": answers, "accounts": c360["accounts"],
                "cards": c360["cards"], "service_requests": srs, "last_login": c360.get("last_login"),
                "resolution": "RESOLVED_BY_AI" if simple else "HANDOFF_REQUIRED"}
    if route == "debit_card":
        atm = ctx.latest("get_atm_velocity").data
        la = ctx.latest("get_linked_account_activity").data
        return {"type": "debit_card", "atm": atm, "linked_account": la}
    # credit card
    prof = ctx.latest("get_customer_profile").data
    card = next((c for c in prof["cards"] if c["type"] == "credit"), {})
    return {"type": "credit_card", "card": card}
