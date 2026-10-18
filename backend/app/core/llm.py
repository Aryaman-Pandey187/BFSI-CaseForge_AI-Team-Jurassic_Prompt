"""
Thin async wrapper around the Google Gen AI SDK (Vertex AI Gemini).

* ``LLM_MODE=vertex``     -> Vertex AI (ADC / Cloud Run service account)
* ``LLM_MODE=gemini_api`` -> Gemini Developer API with ``GEMINI_API_KEY``
* ``LLM_MODE=mock``       -> no network; agents use their deterministic paths

Features: model fallback chain, per-call timeout, a generic function-calling
loop that executes our Python tools, and JSON-mode generation. The raw model
``Content`` is appended to history unchanged so Gemini 3 thought signatures
are preserved across tool-calling turns.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Awaitable, Callable

from app.config import get_settings

log = logging.getLogger("caseforge.llm")

ToolFn = Callable[[str, dict], Awaitable[dict]]


class LLMUnavailable(RuntimeError):
    pass


class GeminiClient:
    def __init__(self) -> None:
        self.s = get_settings()
        self._client = None

    @property
    def enabled(self) -> bool:
        return self.s.llm_mode in {"vertex", "gemini_api"}

    def client(self):
        if self._client is None:
            from google import genai

            if self.s.llm_mode == "gemini_api":
                self._client = genai.Client(api_key=self.s.gemini_api_key)
            else:
                self._client = genai.Client(vertexai=True, project=self.s.gcp_project,
                                            location=self.s.gcp_location)
        return self._client

    @staticmethod
    def declarations(specs: list[dict]):
        """Convert our JSON-schema tool specs into a Gemini Tool."""
        from google.genai import types

        return types.Tool(function_declarations=[
            types.FunctionDeclaration(name=s["name"], description=s["description"],
                                      parameters_json_schema=s["parameters"]) for s in specs])

    async def _generate(self, contents, config):
        if not self.enabled:
            raise LLMUnavailable("LLM_MODE=mock")
        models = [self.s.gemini_model] + [m for m in self.s.gemini_fallback_models if m != self.s.gemini_model]
        last: Exception | None = None
        for model in models:
            try:
                return await asyncio.wait_for(
                    self.client().aio.models.generate_content(model=model, contents=contents, config=config),
                    timeout=self.s.llm_timeout_s)
            except Exception as exc:  # try the next model in the chain
                last = exc
                log.warning("Gemini call failed on %s: %s", model, exc)
        raise LLMUnavailable(str(last))

    async def tool_loop(self, *, system: str, history: list, tools: list[dict], execute: ToolFn,
                        max_rounds: int = 5, force_tool: bool = False, temperature: float = 0.3) -> str:
        """
        Run a Gemini function-calling loop.

        ``history`` is a list of ``types.Content`` and is mutated in place so a
        multi-turn conversation can continue across calls. Returns the final
        text answer.
        """
        from google.genai import types

        tool = self.declarations(tools) if tools else None
        for round_ in range(max_rounds):
            mode = "ANY" if (force_tool and round_ == 0) else "AUTO"
            cfg = types.GenerateContentConfig(
                system_instruction=system, temperature=temperature,
                tools=[tool] if tool else None,
                tool_config=types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode=mode))
                if tool else None,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            )
            resp = await self._generate(history, cfg)
            cand = resp.candidates[0] if resp.candidates else None
            if cand is None or cand.content is None:
                return ""
            history.append(cand.content)  # keep thought signatures intact
            calls = [p.function_call for p in (cand.content.parts or []) if p.function_call]
            if not calls:
                return (resp.text or "").strip()
            results = await asyncio.gather(*[execute(c.name, dict(c.args or {})) for c in calls])
            history.append(types.Content(role="user", parts=[
                types.Part.from_function_response(name=c.name, response={"result": r})
                for c, r in zip(calls, results)]))
        return ""

    async def json(self, *, system: str, prompt: str, schema: dict | None = None,
                   temperature: float = 0.2) -> dict:
        """Single-shot JSON generation (structured output)."""
        from google.genai import types

        cfg = types.GenerateContentConfig(system_instruction=system, temperature=temperature,
                                          response_mime_type="application/json",
                                          response_json_schema=schema)
        resp = await self._generate([types.Content(role="user", parts=[types.Part(text=prompt)])], cfg)
        return parse_json(resp.text or "{}")

    async def text(self, *, system: str, history: list, temperature: float = 0.5) -> str:
        from google.genai import types

        cfg = types.GenerateContentConfig(system_instruction=system, temperature=temperature)
        resp = await self._generate(history, cfg)
        if resp.candidates and resp.candidates[0].content:
            history.append(resp.candidates[0].content)
        return (resp.text or "").strip()


def parse_json(text: str) -> dict:
    """Tolerant JSON parse (strips ``` fences / leading prose)."""
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        text = m.group(0)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def user_content(text: str):
    from google.genai import types

    return types.Content(role="user", parts=[types.Part(text=text)])


llm = GeminiClient()
