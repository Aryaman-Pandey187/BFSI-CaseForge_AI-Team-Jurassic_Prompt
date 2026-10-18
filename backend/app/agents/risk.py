"""
Deterministic Risk Scoring Agent.

Scoring is intentionally *not* done by the LLM: banks need reproducible,
explainable scores. Each detector emits a reason code with points and the
evidence ids (tool outputs) that justify it. Raw points are combined with a
saturating curve so many weak signals can't trivially hit 100:

    score = 100 * (1 - exp(-raw / 45))

Bands: LOW < 30 <= MEDIUM < 60 <= HIGH < 80 <= CRITICAL
"""
from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta, timezone

from app.agents.tools import CaseContext, haversine_km, inr
from app.core.datastore import get_store, parse_ts

IST = timezone(timedelta(hours=5, minutes=30))
HIGH_RISK_MCC = {"5732": "Electronics", "5944": "Jewellery", "6051": "Quasi-cash", "4829": "Money transfer",
                 "7995": "Gambling", "5816": "Digital goods"}
BASELINE = {"LOW": 3, "MEDIUM": 10, "HIGH": 22}


def band(score: int) -> str:
    return "CRITICAL" if score >= 80 else "HIGH" if score >= 60 else "MEDIUM" if score >= 30 else "LOW"


class Reasons:
    def __init__(self, ctx: CaseContext):
        self.ctx, self.items = ctx, []

    def add(self, code: str, label: str, points: int, detail: str, tools: list[str], txn_ids: list[str] | None = None):
        ev = [e.id for t in tools if (e := self.ctx.latest(t))]
        self.items.append({"code": code, "label": label, "points": points, "detail": detail, "evidence": ev,
                           "txn_ids": txn_ids or []})


def _composite(raw: float) -> int:
    return int(round(100 * (1 - math.exp(-raw / 45))))


