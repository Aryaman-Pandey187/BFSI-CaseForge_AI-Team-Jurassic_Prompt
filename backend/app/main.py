"""
CaseForge AI - FastAPI entry point.

Routes
  /twilio/*            Twilio voice webhooks + Media Streams websocket
  /ws/desktop          real-time event stream for the agent desktop
  /api/simulate        run a scripted demo call (no phone needed)
  /api/text-call/*     interactive typed call (type as the caller)
  /api/cases           post-call case logs
  /api/customers       demo cheat-sheet (names + identifiers)
  /                    built React agent desktop (when STATIC_DIR is set)
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import __version__
from app.config import get_settings
from app.core.datastore import get_store
from app.core.events import hub
from app.core.session import create_session, sessions
from app.core.simulator import SCENARIOS, running, start_scenario
from app.voice.twilio_routes import router as twilio_router, tts_router

settings = get_settings()
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("caseforge")


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = await get_store()  # loads / seeds data on first run
    log.info("CaseForge AI %s ready | llm=%s model=%s | data=%s | voice=%s tts=%s | base=%s", __version__,
             settings.llm_mode, settings.gemini_model, type(store).__name__, settings.voice_mode,
             settings.tts_mode, settings.public_base_url)
    yield


app = FastAPI(title="CaseForge AI", version=__version__, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])
app.include_router(twilio_router)
app.include_router(tts_router)


def public_config() -> dict:
    return {"version": __version__, "llm_mode": settings.llm_mode, "model": settings.gemini_model,
            "data_backend": settings.data_backend, "voice_mode": settings.voice_mode, "tts_mode": settings.tts_mode,
            "bank_name": settings.bank_name, "persona": settings.agent_persona,
            "scenarios": [{"id": k, "title": v["title"], "customer": v["customer"]} for k, v in SCENARIOS.items()]}


@app.get("/healthz")
async def healthz():
    return {"ok": True, "active_calls": len(sessions)}


@app.get("/api/config")
async def config():
    return public_config()


@app.get("/api/calls")
async def calls():
    return [{"call_id": s.call_id, "channel": s.channel, "stage": s.stage, "caller": s.caller_number,
             "customer": s.customer["full_name"] if s.customer else None} for s in sessions.values()]


@app.get("/api/calls/{call_id}/events")
async def call_events(call_id: str):
    return hub.events_for(call_id)


@app.get("/api/cases")
async def cases(limit: int = 25):
    store = await get_store()
    return [{k: c.get(k) for k in ("case_id", "call_id", "created_at", "status", "priority", "queue", "route_label",
                                   "customer", "post_call")} | {"score": (c.get("risk") or {}).get("score"),
                                                                 "band": (c.get("risk") or {}).get("band"),
                                                                 "headline": (c.get("summary") or {}).get("headline")}
            for c in await store.list_cases(limit)]


@app.get("/api/cases/{case_id}")
async def case(case_id: str):
    store = await get_store()
    for c in await store.list_cases(200):
        if c["case_id"] == case_id:
            return c
    raise HTTPException(404)


@app.get("/api/customers")
async def customers():
    """Demo cheat-sheet: who you can pretend to be on the call."""
    store = await get_store()
    rows = await store._all("customers")
    return [{"customer_id": c["customer_id"], "full_name": c["full_name"], "mobile_last4": c["mobile_last4"],
             "city": c["city"], "risk_rating": c["risk_rating"], "segment": c["segment"]} for c in rows]


class SimRequest(BaseModel):
    scenario: str


@app.post("/api/simulate")
async def simulate(req: SimRequest):
    if req.scenario not in SCENARIOS:
        raise HTTPException(400, f"unknown scenario; choose from {list(SCENARIOS)}")
    return {"call_id": start_scenario(req.scenario), "scenario": req.scenario}


@app.post("/api/simulate/stop")
async def simulate_stop():
    for t in list(running.values()):
        t.cancel()
    for s in list(sessions.values()):
        if s.channel in {"simulator", "text"}:
            await s.end("stopped")
    return {"ok": True}


class TextCallStart(BaseModel):
    caller_number: str | None = None


class TextTurn(BaseModel):
    text: str


@app.post("/api/text-call")
async def text_call_start(req: TextCallStart):
    call_id = f"TXT-{uuid.uuid4().hex[:8].upper()}"
    s = create_session(call_id, "text", req.caller_number)
    g = await s.greet()
    return {"call_id": call_id, "replies": [g.say]}


@app.post("/api/text-call/{call_id}/say")
async def text_call_say(call_id: str, req: TextTurn):
    s = sessions.get(call_id)
    if not s:
        raise HTTPException(404, "call not active")
    res = await s.handle(req.text)
    replies = [res.say]
    while res.action == "hold":
        res = await s.after_hold()
        replies.append(res.say)
    if res.action == "end":
        asyncio.create_task(s.end("caller_goodbye"))
    return {"replies": replies, "action": res.action, "stage": s.stage}


@app.post("/api/text-call/{call_id}/end")
async def text_call_end(call_id: str):
    s = sessions.get(call_id)
    if s:
        await s.end("agent_ended")
    return {"ok": True}


@app.websocket("/ws/desktop")
async def desktop_ws(ws: WebSocket):
    await ws.accept()
    q = hub.subscribe()
    try:
        await ws.send_json({"type": "hello", "data": public_config()})
        await ws.send_json({"type": "replay", "data": hub.replay()})

        async def pump():
            while True:
                await ws.send_json(await q.get())

        async def drain():  # detect client disconnects / pings
            while True:
                await ws.receive_text()

        done, pending = await asyncio.wait([asyncio.create_task(pump()), asyncio.create_task(drain())],
                                           return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.unsubscribe(q)


# ---- serve the built frontend (single-container deploy) --------------------
_static = Path(settings.static_dir) if settings.static_dir else None
if _static and _static.exists():
    app.mount("/assets", StaticFiles(directory=_static / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        f = _static / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(_static / "index.html")
