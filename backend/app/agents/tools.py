"""
Agent tools.

Each tool is (1) a JSON-schema *declaration* that is handed to Gemini for
function calling and (2) an async Python implementation that queries the data
store. Every execution is recorded as an **evidence** item (``E1``, ``E2``...)
so the Case Assembler can cite exactly which tool output supports each
statement in the case summary.

Security: tools are bound to a :class:`CaseContext`. After identity
verification the ``customer_id`` argument is *forced* to the verified
customer, so a prompt-injected caller can never make the model read another
customer's data.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from app.config import get_settings
from app.core.datastore import get_store, parse_ts

# ---------------------------------------------------------------------------
# Context + evidence registry
# ---------------------------------------------------------------------------


@dataclass
class Evidence:
    id: str
    tool: str
    agent: str
    args: dict
    source: str
    summary: str
    data: Any
    ts: float = field(default_factory=time.time)

    def public(self) -> dict:
        return {"id": self.id, "tool": self.tool, "agent": self.agent, "args": self.args,
                "source": self.source, "summary": self.summary}


@dataclass
class CaseContext:
    call_id: str
    caller_number: str | None
    publish: Callable[[str, dict], Any]
    customer_id: str | None = None
    evidence: list[Evidence] = field(default_factory=list)

    def add_evidence(self, tool: str, agent: str, args: dict, source: str, summary: str, data: Any) -> Evidence:
        ev = Evidence(id=f"E{len(self.evidence) + 1}", tool=tool, agent=agent, args=args, source=source,
                      summary=summary, data=data)
        self.evidence.append(ev)
        return ev

    def latest(self, tool: str) -> Evidence | None:
        for ev in reversed(self.evidence):
            if ev.tool == tool:
                return ev
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def inr(v: float) -> str:
    """Indian-style currency formatting: 184500 -> ₹1,84,500."""
    neg, v = v < 0, abs(round(v))
    s = str(int(v))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return ("-" if neg else "") + "₹" + s


def _slim_txn(t: dict) -> dict:
    keys = ["txn_id", "timestamp", "amount", "direction", "merchant", "mcc", "mcc_description", "channel",
            "city", "country", "device_id", "status", "entry_mode", "instrument", "card_id"]
    out = {k: t.get(k) for k in keys}
    for k in ("original_amount", "original_currency", "decline_reason", "beneficiary_added_minutes_before"):
        if k in t:
            out[k] = t[k]
    return out


def _mask_mobile(m: str) -> str:
    return m[:3] + "•" * (len(m) - 7) + m[-4:]


# ---------------------------------------------------------------------------
# Tool implementations. Signature: (ctx, **args) -> (result_for_llm, summary, source)
# ---------------------------------------------------------------------------

async def lookup_customer(ctx: CaseContext, name: str | None = None, mobile_last4: str | None = None,
                          customer_id: str | None = None):
    store = await get_store()
    res = await store.find_customer(name=name, mobile_last4=mobile_last4, customer_id=customer_id)
    cust = res.get("customer")
    out = {"verified": bool(res["match"]), "confidence": res["confidence"], "reason": res["reason"]}
    if cust:
        ctx.customer_id = cust["customer_id"]
        out.update({"customer_id": cust["customer_id"], "first_name": cust["first_name"],
                    "full_name": cust["full_name"], "segment": cust["segment"],
                    "vulnerable_customer": cust.get("vulnerable_customer", False)})
    summary = (f"Verified {cust['full_name']} ({cust['customer_id']}) - {res['reason']}" if cust
               else f"No match: {res['reason']}")
    return out, summary, "firestore://customers"


async def get_customer_profile(ctx: CaseContext, customer_id: str | None = None):
    store = await get_store()
    cid = ctx.customer_id
    c = await store.get_customer(cid)
    cards = await store.cards(cid)
    accts = await store.accounts(cid)
    loans = await store.loans(cid)
    profile = {
        "customer_id": c["customer_id"], "full_name": c["full_name"], "dob": c["dob"],
        "registered_mobile": _mask_mobile(c["registered_mobile"]), "email": c["email"], "city": c["city"],
        "state": c["state"], "segment": c["segment"], "relationship_since": c["relationship_since"],
        "kyc_status": c["kyc_status"], "risk_rating": c["risk_rating"], "vulnerable_customer": c["vulnerable_customer"],
        "nps_last": c["nps_last"], "notes": c["notes"], "products": c["products"],
        "cards": [{k: v for k, v in x.items() if k in {"card_id", "type", "network", "variant", "last4", "status",
                                                        "credit_limit", "available_limit", "outstanding",
                                                        "linked_account_id", "international_enabled"}} for x in cards],
        "accounts": [{k: v for k, v in a.items() if k in {"account_id", "type", "balance", "status",
                                                           "maturity_date", "interest_rate"}} for a in accts],
        "loans": [{k: v for k, v in ln.items() if k in {"loan_id", "type", "outstanding", "emi_amount", "dpd",
                                                         "bucket"}} for ln in loans],
    }
    years = datetime.now().year - int(c["relationship_since"][:4])
    return profile, f"{c['full_name']}: {c['segment']} customer, {years} yrs, KYC {c['kyc_status']}, risk rating {c['risk_rating']}", \
        f"firestore://customers/{cid}"


async def get_recent_transactions(ctx: CaseContext, customer_id: str | None = None, days: int = 90,
                                  instrument: str | None = None):
    store = await get_store()
    txns = await store.transactions(ctx.customer_id, days=int(days or 90), instrument=instrument)
    cust = await store.get_customer(ctx.customer_id)
    debits = [t for t in txns if t["direction"] == "DEBIT"]
    foreign = [t for t in txns if t["country"] != "IN"]
    stats = {
        "count": len(txns), "window_days": days, "instrument": instrument or "all",
        "total_debit": round(sum(t["amount"] for t in debits), 2),
        "avg_debit": round(sum(t["amount"] for t in debits) / max(len(debits), 1), 2),
        "max_debit": max((t["amount"] for t in debits), default=0),
        "home_city": cust["city"], "foreign_txn_count": len(foreign),
        "countries": sorted({t["country"] for t in txns}),
        "channels": sorted({t["channel"] for t in txns}),
        "devices": sorted({t["device_id"] for t in txns if t["channel"] in {"ECOM", "IMPS", "UPI"}}),
    }
    recent = [_slim_txn(t) for t in txns[:25]]
    result = {"stats": stats, "recent_transactions": recent}
    summary = (f"{len(txns)} {instrument or ''} txns in {days}d, avg {inr(stats['avg_debit'])}, "
               f"max {inr(stats['max_debit'])}, {len(foreign)} foreign").replace("  ", " ")
    ctx._raw_txns = txns  # type: ignore[attr-defined]  # full list for risk scoring
    return result, summary, f"firestore://transactions?customer_id={ctx.customer_id}&days={days}"


async def get_prior_fraud_flags(ctx: CaseContext, customer_id: str | None = None):
    store = await get_store()
    flags = await store.fraud_flags(ctx.customer_id)
    sar = [f for f in flags if f.get("sar_filed")]
    open_ = [f for f in flags if f["status"] == "OPEN"]
    summary = (f"{len(flags)} prior flags ({len(open_)} open, {len(sar)} SAR)" if flags else "No prior fraud flags or SARs")
    return {"flags": flags, "sar_count": len(sar), "open_count": len(open_)}, summary, \
        f"firestore://fraud_flags?customer_id={ctx.customer_id}"


async def check_ani_match(ctx: CaseContext, customer_id: str | None = None, caller_number: str | None = None):
    """Compare the caller's ANI (phone number Twilio reports) to the registered mobile."""
    store = await get_store()
    s = get_settings()
    c = await store.get_customer(ctx.customer_id)
    ani = (ctx.caller_number or "").replace(" ", "")
    exact = bool(ani) and ani[-10:] == c["registered_mobile"][-10:]
    trusted = ani in s.demo_trusted_caller_numbers
    evts = await store.auth_events(ctx.customer_id, days=7)
    sim_swap = next((e for e in evts if e["type"] == "SIM_SWAP"), None)
    match = exact or trusted
    if match and sim_swap:
        verdict = "MATCH_BUT_SIM_SWAPPED"
    elif match:
        verdict = "MATCH"
    elif not ani:
        verdict = "UNKNOWN"
    else:
        verdict = "MISMATCH"
    out = {"caller_ani": ani[:3] + "•••••" + ani[-4:] if ani else None, "registered_mobile": _mask_mobile(c["registered_mobile"]),
           "verdict": verdict, "demo_trusted_number": trusted and not exact,
           "sim_swap_at": sim_swap["timestamp"] if sim_swap else None}
    return out, f"ANI check: {verdict.replace('_', ' ').lower()}", "telephony://ani + firestore://customers"


