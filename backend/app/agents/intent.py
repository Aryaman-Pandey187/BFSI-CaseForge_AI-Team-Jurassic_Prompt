"""
Intent & Routing Agent.

Classifies the caller's problem into one of the supported intents, extracts
entities (amount, date, merchant, location, card last 4, query type...) and
picks a specialist orchestrator. Gemini is *forced* to call ``route_case``
(function-calling mode ANY) so the output is always structured. A keyword +
regex classifier is the offline / failure fallback.
"""
from __future__ import annotations

import logging
import re

from app.agents.textnum import words_to_number
from app.core.llm import llm, user_content

log = logging.getLogger("caseforge.intent")

INTENTS = {
    "CREDIT_CARD_FRAUD": "credit_card", "CREDIT_CARD_DISPUTE": "credit_card",
    "DEBIT_CARD_FRAUD": "debit_card", "DEBIT_CARD_DISPUTE": "debit_card",
    "LOAN_HARDSHIP": "loan", "LOAN_QUERY": "loan",
    "ACCOUNT_QUERY": "account",
}
QUERY_TYPES = ["balance", "cheque_book", "fd_maturity", "statement", "card_status", "address_change",
               "service_request_status", "other"]

ROUTE_TOOL = {
    "name": "route_case",
    "description": "Classify the caller's issue and extract entities for routing to a specialist orchestrator.",
    "parameters": {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": list(INTENTS) + ["UNCLEAR"]},
            "confidence": {"type": "number", "description": "0-1"},
            "summary": {"type": "string", "description": "One-sentence summary of the caller's problem"},
            "needs_clarification": {"type": "boolean"},
            "clarifying_question": {"type": "string", "description": "Short spoken question if intent is unclear"},
            "entities": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number", "description": "Amount in INR if mentioned"},
                    "date": {"type": "string", "description": "When it happened, as said (e.g. 'last night')"},
                    "merchant": {"type": "string"},
                    "location": {"type": "string"},
                    "card_last4": {"type": "string"},
                    "card_in_possession": {"type": "boolean"},
                    "customer_recognises_transaction": {"type": "boolean"},
                    "loan_type": {"type": "string"},
                    "hardship_reason": {"type": "string"},
                    "query_types": {"type": "array", "items": {"type": "string", "enum": QUERY_TYPES}},
                },
            },
        },
        "required": ["intent", "confidence", "summary", "entities"],
    },
}

SYSTEM = """You are the Intent & Routing Agent in a bank contact centre (BFSI).
Read the call transcript and call route_case exactly once.
Intents:
- CREDIT_CARD_FRAUD: unrecognised/unauthorised credit card transactions, lost/stolen credit card.
- CREDIT_CARD_DISPUTE: recognised merchant but wrong/double charge, refund not received.
- DEBIT_CARD_FRAUD: unauthorised ATM withdrawals or debit card spends, lost/stolen debit card, money taken from account.
- DEBIT_CARD_DISPUTE: ATM did not dispense cash, failed debit transaction still debited.
- LOAN_HARDSHIP: can't pay EMI, job loss, medical emergency, wants restructuring/moratorium.
- LOAN_QUERY: EMI amount/date, outstanding, prepayment, foreclosure, statement.
- ACCOUNT_QUERY: balance, cheque book, FD, statement, address change, service request status.
Use UNCLEAR with a short clarifying_question only when you genuinely cannot tell.
Convert spoken amounts to numbers in INR ("one lakh eighty four thousand" -> 184000)."""


async def classify(transcript_lines: list[str]) -> dict:
    """Return {intent, route, confidence, summary, entities, needs_clarification, clarifying_question, engine}."""
    text = "\n".join(transcript_lines)
    if llm.enabled:
        try:
            captured: dict = {}

            async def execute(name: str, args: dict) -> dict:
                captured.update(args)
                return {"ok": True}

            history = [user_content(f"Call transcript so far:\n{text}")]
            await llm.tool_loop(system=SYSTEM, history=history, tools=[ROUTE_TOOL], execute=execute,
                                max_rounds=1, force_tool=True, temperature=0.0)
            if captured.get("intent"):
                return _finalise(captured, "gemini", text)
        except Exception as exc:  # LLMUnavailable, timeouts, bad responses -> deterministic path
            log.warning("Intent LLM unavailable, using rules: %s", exc)
    return _finalise(rule_classify(text), "rules", text)


def _finalise(r: dict, engine: str, text: str) -> dict:
    intent = r.get("intent", "UNCLEAR")
    ents = dict(r.get("entities") or {})
    # deterministic safety net for amounts the model may have missed
    if not ents.get("amount"):
        caller_text = " ".join(l.split(":", 1)[-1] for l in text.splitlines() if l.lower().startswith("caller"))
        amt = words_to_number(caller_text)
        if amt and amt >= 100 and intent != "ACCOUNT_QUERY":
            ents["amount"] = amt
    if intent == "ACCOUNT_QUERY" and not ents.get("query_types"):
        ents["query_types"] = rule_classify(text)["entities"].get("query_types", ["other"])
    return {"intent": intent, "route": INTENTS.get(intent), "confidence": float(r.get("confidence", 0.5)),
            "summary": r.get("summary", ""), "entities": {k: v for k, v in ents.items() if v not in (None, "", [])},
            "needs_clarification": bool(r.get("needs_clarification")) or intent == "UNCLEAR",
            "clarifying_question": r.get("clarifying_question")
            or "Could you tell me a little more? Is this about a card, a loan, or your account?",
            "engine": engine}


