"""
Case Assembler.

Aggregates every sub-agent finding, the risk result and the route panel into a
single structured case document with **citations** (evidence ids → tool +
data source). The skeleton is built deterministically; Gemini (when enabled)
writes the narrative fields - headline, narrative, key findings, suggested
questions, recommended actions and the caller-facing handoff message - using
JSON structured output. Anything missing or invalid falls back to templates.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone

from app.agents.textnum import spoken_inr
from app.agents.tools import CaseContext, inr
from app.core.llm import llm

log = logging.getLogger("caseforge.assembler")

ASSEMBLER_SYSTEM = """You are the Case Assembler for a bank contact centre. You receive structured outputs from
specialist agents (each with evidence ids like E3) and a deterministic risk score. Produce a concise case file for
the human agent who will take over the call. Every key finding MUST cite at least one valid evidence id.
caller_message is spoken aloud by a voice bot to the customer right before handoff: warm, max 55 words, no
markdown, say amounts like "1 lakh 84 thousand rupees", never reveal internal risk scores or fraud-rule names, and
say a specialist with full context is joining. If resolution is RESOLVED_BY_AI, caller_message must directly answer
the customer's question(s) using the provided answers and then ask if there is anything else."""

ASSEMBLER_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "narrative": {"type": "string"},
        "key_findings": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"}, "citations": {"type": "array", "items": {"type": "string"}},
            "severity": {"type": "string", "enum": ["info", "warning", "critical"]}}, "required": ["text", "citations"]}},
        "suggested_questions": {"type": "array", "items": {"type": "string"}},
        "recommended_actions": {"type": "array", "items": {"type": "object", "properties": {
            "action": {"type": "string"}, "label": {"type": "string"}, "rationale": {"type": "string"}},
            "required": ["action", "label"]}},
        "caller_message": {"type": "string"},
    },
    "required": ["headline", "narrative", "key_findings", "suggested_questions", "recommended_actions", "caller_message"],
}

ROUTE_LABEL = {"credit_card": "Credit Card", "debit_card": "Debit Card", "loan": "Loans", "account": "Account Services"}
QUEUE = {"credit_card": "Card Fraud Desk", "debit_card": "Card Fraud Desk", "loan": "Collections & Hardship",
         "account": "Retail Service"}