async def check_recent_auth_events(ctx: CaseContext, customer_id: str | None = None, days: int = 14):
    store = await get_store()
    evts = await store.auth_events(ctx.customer_id, days=int(days or 14))
    risky = [e for e in evts if e["risk"] in {"HIGH", "MEDIUM"}]
    types = sorted({e["type"] for e in risky})
    summary = f"{len(risky)} risky auth events in {days}d: {', '.join(types)}" if risky else f"No risky auth events in {days}d"
    return {"events": evts[:20], "risky_events": risky, "risky_types": types}, summary, \
        f"firestore://auth_events?customer_id={ctx.customer_id}&days={days}"


async def get_atm_velocity(ctx: CaseContext, customer_id: str | None = None, hours: int = 24):
    store = await get_store()
    txns = await store.transactions(ctx.customer_id, days=max(1, math.ceil(int(hours or 24) / 24) + 1))
    since = datetime.now(timezone.utc) - timedelta(hours=int(hours or 24))
    atm = sorted([t for t in txns if t["channel"] == "ATM" and parse_ts(t["timestamp"]) >= since],
                 key=lambda t: t["timestamp"])
    ok = [t for t in atm if t["status"] == "APPROVED"]
    max_1h = 0
    for i, t in enumerate(atm):
        t0 = parse_ts(t["timestamp"])
        max_1h = max(max_1h, sum(1 for u in atm[i:] if parse_ts(u["timestamp"]) - t0 <= timedelta(hours=1)))
    hist = [t for t in await store.transactions(ctx.customer_id, days=90) if t["channel"] == "ATM"]
    out = {"window_hours": hours, "withdrawals": [_slim_txn(t) for t in atm], "approved_count": len(ok),
           "declined_count": len(atm) - len(ok), "total_withdrawn": sum(t["amount"] for t in ok),
           "distinct_atms": len({t["device_id"] for t in atm}), "max_in_1h": max_1h,
           "baseline_atm_per_month": round(max(len(hist) - len(atm), 0) / 3, 1),
           "odd_hour": any(parse_ts(t["timestamp"]).astimezone(timezone(timedelta(hours=5, minutes=30))).hour < 5 for t in atm)}
    return out, (f"{len(atm)} ATM attempts in {hours}h ({inr(out['total_withdrawn'])} withdrawn, "
                 f"{out['distinct_atms']} ATMs, max {max_1h}/hr)"), \
        f"firestore://transactions?channel=ATM&customer_id={ctx.customer_id}"