def rule_classify(text: str) -> dict:
    caller = " ".join(l.split(":", 1)[-1] for l in text.splitlines() if l.lower().startswith("caller")) or text
    t = caller.lower()
    fraud = bool(re.search(r"never|didn'?t (make|do|authori[sz]e)|not me|fraud|stolen|missing|lost my (debit |credit )?card|"
                           r"unauthori[sz]ed|don'?t recogni[sz]e|someone (used|took)|can'?t find my", t))
    dispute = bool(re.search(r"twice|double|charged two|refund|not dispensed|didn'?t get (the )?cash", t))
    ents: dict = {}
    if m := re.search(r"\b(?:at|from)\s+(?:some\s+|an?\s+)?([a-z][\w&' ]{2,40}?)(?:\s+(?:in|on|for|yesterday|last|today)\b|[,.]|$)", t):
        ents["merchant"] = m.group(1).strip().title()
    places = [(t.find(p), p) for p in ["romania", "bucharest", "dubai", "london", "singapore", "hosur", "mumbai",
                                       "bangalore", "bengaluru", "delhi", "chennai"] if p in t]
    if places:
        ents["location"] = min(places)[1].title()  # first place mentioned
    for d in ["last night", "yesterday", "today", "this morning", "last week"]:
        if d in t:
            ents["date"] = d
    if m := re.search(r"\bin (july|august|september|june|may)\b", t):
        ents.setdefault("date", m.group(1).title())
    if re.search(r"card", t) and re.search(r"(can'?t|cannot) find|lost (my|the) (debit |credit )?card|stolen|missing", t):
        ents["card_in_possession"] = False
    elif re.search(r"card is with me|(still )?have (the|my) card", t):
        ents["card_in_possession"] = True
    if fraud:
        ents["customer_recognises_transaction"] = False

    if re.search(r"\bloan|emi|instal?ment|restructur|moratorium|foreclos|prepay", t):
        hardship = bool(re.search(r"lost my job|laid off|can'?t pay|unable to pay|missed|relief|hardship|medical|restructur|moratorium", t))
        if m := re.search(r"(home|personal|car|education|gold) loan", t):
            ents["loan_type"] = m.group(1)
        if hardship and (m := re.search(r"(lost my job|laid off|medical \w+|salary (stopped|delayed))", t)):
            ents["hardship_reason"] = m.group(1)
        intent, conf, summ = ("LOAN_HARDSHIP", 0.86, "Customer reports financial hardship and missed EMIs; seeks relief options") \
            if hardship else ("LOAN_QUERY", 0.8, "Customer has a question about their loan")
    elif re.search(r"debit card|atm|withdraw|cash", t):
        intent = "DEBIT_CARD_DISPUTE" if dispute and not fraud else "DEBIT_CARD_FRAUD"
        conf, summ = 0.88, ("Customer reports unauthorised ATM withdrawals / debit card misuse" if intent.endswith("FRAUD")
                            else "Customer disputes a failed debit card / ATM transaction")
    elif re.search(r"credit card|charge|transaction|purchase|swipe", t):
        intent = "CREDIT_CARD_DISPUTE" if dispute and not fraud else "CREDIT_CARD_FRAUD"
        conf, summ = 0.9, ("Customer reports an unrecognised high-value credit card transaction" if intent.endswith("FRAUD")
                           else "Customer disputes a duplicate / incorrect credit card charge")
    elif re.search(r"balance|cheque|check book|statement|fixed deposit|\bfd\b|address|account", t):
        q = []
        if "balance" in t: q.append("balance")
        if re.search(r"cheque|check book|chequebook", t): q.append("cheque_book")
        if re.search(r"fixed deposit|\bfd\b|matur", t): q.append("fd_maturity")
        if "statement" in t: q.append("statement")
        if "address" in t: q.append("address_change")
        ents["query_types"] = q or ["other"]
        intent, conf, summ = "ACCOUNT_QUERY", 0.85, "Customer has a general account query: " + ", ".join(q or ["other"]).replace("_", " ")
    else:
        return {"intent": "UNCLEAR", "confidence": 0.3, "summary": "Issue not yet clear", "entities": ents,
                "needs_clarification": True,
                "clarifying_question": "Sure. Is this about a credit card, a debit card, a loan, or your account?"}
    if (amt := words_to_number(caller)) and amt >= 100 and intent != "ACCOUNT_QUERY":
        ents["amount"] = amt
    return {"intent": intent, "confidence": conf, "summary": summ, "entities": ents}