async def assemble_case(ctx: CaseContext, *, intent: dict, customer: dict, findings: list[dict], risk: dict,
                        panel: dict, orchestrator: str) -> dict:
    t0 = time.perf_counter()
    ctx.publish("agent.started", {"agent_id": "case_assembler", "title": "Case Assembler", "group": "assembler",
                                  "icon": "file", "tools": ["aggregate", "cite", "summarise"], "parallel": False})
    route = intent["route"]
    base = _template(route, intent, customer, findings, risk, panel)
    engine = "rules"
    if llm.enabled:
        try:
            payload = {"intent": intent, "customer": {k: customer.get(k) for k in ("full_name", "first_name", "segment", "city", "vulnerable_customer")},
                       "risk": {k: risk[k] for k in ("score", "band", "risk_type", "reasons")},
                       "flagged_transactions": risk["flagged_transactions"][:8],
                       "agent_findings": findings, "route_panel": _trim_panel(panel),
                       "resolution": panel.get("resolution", "HANDOFF_REQUIRED"),
                       "evidence": [e.public() for e in ctx.evidence]}
            out = await llm.json(system=ASSEMBLER_SYSTEM, prompt=json.dumps(payload, default=str)[:60000],
                                 schema=ASSEMBLER_SCHEMA)
            valid = {e.id for e in ctx.evidence}
            if out.get("headline") and out.get("caller_message"):
                kf = [{"text": f["text"], "citations": [c for c in f.get("citations", []) if c in valid],
                       "severity": f.get("severity", "info")} for f in out.get("key_findings", []) if f.get("text")]
                base.update({k: out[k] for k in ("headline", "narrative", "caller_message") if out.get(k)})
                if kf:
                    base["key_findings"] = kf
                if out.get("suggested_questions"):
                    base["suggested_questions"] = out["suggested_questions"][:6]
                if out.get("recommended_actions"):
                    base["recommended_actions"] = out["recommended_actions"][:5]
                engine = "gemini"
        except Exception as exc:  # LLMUnavailable, timeouts, bad responses -> deterministic path
            log.warning("Assembler LLM unavailable, using templates: %s", exc)

    case = {
        "case_id": f"CF-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:6].upper()}",
        "call_id": ctx.call_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "RESOLVED_BY_AI" if panel.get("resolution") == "RESOLVED_BY_AI" else "PENDING_AGENT",
        "queue": QUEUE[route], "priority": {"CRITICAL": "P1", "HIGH": "P2", "MEDIUM": "P3", "LOW": "P4"}[risk["band"]],
        "route": route, "route_label": ROUTE_LABEL[route], "orchestrator": orchestrator,
        "intent": intent,
        "customer": {k: customer.get(k) for k in ("customer_id", "full_name", "first_name", "segment", "city", "risk_rating",
                                                   "relationship_since", "vulnerable_customer")},
        "risk": risk,
        "summary": {k: base[k] for k in ("headline", "narrative", "key_findings")},
        "suggested_questions": base["suggested_questions"],
        "recommended_actions": base["recommended_actions"],
        "caller_message": base["caller_message"],
        "agent_findings": findings,
        "route_panel": panel,
        "timeline": _timeline(ctx, risk),
        "citations": [e.public() for e in ctx.evidence],
        "assembler_engine": engine,
    }
    ctx.publish("agent.completed", {"agent_id": "case_assembler", "title": "Case Assembler", "status": "ok", "group": "assembler",
                                    "headline": f"{case['priority']} case {case['case_id']} → {case['queue']}", "engine": engine,
                                    "findings": [{"text": f["text"], "evidence": f["citations"]} for f in case["summary"]["key_findings"][:4]],
                                    "duration_ms": round((time.perf_counter() - t0) * 1000)})
    return case


def _trim_panel(p: dict) -> dict:
    p = dict(p)
    if p.get("type") == "loan":
        p["loans"] = [{k: v for k, v in ln.items() if k not in {"last_12"}} for ln in p["loans"]]
    return p


def _timeline(ctx: CaseContext, risk: dict) -> list[dict]:
    items = []
    if (ev := ctx.latest("get_prior_fraud_flags")):
        for f in ev.data["flags"]:
            items.append({"ts": f["date"], "kind": "fraud_flag", "title": f["type"].replace("_", " ").title(),
                          "detail": f["description"], "severity": f["severity"], "status": f["status"],
                          "sar": f.get("sar_filed"), "evidence": ev.id})
    if (ev := ctx.latest("check_recent_auth_events")):
        for e in ev.data["risky_events"]:
            items.append({"ts": e["timestamp"], "kind": "auth_event", "title": e["type"].replace("_", " ").title(),
                          "detail": f"{e['detail']} ({e['ip_city']})", "severity": e["risk"], "evidence": ev.id})
    for t in risk["flagged_transactions"][:6]:
        items.append({"ts": t["timestamp"], "kind": "transaction", "title": f"{inr(t['amount'])} · {t['merchant']}",
                      "detail": f"{t.get('city', '')} · {', '.join(t.get('flags', []))}", "severity": "HIGH",
                      "status": t.get("status")})
    return sorted(items, key=lambda i: i["ts"], reverse=True)


# ---------------------------------------------------------------------------
# Deterministic templates (used offline and as a fallback)
# ---------------------------------------------------------------------------