async def get_linked_account_activity(ctx: CaseContext, customer_id: str | None = None, hours: int = 48):
    store = await get_store()
    accts = [a for a in await store.accounts(ctx.customer_id) if a["type"] in {"savings", "current"}]
    txns = await store.transactions(ctx.customer_id, days=3)
    since = datetime.now(timezone.utc) - timedelta(hours=int(hours or 48))
    out_txns = [t for t in txns if t["direction"] == "DEBIT" and parse_ts(t["timestamp"]) >= since]
    transfers = [t for t in out_txns if t["channel"] in {"IMPS", "UPI", "NEFT"}]
    a = accts[0] if accts else {}
    prior = a.get("balance_7d_ago") or (a.get("balance", 0) + sum(t["amount"] for t in out_txns if t["status"] == "APPROVED"))
    drained = sum(t["amount"] for t in out_txns if t["status"] == "APPROVED")
    out = {"account_id": a.get("account_id"), "current_balance": a.get("balance"), "balance_before": prior,
           "outflow_window": drained, "outflow_pct_of_balance": round(100 * drained / prior, 1) if prior else 0,
           "transfers": [_slim_txn(t) for t in transfers],
           "new_beneficiary_transfers": [t["txn_id"] for t in transfers if "new beneficiary" in t["merchant"].lower()
                                         or t.get("beneficiary_added_minutes_before") is not None]}
    return out, f"Linked a/c {a.get('account_id')}: {inr(drained)} out in {hours}h ({out['outflow_pct_of_balance']}% of balance)", \
        f"firestore://accounts/{a.get('account_id')}"