async def score_card_fraud(ctx: CaseContext, instrument: str) -> dict:
    """Fraud score for credit- or debit-card cases."""
    store = await get_store()
    cust = await store.get_customer(ctx.customer_id)
    all_txns = sorted(await store.transactions(ctx.customer_id, days=90), key=lambda t: t["timestamp"])
    now = datetime.now(timezone.utc)
    recent_cut, hist_cut = now - timedelta(hours=72), now - timedelta(days=90)
    card_txns = [t for t in all_txns if t["instrument"] == instrument]
    recent = [t for t in card_txns if parse_ts(t["timestamp"]) >= recent_cut]
    history = [t for t in card_txns if parse_ts(t["timestamp"]) < recent_cut and parse_ts(t["timestamp"]) >= hist_cut]
    r = Reasons(ctx)
    flagged: dict[str, dict] = {}

    def flag(t, why):
        f = flagged.setdefault(t["txn_id"], {**t, "flags": []})
        if why not in f["flags"]:
            f["flags"].append(why)

    # 1. Geo-velocity / impossible travel ---------------------------------
    window = [t for t in card_txns if parse_ts(t["timestamp"]) >= now - timedelta(days=7)]
    worst = None
    for a, b in zip(window, window[1:]):
        hrs = max((parse_ts(b["timestamp"]) - parse_ts(a["timestamp"])).total_seconds() / 3600, 0.05)
        km = haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
        if km > 300 and km / hrs > 800 and (worst is None or km / hrs > worst[2]):
            worst = (a, b, km / hrs, km, hrs)
    if worst:
        a, b, speed, km, hrs = worst
        r.add("GEO_VELOCITY", "Impossible travel", 25,
              f"{a['city']} → {b['city']} ({km:,.0f} km) in {hrs * 60:.0f} min = {speed:,.0f} km/h",
              ["get_recent_transactions"], [a["txn_id"], b["txn_id"]])
        flag(b, "Impossible travel")

    # 2. New country -------------------------------------------------------
    hist_countries = {t["country"] for t in history}
    new_c = [t for t in recent if t["country"] not in hist_countries and t["country"] != cust["country"]]
    if new_c:
        r.add("NEW_COUNTRY", "First-ever foreign usage", 10,
              f"{len(new_c)} txns in {new_c[0]['country']} - no foreign usage in prior 90 days",
              ["get_recent_transactions"], [t["txn_id"] for t in new_c])
        for t in new_c:
            flag(t, f"New country ({t['country']})")

    # 3. Unusual spend ------------------------------------------------------
    hist_amts = [t["amount"] for t in history if t["direction"] == "DEBIT"] or [1.0]
    mu = statistics.mean(hist_amts)
    sd = statistics.pstdev(hist_amts) or 1.0
    big = [t for t in recent if t["direction"] == "DEBIT" and t["amount"] > max(5 * mu, 25000)]
    if big:
        top = max(big, key=lambda t: t["amount"])
        z = (top["amount"] - mu) / sd
        r.add("UNUSUAL_AMOUNT", "Unusual spend amount", 20,
              f"{inr(top['amount'])} is {top['amount'] / mu:.0f}× the 90-day average of {inr(mu)} (z={z:.1f})",
              ["get_recent_transactions"], [t["txn_id"] for t in big])
        for t in big:
            flag(t, "Unusual amount")

    # 4. Transaction velocity ----------------------------------------------
    last24 = [t for t in card_txns if parse_ts(t["timestamp"]) >= now - timedelta(hours=24)]
    max_1h = max((sum(1 for u in last24[i:] if parse_ts(u["timestamp"]) - parse_ts(t["timestamp"]) <= timedelta(hours=1))
                  for i, t in enumerate(last24)), default=0)
    daily_base = len(history) / 87 if history else 0.3
    if max_1h >= 3:
        r.add("VELOCITY_SPIKE", "Transaction velocity spike", 10,
              f"{max_1h} card txns within 60 min vs baseline {daily_base:.1f}/day", ["get_recent_transactions"],
              [t["txn_id"] for t in last24])

    # 5. Card testing -------------------------------------------------------
    small = [t for t in recent if t["amount"] < 200 and t["channel"] == "ECOM"]
    if len(small) >= 2 and big:
        r.add("CARD_TESTING", "Card-testing pattern", 10,
              f"{len(small)} micro-charges at {small[0]['merchant']} before large purchase", ["get_recent_transactions"],
              [t["txn_id"] for t in small])
        for t in small:
            flag(t, "Card testing")

    # 6. High-risk MCC / entry mode ----------------------------------------
    hr = [t for t in recent if t["mcc"] in HIGH_RISK_MCC and (t in big or t["country"] != "IN")]
    if hr:
        r.add("HIGH_RISK_MCC", "High-risk merchant category", 5,
              ", ".join(sorted({HIGH_RISK_MCC[t['mcc']] for t in hr})), ["get_recent_transactions"],
              [t["txn_id"] for t in hr])
    fb = [t for t in recent if t.get("entry_mode") == "MAGSTRIPE_FALLBACK"]
    if fb:
        r.add("MAGSTRIPE_FALLBACK", "Chip bypassed (magstripe fallback)", 5,
              "Card-present txns forced to magstripe - typical of skimmed/cloned card", ["get_recent_transactions"],
              [t["txn_id"] for t in fb])
        for t in fb:
            flag(t, "Magstripe fallback")

    # 7. Debit-specific: ATM velocity, cash-out, linked account drain -------
    if instrument == "debit_card":
        atm_ev = ctx.latest("get_atm_velocity")
        if atm_ev:
            d = atm_ev.data
            if d["max_in_1h"] >= 3:
                r.add("ATM_VELOCITY", "ATM velocity burst", 20,
                      f"{d['max_in_1h']} ATM withdrawals within 1h at {d['distinct_atms']} different ATMs "
                      f"(baseline {d['baseline_atm_per_month']}/month)", ["get_atm_velocity"],
                      [w["txn_id"] for w in d["withdrawals"]])
                for w in d["withdrawals"]:
                    flag({**w, "lat": 0, "lon": 0}, "ATM velocity")
            if d["odd_hour"]:
                r.add("ODD_HOUR", "Unusual hour activity", 5, "Withdrawals between 00:00-05:00 IST", ["get_atm_velocity"])
            if any(w["status"] == "DECLINED" for w in d["withdrawals"]):
                r.add("LIMIT_EXHAUSTION", "Daily limit exhausted", 5, "Withdrawal declined - daily ATM limit hit",
                      ["get_atm_velocity"])
        la = ctx.latest("get_linked_account_activity")
        if la:
            d = la.data
            if d["outflow_pct_of_balance"] >= 50:
                r.add("CASH_OUT_PATTERN", "Cash-out pattern", 20,
                      f"{inr(d['outflow_window'])} ({d['outflow_pct_of_balance']}% of balance) drained in 48h",
                      ["get_linked_account_activity", "get_atm_velocity"])
            if d["new_beneficiary_transfers"]:
                r.add("LINKED_ACCOUNT_DRAIN", "Transfer to new beneficiary", 15,
                      f"{len(d['new_beneficiary_transfers'])} transfers to payee added minutes earlier",
                      ["get_linked_account_activity"], d["new_beneficiary_transfers"])
                for t in d["transfers"]:
                    flag({**t, "lat": 0, "lon": 0}, "New beneficiary")

    # 8. Identity / channel signals ----------------------------------------
    _auth_reasons(r, await store.auth_events(ctx.customer_id, days=7))
    _ani_reason(r, ctx)
    _flag_reasons(r, await store.fraud_flags(ctx.customer_id))
    return _finish(r, cust, "FRAUD", list(flagged.values()))


