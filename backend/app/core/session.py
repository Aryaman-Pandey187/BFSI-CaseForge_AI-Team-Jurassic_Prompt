"""
Call session: the conversation state machine shared by every channel
(Twilio Media Streams, Twilio Gather, the text simulator).

    GREETING ─► IDENTITY ─► INTENT ─► ORCHESTRATING ─► HANDOFF | RESOLVED ─► ENDED

Channels only need three calls:
    greet()                 -> TurnResult   (first thing the caller hears)
    handle(utterance)       -> TurnResult   (each final STT transcript)
    after_hold()            -> TurnResult   (when TurnResult.action == "hold")
and ``end()`` when the call finishes (writes the post-call case log).
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from app.agents.identity import IdentityAgent
from app.agents.intent import classify
from app.agents.orchestrators import run_orchestrator
from app.agents.tools import CaseContext
from app.config import get_settings
from app.core.datastore import get_store
from app.core.events import hub, now_iso
from app.core.llm import llm, user_content

log = logging.getLogger("caseforge.session")

STAGE_LABEL = {"GREETING": "Greeting", "IDENTITY": "Verifying identity", "INTENT": "Understanding request",
               "ORCHESTRATING": "Agents investigating", "HANDOFF": "Handed to human agent",
               "RESOLVED": "Resolved by AI", "ENDED": "Call ended"}
HOLD_LINES = {
    "credit_card": "Thanks. I'm pulling up your card activity and running some security checks now. This will take just a few seconds.",
    "debit_card": "I understand, let me check your debit card and account activity right away. One moment please.",
    "loan": "Thank you for sharing that. Let me pull up your loan details, it'll take just a moment.",
    "account": "Sure, let me check that for you, one moment.",
}
BYE = re.compile(r"\b(bye|goodbye|that'?s all|nothing else|no,? thanks?|no thank you|that'?s it|all good|no that'?s)\b", re.I)


@dataclass
class TurnResult:
    say: str
    action: str = "continue"  # continue | hold | handoff | end


class CallSession:
    def __init__(self, call_id: str, channel: str, caller_number: str | None, scenario: str | None = None):
        self.call_id = call_id
        self.channel = channel
        self.caller_number = caller_number
        self.scenario = scenario
        self.started = time.time()
        self.stage = "GREETING"
        self.transcript: list[dict] = []
        self.ctx = CaseContext(call_id=call_id, caller_number=caller_number, publish=self.publish)
        self.identity = IdentityAgent(self.ctx)
        self.customer: dict | None = None
        self.intent: dict | None = None
        self.case: dict | None = None
        self.task: asyncio.Task | None = None
        self.clarifications = 0
        self.ended = False
        self.post_history: list = []
        self.issue_from = 0  # transcript index where the caller's problem statement starts
        self.lock = asyncio.Lock()
        s = get_settings()
        self.publish("call.started", {"channel": channel, "caller_number": caller_number, "scenario": scenario,
                                      "started_at": now_iso(), "bank": s.bank_name, "persona": s.agent_persona,
                                      "llm_mode": s.llm_mode, "voice_mode": s.voice_mode if channel == "phone" else channel})
        self.set_stage("GREETING")

    # ---- events -----------------------------------------------------------
    def publish(self, type_: str, data: dict | None = None):
        return hub.publish(self.call_id, type_, data)

    def set_stage(self, stage: str):
        self.stage = stage
        self.publish("call.stage", {"stage": stage, "label": STAGE_LABEL[stage]})

    def voice_state(self, state: str):
        self.publish("voice.state", {"state": state})

    def add_line(self, role: str, text: str, interim: bool = False):
        if not text:
            return
        line = {"id": uuid.uuid4().hex[:8], "role": role, "text": text, "ts": now_iso(), "interim": interim}
        if not interim:
            self.transcript.append(line)
        self.publish("transcript", line)

    def _caller_lines(self) -> list[str]:
        """Transcript from the problem statement onwards (identity digits excluded)."""
        return [f"{'Caller' if l['role'] == 'caller' else 'Assistant'}: {l['text']}"
                for l in self.transcript[self.issue_from:]]

    # ---- turns ------------------------------------------------------------
    async def greet(self) -> TurnResult:
        text = self.identity.greeting()
        self.set_stage("IDENTITY")
        self.add_line("ai", text)
        return TurnResult(text)

    async def handle(self, utterance: str) -> TurnResult:
        utterance = (utterance or "").strip()
        async with self.lock:
            if not utterance:
                return self._say("Sorry, I didn't catch that. Could you say it again?")
            self.add_line("caller", utterance)
            self.voice_state("thinking")
            try:
                return await self._dispatch(utterance)
            except Exception:  # never drop a live call because of a bug
                log.exception("turn failed")
                return self._say("Sorry, I'm having a little trouble. Let me connect you to a colleague.", "handoff")

    async def _dispatch(self, utterance: str) -> TurnResult:
        if self.stage in {"GREETING", "IDENTITY"}:
            reply = await self.identity.respond(utterance)
            if self.identity.verified and not self.customer:
                await self._on_verified()
                # problem statement starts at this utterance if mentioned, else at the next one
                self.issue_from = len(self.transcript) - (1 if self.identity.issue_mentioned else 0)
                self.set_stage("INTENT")
                if self.identity.issue_mentioned:
                    started = await self._classify_and_route(prefix=reply)
                    if started:
                        return started
                    return self._say(f"{_statements(reply)} {self.intent['clarifying_question']}".strip())
                return self._say(reply)
            if self.identity.attempts >= 3:
                self.publish("handoff", {"reason": "identity_not_verified", "queue": "Retail Service"})
                self.set_stage("HANDOFF")
                return self._say(reply, "handoff")
            return self._say(reply)
        if self.stage == "INTENT":
            res = await self._classify_and_route()
            return res or self._say(self.intent["clarifying_question"])
        if self.stage == "ORCHESTRATING":
            return self._say("I'm still checking that for you, just a moment.", "hold")
        return await self._post_case(utterance)

    async def _on_verified(self):
        store = await get_store()
        self.customer = await store.get_customer(self.identity.verified["customer_id"])
        cid = self.customer["customer_id"]
        accts, cards, loans = await store.accounts(cid), await store.cards(cid), await store.loans(cid)
        c = self.customer
        self.publish("customer.snapshot", {
            "customer_id": cid, "full_name": c["full_name"], "first_name": c["first_name"], "segment": c["segment"],
            "city": c["city"], "dob": c["dob"], "email": c["email"], "registered_mobile": c["registered_mobile"][:3] + "•••••" + c["mobile_last4"],
            "relationship_since": c["relationship_since"], "kyc_status": c["kyc_status"], "risk_rating": c["risk_rating"],
            "vulnerable_customer": c["vulnerable_customer"], "nps_last": c["nps_last"], "products": c["products"],
            "accounts": [{k: a.get(k) for k in ("account_id", "type", "balance", "status", "maturity_date")} for a in accts],
            "cards": [{k: x.get(k) for k in ("card_id", "type", "network", "variant", "last4", "status", "credit_limit",
                                              "available_limit", "outstanding")} for x in cards],
            "loans": [{k: l.get(k) for k in ("loan_id", "type", "outstanding", "emi_amount", "dpd", "bucket")} for l in loans],
            "total_balance": sum(a["balance"] for a in accts if a["type"] != "fixed_deposit"),
            "total_deposits": sum(a["balance"] for a in accts if a["type"] == "fixed_deposit")})

    async def _classify_and_route(self, prefix: str | None = None) -> TurnResult | None:
        self.intent = await classify(self._caller_lines())
        self.publish("intent.classified", self.intent)
        if (self.intent["needs_clarification"] or not self.intent["route"]) and self.clarifications < 2:
            self.clarifications += 1
            return None  # caller asks the clarifying question
        if not self.intent["route"]:
            self.publish("handoff", {"reason": "intent_unclear", "queue": "Retail Service"})
            self.set_stage("HANDOFF")
            return self._say("Let me connect you to a colleague who can help with that.", "handoff")
        self.set_stage("ORCHESTRATING")
        self.task = asyncio.create_task(self._orchestrate())
        hold = HOLD_LINES[self.intent["route"]]
        if prefix:  # verified + issue known in the same turn: drop any "how can I help?" question
            hold = f"{_statements(prefix)} {hold.split('. ', 1)[-1] if hold.startswith('Thanks') else hold}".strip()
        return self._say(hold, "hold")

    async def _orchestrate(self):
        try:
            self.case = await run_orchestrator(self.ctx, self.intent, self.customer)
            self.case["transcript_so_far"] = len(self.transcript)
            self.publish("case.assembled", self.case)
        except Exception as exc:
            log.exception("orchestration failed")
            self.publish("error", {"where": "orchestrator", "message": str(exc)})

    async def after_hold(self, timeout: float = 45.0) -> TurnResult:
        if self.task:
            try:
                await asyncio.wait_for(asyncio.shield(self.task), timeout)
            except asyncio.TimeoutError:
                return self._say("Thanks for holding, this is taking a little longer than usual.", "hold")
        if not self.case:
            self.set_stage("HANDOFF")
            return self._say("Thanks for holding. I'm connecting you to a specialist who can help.", "handoff")
        if self.case["status"] == "RESOLVED_BY_AI":
            self.set_stage("RESOLVED")
            return self._say(self.case["caller_message"], "continue")
        self.set_stage("HANDOFF")
        self.publish("handoff", {"reason": "case_ready", "queue": self.case["queue"], "priority": self.case["priority"],
                                 "case_id": self.case["case_id"]})
        return self._say(self.case["caller_message"], "handoff")

    async def _post_case(self, utterance: str) -> TurnResult:
        if BYE.search(utterance) or re.fullmatch(r"\s*(no|nope|thanks?|thank you)[.! ]*", utterance, re.I):
            return self._say(f"You're welcome. Thank you for calling {get_settings().bank_name}. Take care, goodbye!", "end")
        if self.stage == "RESOLVED":
            # new request after an AI-resolved query: hand off with context
            self.set_stage("HANDOFF")
            self.publish("handoff", {"reason": "follow_up_request", "queue": "Retail Service",
                                     "case_id": self.case["case_id"] if self.case else None})
            return self._say("Sure, let me connect you to a colleague for that. They can already see our conversation.", "handoff")
        reply = None
        if llm.enabled and self.case:
            try:
                sys = ("You are a bank voice assistant holding the line until a human specialist joins. The case summary is: "
                       f"{self.case['summary']['headline']}. Reassure the caller in ONE short sentence (max 25 words). "
                       "Do not take actions, do not promise outcomes, never reveal risk scores. If they ask to block a card, "
                       "say the specialist will do it the moment they join, within a minute.")
                self.post_history.append(user_content(utterance))
                reply = await llm.text(system=sys, history=self.post_history)
            except Exception:
                reply = None
        if not reply:
            if re.search(r"\bblock|freeze|stop\b", utterance, re.I):
                reply = "Absolutely. The specialist will secure your card the moment they join, which will be in under a minute."
            else:
                reply = "Understood. A specialist is joining you now and already has your full case, so you won't need to repeat anything."
        return self._say(reply, "handoff")

    def _say(self, text: str, action: str = "continue") -> TurnResult:
        self.add_line("ai", text)
        self.voice_state("speaking")
        return TurnResult(text, action)

    # ---- post-call logging -------------------------------------------------
    async def end(self, reason: str = "completed") -> dict | None:
        if self.ended:
            return None
        self.ended = True
        if self.task and not self.task.done():
            try:
                await asyncio.wait_for(self.task, 30)
            except Exception:
                pass
        duration = round(time.time() - self.started)
        disposition = ("RESOLVED_BY_AI" if self.stage == "RESOLVED" or (self.case and self.case["status"] == "RESOLVED_BY_AI")
                       else "HANDED_OFF" if self.stage == "HANDOFF" else "ABANDONED")
        record = dict(self.case or {
            "case_id": f"CF-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:6].upper()}", "call_id": self.call_id,
            "created_at": datetime.now(timezone.utc).isoformat(), "status": "NO_CASE",
            "customer": {k: self.customer.get(k) for k in ("customer_id", "full_name")} if self.customer else None})
        record.update({"post_call": {"ended_at": now_iso(), "duration_s": duration, "disposition": disposition,
                                     "end_reason": reason, "channel": self.channel, "caller_number": self.caller_number,
                                     "turns": len(self.transcript)},
                       "transcript": self.transcript})
        try:
            store = await get_store()
            await store.save_case(record)
            stored = type(store).__name__.replace("DataStore", "").lower()
        except Exception as exc:
            log.exception("post-call logging failed")
            stored = f"error: {exc}"
        self.set_stage("ENDED")
        self.publish("call.ended", {"duration_s": duration, "disposition": disposition, "reason": reason})
        self.publish("case.logged", {"case_id": record["case_id"], "store": stored, "disposition": disposition})
        sessions.pop(self.call_id, None)
        return record


def _statements(text: str) -> str:
    """Keep only declarative sentences (drop trailing questions)."""
    return " ".join(x for x in re.split(r"(?<=[.!?])\s+", text or "") if x and not x.endswith("?"))


sessions: dict[str, CallSession] = {}


def create_session(call_id: str, channel: str, caller_number: str | None, scenario: str | None = None) -> CallSession:
    s = CallSession(call_id, channel, caller_number, scenario)
    sessions[call_id] = s
    return s
