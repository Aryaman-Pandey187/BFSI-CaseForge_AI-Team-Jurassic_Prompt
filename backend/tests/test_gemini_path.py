"""
Exercise the Gemini code paths with a fake model (no network): function
declarations are valid google-genai objects, the tool loop executes our tools,
feeds results back and keeps the model's content (thought signatures) intact.
"""
import asyncio

from google.genai import types

from app.agents.intent import ROUTE_TOOL
from app.agents.tools import TOOL_SPECS, specs_for
from app.core.llm import GeminiClient


def test_declarations_build():
    tool = GeminiClient.declarations(specs_for(list(TOOL_SPECS)) + [ROUTE_TOOL])
    assert len(tool.function_declarations) == len(TOOL_SPECS) + 1


def test_tool_loop_and_identity_agent(monkeypatch):
    from app.agents.identity import IdentityAgent
    from app.agents.tools import CaseContext
    from app.core import llm as llm_mod

    calls = {"n": 0}

    async def fake_generate(self, contents, config):
        calls["n"] += 1
        assert config.tools and config.system_instruction
        if calls["n"] == 1:  # model decides to call the tool
            part = types.Part(function_call=types.FunctionCall(name="lookup_customer",
                                                               args={"name": "Aarav Mehta", "mobile_last4": "4821"}),
                              thought_signature=b"sig")
        else:  # model sees the tool result and answers
            last = contents[-1].parts[0].function_response.response["result"]
            assert last["verified"] is True and contents[-2].parts[0].thought_signature == b"sig"
            part = types.Part(text=f"Thank you {last['first_name']}, you're verified. How can I help?")
        return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=[part]))])

    monkeypatch.setattr(llm_mod.GeminiClient, "_generate", fake_generate)
    monkeypatch.setattr(llm_mod.llm.s, "llm_mode", "vertex")
    events = []
    ctx = CaseContext(call_id="T", caller_number="+919820114821", publish=lambda t, d: events.append(t))
    agent = IdentityAgent(ctx)
    reply = asyncio.run(agent.respond("Hi, I'm Aarav Mehta, last four 4821"))
    assert "Aarav" in reply and agent.verified and ctx.customer_id == "C1001"
    assert "identity.update" in events and calls["n"] == 2