def _auth_reasons(r: Reasons, evts: list[dict]) -> None:
    types = {e["type"] for e in evts}
    if "SIM_SWAP" in types:
        e = next(e for e in evts if e["type"] == "SIM_SWAP")
        hrs = (datetime.now(timezone.utc) - parse_ts(e["timestamp"])).total_seconds() / 3600
        r.add("SIM_SWAP_RECENT", "SIM swap in last 7 days", 15, f"SIM replaced {hrs:.0f}h ago on registered mobile",
              ["check_recent_auth_events"])
    if types & {"PASSWORD_RESET", "MPIN_RESET"}:
        r.add("CREDENTIAL_RESET", "Credential reset", 10, "Password / MPIN reset in the last 7 days",
              ["check_recent_auth_events"])
    if "NEW_DEVICE_LOGIN" in types or "DEVICE_CHANGE" in types:
        r.add("NEW_DEVICE", "New device login", 5, "Login from an unrecognised device", ["check_recent_auth_events"])
    if "CARD_LIMIT_CHANGE" in types:
        r.add("LIMIT_CHANGE", "Limits raised remotely", 5, "International usage enabled & limits maxed from new device",
              ["check_recent_auth_events"])
    if "BENEFICIARY_ADDED" in types:
        r.add("NEW_BENEFICIARY", "New payee added", 5, "Payee added on new device with cooling period bypassed",
              ["check_recent_auth_events"])
    if "OTP_FAIL" in types or "CARD_PIN_FAIL" in types:
        r.add("AUTH_FAILURES", "Failed authentication attempts", 5, "Wrong OTP / PIN attempts", ["check_recent_auth_events"])


def _ani_reason(r: Reasons, ctx: CaseContext) -> None:
    ev = ctx.latest("check_ani_match")
    if not ev:
        return
    v = ev.data["verdict"]
    if v == "MISMATCH":
        r.add("ANI_MISMATCH", "Caller number not registered", 5, "Calling number differs from registered mobile",
              ["check_ani_match"])
    elif v == "MATCH_BUT_SIM_SWAPPED":
        r.add("ANI_SIM_SWAPPED", "Caller ANI on swapped SIM", 5,
              "Call is from the registered number, but that SIM was swapped recently", ["check_ani_match"])