async def get_emi_schedule(ctx: CaseContext, customer_id: str | None = None, loan_id: str | None = None):
    store = await get_store()
    loans = await store.loans(ctx.customer_id)
    out = []
    for ln in loans:
        if loan_id and ln["loan_id"] != loan_id:
            continue
        sched = ln["emi_schedule"]
        past = [r for r in sched if r["status"] != "UPCOMING"]
        upcoming = [r for r in sched if r["status"] == "UPCOMING"]
        out.append({"loan_id": ln["loan_id"], "type": ln["type"], "emi_amount": ln["emi_amount"],
                    "outstanding": ln["outstanding"], "interest_rate": ln["interest_rate"],
                    "tenure_months": ln["tenure_months"], "bucket": ln["bucket"], "dpd": ln["dpd"],
                    "installments_paid": sum(1 for r in past if r["status"] in {"PAID", "PAID_LATE"}),
                    "remaining_installments": len(upcoming), "last_12": past[-12:], "next_3": upcoming[:3],
                    "restructure_eligible": ln.get("restructure_eligible"),
                    "prepayment_charges": ln.get("prepayment_charges")})
    total = sum(x["emi_amount"] for x in out)
    return {"loans": out}, f"{len(out)} active loans, total EMI {inr(total)}/month", \
        f"firestore://loans?customer_id={ctx.customer_id}"


async def get_repayment_history(ctx: CaseContext, customer_id: str | None = None):
    store = await get_store()
    loans = await store.loans(ctx.customer_id)
    rows = []
    for ln in loans:
        past = [r for r in ln["emi_schedule"] if r["status"] != "UPCOMING"]
        rows.append({"loan_id": ln["loan_id"], "type": ln["type"],
                     "on_time": sum(1 for r in past if r["status"] == "PAID"),
                     "late": sum(1 for r in past if r["status"] == "PAID_LATE"),
                     "bounced": sum(1 for r in past if r["status"] == "BOUNCED"),
                     "overdue": sum(1 for r in past if r["status"] == "OVERDUE"),
                     "max_dpd": max((r.get("dpd", 0) for r in past), default=0),
                     "bounce_history": ln["bounce_history"],
                     "overdue_amount": sum(r["amount"] for r in past if r["status"] in {"BOUNCED", "OVERDUE"})})
    b = sum(r["bounced"] for r in rows)
    od = sum(r["overdue_amount"] for r in rows)
    return {"loans": rows, "total_bounces": b, "total_overdue": od}, \
        f"{b} EMI bounces, {inr(od)} overdue across {len(rows)} loans", f"firestore://loans?customer_id={ctx.customer_id}#history"