def _template(route, intent, customer, findings, risk, panel) -> dict:
    first = customer["first_name"]
    codes = {r["code"] for r in risk["reasons"]}
    kf = [{"text": f"{r['label']}: {r['detail']}", "citations": r["evidence"],
           "severity": "critical" if r["points"] >= 15 else "warning"} for r in risk["reasons"][:5]]
    flagged = risk["flagged_transactions"]
    q, actions = [], []
    if route == "credit_card":
        top = max((t for t in flagged if t["direction"] == "DEBIT"), key=lambda t: t["amount"], default=None)
        if intent["intent"] == "CREDIT_CARD_DISPUTE":
            headline = f"Merchant dispute on credit card - {inr(intent['entities'].get('amount', 0)) if intent['entities'].get('amount') else 'amount TBC'}"
        elif top:
            headline = f"Probable card compromise: {inr(top['amount'])} at {top['merchant']}, {top.get('city')}"
        else:
            headline = "Credit card transaction query - no anomalies detected"
        narrative = (f"{intent['summary'].replace('Customer', customer['full_name'], 1)}. Risk engine scores the case {risk['score']}/100 "
                     f"({risk['band']}) driven by {', '.join(r['label'].lower() for r in risk['reasons'][:3]) or 'no material signals'}.")
        if "SIM_SWAP_RECENT" in codes:
            narrative += " A SIM swap and credential reset preceded the spend - pattern consistent with account takeover."
        q = ["Are you currently in India, and is the physical card with you right now?",
             "Have you shared your card details, CVV or any OTP with anyone in the last 3 days?"]
        if "SIM_SWAP_RECENT" in codes:
            q.append("Did your mobile lose network signal unexpectedly in the last few days?")
        if "CREDENTIAL_RESET" in codes:
            q.append("Did you reset your net-banking password yourself this week?")
        q.append("Besides the flagged transactions, do you recognise all other recent charges?")
        actions = [{"action": "BLOCK_CARD", "label": "Block card & reissue", "rationale": "Stop further fraudulent use"},
                   {"action": "RAISE_DISPUTE", "label": "Raise fraud dispute (chargeback)", "rationale": "Card-present fraud with magstripe fallback - liability shift likely"},
                   {"action": "RESET_CREDENTIALS", "label": "Lock digital banking & reset", "rationale": "New device + password reset after SIM swap"}]
        if top:
            caller = (f"Thanks {first}. I can see the {spoken_inr(top['amount'])} transaction at {top['merchant']} "
                      f"along with some other unusual activity. To protect you, I'm connecting you to a fraud specialist now. "
                      f"They already have all the details, so you won't need to repeat yourself. Please stay on the line.")
        else:
            caller = f"Thanks {first}. I've pulled up your card activity, and I'm connecting you to a card specialist who has all the details. Please stay on the line."
    elif route == "debit_card":
        atm, la = panel["atm"], panel["linked_account"]
        total = atm["total_withdrawn"] + sum(t["amount"] for t in la["transfers"])
        headline = f"Debit card misuse: {atm['approved_count']} ATM cash-outs + transfers, {inr(total)} at risk"
        narrative = (f"{customer['full_name']} reports a missing debit card. {atm['approved_count']} ATM withdrawals across {atm['distinct_atms']} ATMs "
                     f"(peak {atm['max_in_1h']}/hour) were followed by an MPIN reset on a new device and transfers to a newly added payee. "
                     f"Linked account drained {la['outflow_pct_of_balance']}%. Risk {risk['score']}/100 ({risk['band']}).")
        q = ["When did you last use or see your debit card?", "Was your PIN written down or stored with the card?",
             "Did you add a payee called 'R K Traders' or reset your MPIN last night?",
             "Have you received any calls or messages asking for card details recently?"]
        actions = [{"action": "BLOCK_CARD", "label": "Hot-list debit card", "rationale": "Card reported missing"},
                   {"action": "FREEZE_ACCOUNT", "label": "Debit-freeze linked account", "rationale": "Ongoing outflow to new payee"},
                   {"action": "RECALL_FUNDS", "label": "IMPS/UPI recall + NCRP report", "rationale": "Beneficiary bank may still hold funds (golden hour)"},
                   {"action": "RAISE_DISPUTE", "label": "Raise ATM/POS dispute", "rationale": "Zero-liability claim within 3 days"}]
        caller = (f"Thanks {first}. I can see several ATM withdrawals and transfers from your account overnight. I'm connecting you "
                  f"to a fraud specialist right now who can block your card and act on those transfers. They have everything in front of them, so please stay on the line.")
    elif route == "loan":
        loans = panel["loans"]
        od = sum(r["overdue_amount"] for r in panel["repayment"])
        headline = f"Financial hardship: {sum(r['bounced'] for r in panel['repayment'])} EMI bounces, {inr(od)} overdue, salary stopped"
        narrative = (f"{customer['full_name']} ({customer['segment']}, customer since {customer['relationship_since'][:4]}) reports hardship"
                     f"{' - ' + intent['entities']['hardship_reason'] if intent['entities'].get('hardship_reason') else ''}. "
                     f"{len(loans)} loans with combined EMI {inr(sum(l['emi_amount'] for l in loans))}/month; accounts are in SMA-1. "
                     f"Hardship signals corroborate the claim. Delinquency risk {risk['score']}/100 ({risk['band']}); customer is restructure-eligible.")
        q = ["When did your employment end, and do you have a relieving letter or termination notice?",
             "Do you have any current or expected income in the next 3 months?",
             "Which would help more right now: a lower EMI over a longer tenure, or a short EMI holiday?",
             "Are there other loans or obligations outside our bank?"]
        actions = [{"action": "OFFER_RESOLUTION", "label": "Offer restructuring (tenure extension)", "rationale": "Eligible; reduces EMI and avoids NPA"},
                   {"action": "WAIVE_CHARGES", "label": "Waive bounce charges", "rationale": "First delinquency in 10 years"},
                   {"action": "PAUSE_COLLECTIONS", "label": "Pause collection calls 15 days", "rationale": "Hardship under review"}]
        caller = (f"Thank you for telling me, {first}, and I'm sorry you're going through this. I can see your loan details and there are "
                  f"relief options we can look at, like a lower EMI. I'm connecting you to a specialist who has everything ready. Please stay on the line.")
    else:
        answers = panel["answers"]
        resolved = panel["resolution"] == "RESOLVED_BY_AI"
        headline = ("Account query resolved by AI: " if resolved else "Account query - needs agent: ") + \
            ", ".join(a.replace("_", " ") for a in panel["query_types"])
        narrative = f"{customer['full_name']} asked about {', '.join(a.replace('_', ' ') for a in panel['query_types'])}. " + \
            " ".join(a["answer"] + "." for a in answers) + f" Authentication risk {risk['score']}/100 ({risk['band']})."
        kf = [{"text": a["answer"], "citations": a["evidence"], "severity": "info"} for a in answers] + kf
        q = ["Is there anything else I can help you with on your account?",
             "Would you like to enable SMS alerts for cheque book delivery?"]
        actions = [{"action": "SEND_SMS", "label": "Send balance & tracking SMS", "rationale": "Confirm answers in writing"},
                   {"action": "OFFER_RESOLUTION", "label": "Mark resolved", "rationale": "Answered by AI"}]
        if resolved:
            spoken = ". And ".join(a["spoken"] for a in answers)
            caller = f"Sure, {first}. " + spoken[:1].upper() + spoken[1:] + ". Is there anything else I can help you with?"
        else:
            caller = f"Thanks {first}. I'm connecting you to a colleague who can help with that; they can see your details already."
        if not kf:
            kf = [{"text": "No authentication risk signals.", "citations": [], "severity": "info"}]
    if risk["band"] in {"HIGH", "CRITICAL"} and route != "loan":
        actions.append({"action": "ESCALATE", "label": "Escalate to Fraud Ops", "rationale": f"{risk['band']} risk"})
    if customer.get("vulnerable_customer"):
        q.insert(0, "Customer is flagged vulnerable - speak slowly and confirm understanding.")
    return {"headline": headline, "narrative": narrative, "key_findings": kf, "suggested_questions": q,
            "recommended_actions": actions, "caller_message": caller}