def _flag_reasons(r: Reasons, flags: list[dict]) -> None:
    if any(f.get("sar_filed") for f in flags):
        r.add("PRIOR_SAR", "Prior SAR on file", 15, "Suspicious Activity Report previously filed", ["get_prior_fraud_flags"])
    open_high = [f for f in flags if f["status"] == "OPEN" and f["severity"] == "HIGH"]
    if open_high:
        r.add("OPEN_FRAUD_FLAG", "Open high-severity alert", 10, open_high[0]["description"], ["get_prior_fraud_flags"])
    if any(f["type"] in {"CHARGEBACK_ABUSE", "DISPUTE_LOST"} for f in flags):
        r.add("FRIENDLY_FRAUD_RISK", "Serial disputer", 10, "History of rejected / abusive disputes",
              ["get_prior_fraud_flags"])


async def score_loan(ctx: CaseContext) -> dict:
    """Delinquency / hardship risk for loan cases."""
    store = await get_store()
    cust = await store.get_customer(ctx.customer_id)
    r = Reasons(ctx)
    rep = ctx.latest("get_repayment_history")
    if rep:
        d = rep.data
        if d["total_bounces"]:
            r.add("EMI_BOUNCES", "EMI bounces", min(30, 10 * d["total_bounces"]),
                  f"{d['total_bounces']} EMI bounces, {inr(d['total_overdue'])} overdue", ["get_repayment_history"])
        max_dpd = max((ln["max_dpd"] for ln in d["loans"]), default=0)
        if max_dpd > 60:
            r.add("DPD_60_PLUS", "60+ days past due", 25, f"Max DPD {max_dpd} - SMA-1, nearing NPA at 90", ["get_repayment_history"])
        elif max_dpd > 30:
            r.add("DPD_30_PLUS", "30+ days past due", 15, f"Max DPD {max_dpd}", ["get_repayment_history"])
    hs = ctx.latest("get_hardship_signals")
    pts = {"SALARY_STOPPED": 20, "FULL_AND_FINAL_SETTLEMENT": 5, "BALANCE_DEPLETION": 10,
           "HIGH_CARD_UTILISATION": 10, "DIGITAL_DISTRESS_INTENT": 5}
    if hs:
        for s in hs.data["signals"]:
            r.add(s["code"], s["code"].replace("_", " ").title(), pts.get(s["code"], 5), s["detail"], ["get_hardship_signals"])
    _ani_reason(r, ctx)
    _flag_reasons(r, await store.fraud_flags(ctx.customer_id))
    return _finish(r, cust, "CREDIT_DELINQUENCY", [])


async def score_account(ctx: CaseContext) -> dict:
    """Authentication / account-takeover risk for general account queries."""
    store = await get_store()
    cust = await store.get_customer(ctx.customer_id)
    r = Reasons(ctx)
    _auth_reasons(r, await store.auth_events(ctx.customer_id, days=7))
    _ani_reason(r, ctx)
    _flag_reasons(r, await store.fraud_flags(ctx.customer_id))
    return _finish(r, cust, "AUTHENTICATION", [])


def _finish(r: Reasons, cust: dict, risk_type: str, flagged: list[dict]) -> dict:
    base = BASELINE.get(cust.get("risk_rating", "LOW"), 3)
    raw = base + sum(i["points"] for i in r.items)
    score = max(_composite(raw), base)
    reasons = sorted(r.items, key=lambda i: -i["points"])
    flagged = sorted(flagged, key=lambda t: t["timestamp"], reverse=True)
    for t in flagged:
        for k in ("lat", "lon", "customer_id", "account_id"):
            t.pop(k, None)
    return {"score": score, "band": band(score), "risk_type": risk_type, "raw_points": raw,
            "baseline_points": base, "reasons": reasons, "flagged_transactions": flagged,
            "method": "deterministic-v1: saturating sum of weighted reason codes, 100*(1-e^(-raw/45))"}
