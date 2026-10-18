"""
Call simulator - demo the entire flow with no phone, no GCP and no Twilio.

Each scenario is a scripted list of caller turns that is pushed through the
exact same :class:`CallSession` used for real phone calls, so the agent
desktop receives the identical event stream. The scripts double as the
"what to say on the call" demo script in the README.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from app.config import get_settings
from app.core.session import CallSession, create_session

log = logging.getLogger("caseforge.simulator")

SCENARIOS: dict[str, dict] = {
    "credit_card_fraud": {
        "title": "Credit card fraud (account takeover)",
        "customer": "Aarav Mehta · C1001 · mobile ••4821",
        "caller_number": "+919820114821",
        "turns": [
            "Hi, my name is Aarav Mehta.",
            "The last four digits are 4 8 2 1.",
            "I just got an SMS for a charge of about one lakh eighty four thousand rupees on my credit card at some "
            "electronics store in Romania. I've never been to Romania, I'm in Mumbai and the card is with me.",
            "Yes, please block it right away.",
            "Okay, thank you. Bye.",
        ],
    },
    "debit_card_fraud": {
        "title": "Debit card stolen · ATM cash-out",
        "customer": "Priya Nair · C1002",
        "caller_number": "+919845207310",
        "turns": [
            "Hello, this is Priya Nair, my customer ID is C1002.",
            "I can't find my debit card and I just woke up to SMS alerts for several ATM withdrawals last night, "
            "around fifty thousand rupees, and money was also transferred out of my savings account.",
            "Please freeze everything, I didn't do any of this.",
            "Thank you, that's all.",
        ],
    },
    "loan_hardship": {
        "title": "Home loan hardship (job loss)",
        "customer": "Rohan Gupta · C1003 · mobile ••5562",
        "caller_number": "+919811035562",
        "turns": [
            "Hi, Rohan Gupta here.",
            "Last four of my mobile are 5562.",
            "I lost my job in July and I've missed my home loan EMIs for the last two months. I want to know my "
            "options, can I get some relief or restructuring?",
            "Okay, I'll wait for the specialist. Thank you.",
        ],
    },
    "account_query": {
        "title": "Simple account query (AI-resolved)",
        "customer": "Sneha Iyer · C1004 · mobile ••9047",
        "caller_number": "+919884019047",
        "turns": [
            "Hi, I'm Sneha Iyer, mobile ending 9047.",
            "What's my current savings account balance? And has my cheque book been dispatched yet?",
            "No, that's all. Thanks!",
        ],
    },
}

running: dict[str, asyncio.Task] = {}


async def _pause(seconds: float):
    if seconds > 0:
        await asyncio.sleep(seconds)


async def _speak_pause(session: CallSession, text: str):
    """Approximate the time the bot would take to speak (keeps the demo readable)."""
    d = get_settings().simulator_turn_delay_s
    session.voice_state("speaking")
    await _pause(min(4.0, 0.035 * len(text)) * (d / 1.6) if d else 0)
    session.voice_state("listening")


async def run_scenario(name: str, call_id: str | None = None) -> CallSession:
    sc = SCENARIOS[name]
    call_id = call_id or f"SIM-{uuid.uuid4().hex[:8].upper()}"
    session = create_session(call_id, "simulator", sc["caller_number"], scenario=name)
    delay = get_settings().simulator_turn_delay_s
    await _pause(delay * 0.5)
    g = await session.greet()
    await _speak_pause(session, g.say)
    for turn in sc["turns"]:
        # show the caller "speaking" (interim transcript) before the final line
        words = turn.split()
        for i in range(3, len(words), max(3, len(words) // 3)):
            session.add_line("caller", " ".join(words[:i]) + "…", interim=True)
            await _pause(delay * 0.25)
        await _pause(delay * 0.4)
        res = await session.handle(turn)
        await _speak_pause(session, res.say)
        while res.action == "hold":
            res = await session.after_hold()
            await _speak_pause(session, res.say)
        if res.action == "end":
            break
        await _pause(delay)
    await _pause(delay * 0.5)
    await session.end("simulator_complete")
    return session


def start_scenario(name: str) -> str:
    call_id = f"SIM-{uuid.uuid4().hex[:8].upper()}"
    task = asyncio.create_task(run_scenario(name, call_id))
    running[call_id] = task
    task.add_done_callback(lambda t: running.pop(call_id, None))
    return call_id
