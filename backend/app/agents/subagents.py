"""
Specialist sub-agents (the "enrichers").

Each sub-agent owns a small set of tools. With Gemini enabled the agent is a
real function-calling loop: it decides which of its tools to call (and with
what arguments), then writes JSON findings that cite evidence ids. A
deterministic summariser always runs too, so (a) the UI never shows an empty
card and (b) if the model times out the case is still complete.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Callable

from app.agents.tools import CaseContext, execute_tool, inr, specs_for
from app.config import get_settings
from app.core.llm import llm, parse_json, user_content

log = logging.getLogger("caseforge.subagents")

SUBAGENT_SYSTEM = """You are the {title} inside a bank's contact-centre case-building system.
Mission: {mission}
Case brief: {brief}
Steps: 1) Call the tools you need (you may call several in parallel). 2) Then reply with ONLY a JSON object:
{{"headline": "<max 14 words>", "findings": [{{"text": "<one factual sentence>", "evidence": ["E<n>"]}}], "flags": ["<SHORT_CODE>"]}}
Cite the evidence_id returned by each tool. Never invent data. Amounts are INR."""


@dataclass
class SubAgentSpec:
    id: str
    title: str
    mission: str
    calls: list[tuple[str, dict]]  # default tool calls (tool name, args)
    summarize: Callable[[CaseContext, str], tuple[str, list[dict]]]
    icon: str = "bot"
    tools: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.tools = self.tools or [c[0] for c in self.calls]


def _ev(ctx: CaseContext, agent_id: str, tool: str):
    for e in reversed(ctx.evidence):
        if e.tool == tool and e.agent == agent_id:
            return e
    return ctx.latest(tool)


# ---------------------------------------------------------------------------
# Deterministic summarisers
# ---------------------------------------------------------------------------

def sum_profile(ctx, aid):
    e = _ev(ctx, aid, "get_customer_profile")
    p = e.data
    f = [{"text": f"{p['full_name']}, {p['segment']} segment, customer since {p['relationship_since'][:4]}, KYC {p['kyc_status']}.", "evidence": [e.id]},
         {"text": f"Holds {len(p['products'])} products: {', '.join(p['products'][:4])}.", "evidence": [e.id]},
         {"text": f"Bank risk rating {p['risk_rating']}" + (" - vulnerable customer, adapt communication." if p["vulnerable_customer"] else "."), "evidence": [e.id]}]
    if p.get("notes"):
        f.append({"text": f"Note: {p['notes']}", "evidence": [e.id]})
    return f"{p['segment']} customer since {p['relationship_since'][:4]}, risk rating {p['risk_rating']}", f


def sum_txn(ctx, aid):
    e = _ev(ctx, aid, "get_recent_transactions")
    s = e.data["stats"]
    rec = e.data["recent_transactions"]
    foreign = [t for t in rec if t["country"] != "IN"]
    f = [{"text": f"{s['count']} transactions in {s['window_days']} days; average spend {inr(s['avg_debit'])}, typical location {s['home_city']}.", "evidence": [e.id]}]
    if foreign:
        big = max(foreign, key=lambda t: t["amount"])
        f.append({"text": f"{len(foreign)} recent foreign transactions; largest {inr(big['amount'])} at {big['merchant']}, {big['city']} ({big['status'].lower()}).", "evidence": [e.id]})
        head = f"{len(foreign)} foreign txns incl. {inr(big['amount'])} at {big['merchant']}"
    else:
        top = max(rec[:10], key=lambda t: t["amount"]) if rec else None
        head = f"Largest recent txn {inr(top['amount'])} at {top['merchant']}" if top else "No recent transactions"
        if top:
            f.append({"text": f"Largest recent transaction {inr(top['amount'])} at {top['merchant']} via {top['channel']}.", "evidence": [e.id]})
    return head, f


def sum_fraud(ctx, aid):
    e = _ev(ctx, aid, "get_prior_fraud_flags")
    flags = e.data["flags"]
    if not flags:
        return "Clean history - no prior fraud flags or SARs", [{"text": "No prior fraud alerts, disputes or SARs on record.", "evidence": [e.id]}]
    f = [{"text": f"{fl['date']}: {fl['type'].replace('_', ' ').title()} ({fl['status'].lower()}) - {fl['description']}", "evidence": [e.id]} for fl in flags]
    return f"{len(flags)} prior flags, {e.data['sar_count']} SAR filed", f


def sum_identity(ctx, aid):
    ani = _ev(ctx, aid, "check_ani_match")
    au = _ev(ctx, aid, "check_recent_auth_events")
    f, head = [], []
    if ani:
        v = ani.data["verdict"]
        f.append({"text": f"Caller ANI check: {v.replace('_', ' ').lower()}" + (f" (SIM swapped {ani.data['sim_swap_at'][:10]})" if ani.data.get("sim_swap_at") else "") + ".", "evidence": [ani.id]})
        head.append(f"ANI {v.replace('_', ' ').lower()}")
    if au:
        for ev in au.data["risky_events"][:5]:
            f.append({"text": f"{ev['timestamp'][:16].replace('T', ' ')} UTC {ev['type'].replace('_', ' ').title()} via {ev['channel'].replace('_', ' ').lower()} from {ev['ip_city']} - {ev['detail']}.", "evidence": [au.id]})
        head.append(f"{len(au.data['risky_events'])} risky auth events" if au.data["risky_events"] else "no risky auth events")
    h = ", ".join(head)
    return (h[:1].upper() + h[1:]).replace("Ani ", "ANI ").replace("sim swapped", "SIM swapped"), f


def sum_atm(ctx, aid):
    e = _ev(ctx, aid, "get_atm_velocity")
    d = e.data
    f = [{"text": f"{len(d['withdrawals'])} ATM attempts in {d['window_hours']}h across {d['distinct_atms']} ATMs; {inr(d['total_withdrawn'])} withdrawn, {d['declined_count']} declined.", "evidence": [e.id]},
         {"text": f"Peak velocity {d['max_in_1h']} withdrawals in one hour vs a baseline of {d['baseline_atm_per_month']} per month.", "evidence": [e.id]}]
    if d["odd_hour"]:
        f.append({"text": "Activity occurred between midnight and 5 AM IST.", "evidence": [e.id]})
    return f"{d['max_in_1h']} ATM withdrawals/hr, {inr(d['total_withdrawn'])} cashed out", f


def sum_linked(ctx, aid):
    e = _ev(ctx, aid, "get_linked_account_activity")
    d = e.data
    f = [{"text": f"Linked account {d['account_id']} fell from {inr(d['balance_before'])} to {inr(d['current_balance'])} ({d['outflow_pct_of_balance']}% drained).", "evidence": [e.id]}]
    for t in d["transfers"]:
        f.append({"text": f"{t['channel']} {inr(t['amount'])} - {t['merchant']} from device {t['device_id']}.", "evidence": [e.id]})
    return f"{d['outflow_pct_of_balance']}% of linked balance drained in 48h", f


def sum_emi(ctx, aid):
    e = _ev(ctx, aid, "get_emi_schedule")
    f = []
    for ln in e.data["loans"]:
        nxt = ln["next_3"][0]["due_date"] if ln["next_3"] else "n/a"
        f.append({"text": f"{ln['type'].replace('_', ' ').title()} {ln['loan_id']}: EMI {inr(ln['emi_amount'])}, outstanding {inr(ln['outstanding'])}, {ln['remaining_installments']} instalments left, bucket {ln['bucket']}, next due {nxt}.", "evidence": [e.id]})
    total = sum(ln["emi_amount"] for ln in e.data["loans"])
    return f"{len(e.data['loans'])} loans, combined EMI {inr(total)}/month", f


def sum_repay(ctx, aid):
    e = _ev(ctx, aid, "get_repayment_history")
    f = [{"text": f"{ln['type'].replace('_', ' ').title()}: {ln['on_time']} on-time, {ln['late']} late, {ln['bounced']} bounced, {ln['overdue']} overdue; max DPD {ln['max_dpd']}.", "evidence": [e.id]} for ln in e.data["loans"]]
    return f"{e.data['total_bounces']} bounces, {inr(e.data['total_overdue'])} overdue", f


def sum_hardship(ctx, aid):
    e = _ev(ctx, aid, "get_hardship_signals")
    f = [{"text": s["detail"] + ".", "evidence": [e.id]} for s in e.data["signals"]]
    return (f"{len(e.data['signals'])} hardship signals detected" if f else "No hardship signals"), f or [{"text": "No hardship signals in account data.", "evidence": [e.id]}]


def sum_360(ctx, aid):
    e = _ev(ctx, aid, "get_customer_360")
    d = e.data
    f = [{"text": f"{a['type'].replace('_', ' ').title()} {a['account_id']}: balance {inr(a['balance'])}" + (f", matures {a['maturity_date']}" if a.get("maturity_date") else "") + ".", "evidence": [e.id]} for a in d["accounts"]]
    f += [{"text": f"{c['network']} {c['type']} card ••{c['last4']} is {c['status'].lower()}.", "evidence": [e.id]} for c in d["cards"]]
    return f"Total relationship value {inr(d['total_relationship_value'])}", f


def sum_sr(ctx, aid):
    e = _ev(ctx, aid, "get_service_requests")
    srs = e.data["service_requests"]
    f = [{"text": f"{s['sr_id']} {s['type'].replace('_', ' ').title()} - {s['status'].lower()}: {s['detail']}.", "evidence": [e.id]} for s in srs]
    return (f"{len(srs)} service requests on file" if srs else "No service requests"), f or [{"text": "No service requests on file.", "evidence": [e.id]}]


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

def profile_agent():
    return SubAgentSpec("customer_profile", "Customer Profile Agent", "Summarise who the customer is: segment, tenure, products, KYC, risk rating.",
                        [("get_customer_profile", {})], sum_profile, "user")


def txn_agent(instrument):
    return SubAgentSpec("txn_enricher", "Transaction Enricher Agent",
                        f"Enrich the last 90 days of {instrument.replace('_', ' ')} transactions with MCC, location, channel and device context and point out anomalies.",
                        [("get_recent_transactions", {"days": 90, "instrument": instrument})], sum_txn, "receipt")


def fraud_agent():
    return SubAgentSpec("prior_fraud", "Prior Fraud & Alert Agent", "Report prior fraud flags, alerts, disputes and SARs.",
                        [("get_prior_fraud_flags", {})], sum_fraud, "shield")


def identity_channel_agent(days=14):
    return SubAgentSpec("identity_channel", "Identity & Channel Agent",
                        "Assess caller authenticity: ANI vs registered mobile, SIM swap, credential resets, new devices.",
                        [("check_ani_match", {}), ("check_recent_auth_events", {"days": days})], sum_identity, "fingerprint")


def atm_agent():
    return SubAgentSpec("atm_velocity", "ATM Velocity Agent", "Analyse ATM withdrawal velocity and cash-out patterns in the last 24 hours.",
                        [("get_atm_velocity", {"hours": 24})], sum_atm, "banknote")


def linked_agent():
    return SubAgentSpec("linked_account", "Linked Account Agent", "Check outflows from the debit card's linked account: transfers, new payees, drain %.",
                        [("get_linked_account_activity", {"hours": 48})], sum_linked, "link")


def emi_agent():
    return SubAgentSpec("emi_schedule", "EMI Schedule Agent", "Summarise the EMI schedules, outstanding and upcoming dues.",
                        [("get_emi_schedule", {})], sum_emi, "calendar")


def repay_agent():
    return SubAgentSpec("repayment_history", "Repayment & Bounce Agent", "Summarise repayment behaviour, bounces and days-past-due.",
                        [("get_repayment_history", {})], sum_repay, "history")


def hardship_agent():
    return SubAgentSpec("hardship_signals", "Hardship Signals Agent", "Detect financial hardship: salary stop, balance depletion, credit stress.",
                        [("get_hardship_signals", {})], sum_hardship, "heart")


def c360_agent():
    return SubAgentSpec("customer_360", "Customer 360 Agent", "Build a 360 view: balances, deposits, cards, loans, last login.",
                        [("get_customer_360", {})], sum_360, "layers")


def sr_agent():
    return SubAgentSpec("service_requests", "Service Request Agent", "Report status of open and recent service requests.",
                        [("get_service_requests", {})], sum_sr, "inbox")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def run_subagent(ctx: CaseContext, spec: SubAgentSpec, brief: str, group: str) -> dict:
    t0 = time.perf_counter()
    ctx.publish("agent.started", {"agent_id": spec.id, "title": spec.title, "group": group, "icon": spec.icon,
                                  "tools": spec.tools, "parallel": True})
    s = get_settings()
    llm_out: dict = {}
    engine = "rules"
    if llm.enabled:
        try:
            history = [user_content("Investigate now using your tools, then return the JSON.")]
            text = await llm.tool_loop(
                system=SUBAGENT_SYSTEM.format(title=spec.title, mission=spec.mission, brief=brief),
                history=history, tools=specs_for(spec.tools),
                execute=lambda n, a: execute_tool(ctx, spec.id, n, a), max_rounds=3, force_tool=True)
            llm_out, engine = parse_json(text), "gemini"
        except Exception as exc:  # LLMUnavailable, timeouts, bad responses -> deterministic path
            log.warning("%s: LLM unavailable (%s) - deterministic path", spec.id, exc)
    # Guarantee every default tool ran (UI + risk scoring depend on them).
    called = {e.tool for e in ctx.evidence if e.agent == spec.id}
    for tool, args in spec.calls:
        if tool not in called:
            if not llm.enabled:  # make parallel fan-out visible in the demo
                await asyncio.sleep(random.uniform(0.35, 1.3) * float(s.simulator_turn_delay_s > 0))
            await execute_tool(ctx, spec.id, tool, args)
    try:
        headline, findings = spec.summarize(ctx, spec.id)
    except Exception as exc:  # pragma: no cover
        log.exception("summariser failed")
        headline, findings = f"{spec.title} completed", [{"text": str(exc), "evidence": []}]
    valid = {e.id for e in ctx.evidence}
    if llm_out.get("findings"):
        llm_f = [{"text": f.get("text", ""), "evidence": [x for x in f.get("evidence", []) if x in valid]}
                 for f in llm_out["findings"] if isinstance(f, dict) and f.get("text")]
        if llm_f:
            findings = llm_f
        headline = llm_out.get("headline") or headline
    result = {"agent_id": spec.id, "title": spec.title, "headline": headline, "findings": findings,
              "flags": llm_out.get("flags", []), "engine": engine,
              "evidence": [e.id for e in ctx.evidence if e.agent == spec.id],
              "duration_ms": round((time.perf_counter() - t0) * 1000)}
    ctx.publish("agent.completed", {**result, "status": "ok", "group": group})
    return result