async def get_hardship_signals(ctx: CaseContext, customer_id: str | None = None):
    store = await get_store()
    txns = await store.transactions(ctx.customer_id, days=120)
    accts = await store.accounts(ctx.customer_id)
    cards = await store.cards(ctx.customer_id)
    evts = await store.auth_events(ctx.customer_id, days=10)
    salaries = sorted([t for t in txns if "SALARY" in t["merchant"] or "SETTLEMENT" in t["merchant"]],
                      key=lambda t: t["timestamp"])
    last_sal = salaries[-1] if salaries else None
    days_since = (datetime.now(timezone.utc) - parse_ts(last_sal["timestamp"])).days if last_sal else None
    sav = next((a for a in accts if a["type"] == "savings"), {})
    prev = sav.get("balance_90d_ago")
    cc = next((c for c in cards if c["type"] == "credit"), None)
    signals = []
    if last_sal and "SETTLEMENT" in last_sal["merchant"]:
        signals.append({"code": "FULL_AND_FINAL_SETTLEMENT", "detail": f"F&F settlement credited {last_sal['timestamp'][:10]} - employment ended"})
    if days_since and days_since > 35:
        signals.append({"code": "SALARY_STOPPED", "detail": f"No salary credit for {days_since} days"})
    if prev and sav.get("balance", 0) < 0.2 * prev:
        signals.append({"code": "BALANCE_DEPLETION", "detail": f"Savings fell from {inr(prev)} to {inr(sav['balance'])}"})
    if cc and cc.get("credit_limit") and cc.get("outstanding", 0) / cc["credit_limit"] > 0.85:
        signals.append({"code": "HIGH_CARD_UTILISATION", "detail": f"Credit card {round(100 * cc['outstanding'] / cc['credit_limit'])}% utilised, {cc.get('payment_behaviour', '').replace('_', ' ').lower()}"})
    if any("EMI holiday" in e.get("detail", "") for e in evts):
        signals.append({"code": "DIGITAL_DISTRESS_INTENT", "detail": "Viewed 'EMI holiday' FAQ repeatedly this week"})
    out = {"signals": signals, "last_salary_credit": last_sal["timestamp"] if last_sal else None,
           "employer": (last_sal["merchant"].replace("SALARY ", "").replace("FULL & FINAL SETTLEMENT ", "") if last_sal else None),
           "savings_balance": sav.get("balance"), "balance_90d_ago": prev,
           "card_utilisation_trend": cc.get("utilisation_trend") if cc else None}
    return out, f"{len(signals)} hardship signals: {', '.join(s['code'] for s in signals) or 'none'}", \
        f"firestore://transactions+accounts?customer_id={ctx.customer_id}#hardship"


async def get_customer_360(ctx: CaseContext, customer_id: str | None = None):
    store = await get_store()
    cid = ctx.customer_id
    c = await store.get_customer(cid)
    accts = await store.accounts(cid)
    cards = await store.cards(cid)
    loans = await store.loans(cid)
    srs = await store.service_requests(cid)
    evts = await store.auth_events(cid, days=30)
    last_login = next((e for e in evts if e["type"] == "LOGIN_SUCCESS"), None)
    out = {"customer": {k: c[k] for k in ("customer_id", "full_name", "segment", "city", "relationship_since",
                                           "risk_rating", "kyc_status", "vulnerable_customer", "nps_last")},
           "accounts": accts, "cards": [{k: v for k, v in x.items() if k not in {"issued_on"}} for x in cards],
           "loans": [{k: v for k, v in ln.items() if k != "emi_schedule"} for ln in loans],
           "service_requests": srs, "last_login": last_login,
           "total_relationship_value": sum(a["balance"] for a in accts)}
    return out, f"360: {len(accts)} accounts, {len(cards)} cards, {len(loans)} loans, {len(srs)} service requests", \
        f"firestore://customers/{cid}#360"


async def get_service_requests(ctx: CaseContext, customer_id: str | None = None):
    store = await get_store()
    srs = await store.service_requests(ctx.customer_id)
    open_ = [s for s in srs if s["status"] not in {"CLOSED"}]
    return {"service_requests": srs}, f"{len(srs)} service requests ({len(open_)} in progress)", \
        f"firestore://service_requests?customer_id={ctx.customer_id}"


# ---------------------------------------------------------------------------
# Registry: declarations (for Gemini) + implementations
# ---------------------------------------------------------------------------

_CID = {"customer_id": {"type": "string", "description": "Verified customer id, e.g. C1001"}}

TOOL_SPECS: dict[str, dict] = {
    "lookup_customer": {
        "description": "Look up and verify a bank customer by full name plus EITHER the last 4 digits of their "
                       "registered mobile number OR their customer id. Returns verified=true/false.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "Caller's full name as spoken"},
            "mobile_last4": {"type": "string", "description": "Last 4 digits of registered mobile, digits only"},
            "customer_id": {"type": "string", "description": "Customer id like C1001"}},
            "required": ["name"]},
        "fn": lookup_customer},
    "get_customer_profile": {"description": "Get the verified customer's KYC profile, segment, products, cards, accounts.",
                             "parameters": {"type": "object", "properties": _CID}, "fn": get_customer_profile},
    "get_recent_transactions": {
        "description": "Get recent transactions (default 90 days) with MCC, location, channel and device, plus stats.",
        "parameters": {"type": "object", "properties": {**_CID,
            "days": {"type": "integer", "description": "Look-back window in days (max 90)"},
            "instrument": {"type": "string", "enum": ["credit_card", "debit_card", "account"]}}},
        "fn": get_recent_transactions},
    "get_prior_fraud_flags": {"description": "Get prior fraud flags, alerts and SARs for the customer.",
                              "parameters": {"type": "object", "properties": _CID}, "fn": get_prior_fraud_flags},
    "check_ani_match": {"description": "Check whether the calling phone number (ANI) matches the registered mobile "
                                       "and whether that SIM was recently swapped.",
                        "parameters": {"type": "object", "properties": _CID}, "fn": check_ani_match},
    "check_recent_auth_events": {
        "description": "Get recent authentication events: SIM swap, password/MPIN reset, new device, OTP failures.",
        "parameters": {"type": "object", "properties": {**_CID, "days": {"type": "integer"}}},
        "fn": check_recent_auth_events},
    "get_atm_velocity": {"description": "ATM withdrawal velocity in the last N hours: count, distinct ATMs, max per hour.",
                         "parameters": {"type": "object", "properties": {**_CID, "hours": {"type": "integer"}}},
                         "fn": get_atm_velocity},
    "get_linked_account_activity": {
        "description": "Outflows from the account linked to the debit card: transfers, new beneficiaries, % drained.",
        "parameters": {"type": "object", "properties": {**_CID, "hours": {"type": "integer"}}},
        "fn": get_linked_account_activity},
    "get_emi_schedule": {"description": "EMI schedule for the customer's loans (last 12 and next 3 instalments).",
                         "parameters": {"type": "object", "properties": {**_CID, "loan_id": {"type": "string"}}},
                         "fn": get_emi_schedule},
    "get_repayment_history": {"description": "Repayment history: on-time, late, bounced EMIs, DPD, overdue amount.",
                              "parameters": {"type": "object", "properties": _CID}, "fn": get_repayment_history},
    "get_hardship_signals": {"description": "Financial hardship signals: salary stop, balance depletion, card utilisation.",
                             "parameters": {"type": "object", "properties": _CID}, "fn": get_hardship_signals},
    "get_customer_360": {"description": "Customer 360: all accounts with balances, cards, loans, service requests, last login.",
                         "parameters": {"type": "object", "properties": _CID}, "fn": get_customer_360},
    "get_service_requests": {"description": "Open and recent service requests (cheque book, address change...).",
                             "parameters": {"type": "object", "properties": _CID}, "fn": get_service_requests},
}


def specs_for(names: list[str]) -> list[dict]:
    return [{"name": n, "description": TOOL_SPECS[n]["description"], "parameters": TOOL_SPECS[n]["parameters"]}
            for n in names]


async def execute_tool(ctx: CaseContext, agent_id: str, name: str, args: dict) -> dict:
    """Run a tool, record evidence, publish activity events, return LLM-facing result."""
    spec = TOOL_SPECS.get(name)
    if not spec:
        return {"error": f"unknown tool {name}"}
    allowed = set(spec["parameters"].get("properties", {}).keys())
    clean = {k: v for k, v in (args or {}).items() if k in allowed and v not in (None, "")}
    if name != "lookup_customer":
        if not ctx.customer_id:
            return {"error": "customer not verified"}
        clean["customer_id"] = ctx.customer_id  # never trust model-supplied ids
    ctx.publish("agent.tool_call", {"agent_id": agent_id, "tool": name, "args": clean})
    t0 = time.perf_counter()
    try:
        result, summary, source = await spec["fn"](ctx, **clean)
    except Exception as exc:  # surface tool errors to the model instead of crashing
        ctx.publish("agent.tool_result", {"agent_id": agent_id, "tool": name, "error": str(exc)})
        return {"error": str(exc)}
    ev = ctx.add_evidence(name, agent_id, clean, source, summary, result)
    ctx.publish("agent.tool_result", {"agent_id": agent_id, "tool": name, "evidence_id": ev.id, "summary": summary,
                                      "source": source, "ms": round((time.perf_counter() - t0) * 1000)})
    return {"evidence_id": ev.id, **(result if isinstance(result, dict) else {"data": result})}
