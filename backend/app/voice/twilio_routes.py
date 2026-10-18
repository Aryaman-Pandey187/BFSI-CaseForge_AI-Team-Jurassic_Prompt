"""
Twilio telephony endpoints.

Two voice loops, selected with ``VOICE_MODE``:

1. ``media_stream`` (primary, lowest latency, supports barge-in)
   POST /twilio/voice  -> TwiML <Connect><Stream url="wss://.../twilio/media-stream">
   WS   /twilio/media-stream: caller μ-law audio -> Cloud STT (streaming)
        -> CallSession (Gemini agents) -> Cloud TTS μ-law -> back to the caller.

2. ``gather`` (fallback, simplest, very robust)
   POST /twilio/voice -> <Gather input="speech"> with the greeting
   POST /twilio/gather -> Twilio's own STT result -> CallSession -> TwiML reply
   Replies are spoken with Cloud TTS (<Play> of /tts/<key>.mp3) when
   ``TTS_MODE=cloud`` or Twilio <Say> when ``TTS_MODE=twilio``.

Both loops share the same CallSession, so the agent desktop looks identical.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from twilio.twiml.voice_response import Connect, Gather, VoiceResponse

from app.config import get_settings
from app.core.session import CallSession, TurnResult, create_session, sessions
from app.voice.stt import StreamingRecognizer
from app.voice.tts import tts_service

log = logging.getLogger("caseforge.twilio")
router = APIRouter(prefix="/twilio", tags=["twilio"])
tts_router = APIRouter(tags=["tts"])

HINTS = ["Aarav Mehta", "Priya Nair", "Rohan Gupta", "Sneha Iyer", "Vikram Singh", "Ananya Das", "Karthik Reddy",
         "Meera Kapoor", "customer ID", "credit card", "debit card", "EMI", "cheque book", "lakh", "Romania", "ATM"]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def twiml(resp: VoiceResponse) -> Response:
    return Response(content=str(resp), media_type="application/xml")


def url(path: str, **params) -> str:
    base = get_settings().public_base_url
    return f"{base}{path}" + (f"?{urlencode(params)}" if params else "")


async def validate(request: Request) -> dict:
    """Parse the form and (optionally) verify X-Twilio-Signature."""
    form = dict(await request.form())
    s = get_settings()
    if s.validate_twilio_signature and s.twilio_auth_token:
        from twilio.request_validator import RequestValidator

        full = s.public_base_url + request.url.path + (f"?{request.url.query}" if request.url.query else "")
        if not RequestValidator(s.twilio_auth_token).validate(full, form, request.headers.get("X-Twilio-Signature", "")):
            raise HTTPException(status_code=403, detail="invalid Twilio signature")
    return form


async def speak_into(node, text: str):
    """Add speech to a TwiML node (VoiceResponse or Gather)."""
    s = get_settings()
    if s.tts_mode == "cloud":
        try:
            key = await tts_service.synthesize_mp3(text)
            node.play(url(f"/tts/{key}.mp3"))
            return
        except Exception as exc:
            log.warning("Cloud TTS failed, falling back to <Say>: %s", exc)
    node.say(text, voice=s.twilio_say_voice, language=s.tts_language)


def gather_node(call_id: str) -> Gather:
    s = get_settings()
    kw = dict(input="speech", action=url("/twilio/gather", call_id=call_id), method="POST", speech_timeout="auto",
              language=s.stt_language, action_on_empty_result=True, hints=", ".join(HINTS), timeout=6)
    import os

    if os.getenv("TWILIO_SPEECH_MODEL"):
        kw["speech_model"] = os.getenv("TWILIO_SPEECH_MODEL")
    return Gather(**kw)


async def turn_twiml(session: CallSession, res: TurnResult) -> VoiceResponse:
    s = get_settings()
    vr = VoiceResponse()
    if res.action == "hold":
        await speak_into(vr, res.say)
        vr.redirect(url("/twilio/hold", call_id=session.call_id, n=0), method="POST")
    elif res.action == "end":
        await speak_into(vr, res.say)
        vr.hangup()
    elif res.action == "handoff" and s.handoff_number:
        await speak_into(vr, res.say)
        vr.dial(s.handoff_number)
    else:  # continue the conversation (incl. AI-held handoff when no human number is configured)
        g = gather_node(session.call_id)
        await speak_into(g, res.say)
        vr.append(g)
        vr.redirect(url("/twilio/gather", call_id=session.call_id, empty=1), method="POST")
    return vr


# ---------------------------------------------------------------------------
# Inbound call webhook (configure this URL on your Twilio number)
# ---------------------------------------------------------------------------

@router.post("/voice")
async def incoming_call(request: Request):
    form = await validate(request)
    s = get_settings()
    call_id = form.get("CallSid") or f"CA{uuid.uuid4().hex}"
    caller = form.get("From")
    session = sessions.get(call_id) or create_session(call_id, "phone", caller)
    log.info("Incoming call %s from %s (mode=%s)", call_id, caller, s.voice_mode)
    vr = VoiceResponse()
    if s.voice_mode == "media_stream":
        ws_url = s.public_base_url.replace("https://", "wss://").replace("http://", "ws://") + "/twilio/media-stream"
        connect = Connect()
        stream = connect.stream(url=ws_url, track="inbound_track")
        stream.parameter(name="call_id", value=call_id)
        stream.parameter(name="caller", value=caller or "")
        vr.append(connect)
        # Reached only when our websocket closes: decide between Dial and Hangup.
        vr.redirect(url("/twilio/after-stream", call_id=call_id), method="POST")
        return twiml(vr)
    res = await session.greet()
    return twiml(await turn_twiml(session, res))


@router.post("/gather")
async def gather(request: Request, call_id: str, empty: int = 0):
    form = await validate(request)
    session = sessions.get(call_id)
    if not session:
        vr = VoiceResponse()
        vr.say("Sorry, this call has expired. Please call again.")
        vr.hangup()
        return twiml(vr)
    speech = (form.get("SpeechResult") or "").strip()
    if not speech:
        session.__dict__["_silence"] = session.__dict__.get("_silence", 0) + 1
        if session.__dict__["_silence"] >= 3:
            res = session._say("I haven't heard anything, so I'll end the call now. Please call back anytime. Goodbye!", "end")
            asyncio.create_task(session.end("silence"))
        else:
            res = session._say("Sorry, I didn't catch that. Could you please repeat?", "continue")
        return twiml(await turn_twiml(session, res))
    session.__dict__["_silence"] = 0
    res = await session.handle(speech)
    if res.action == "end":
        asyncio.create_task(session.end("caller_goodbye"))
    return twiml(await turn_twiml(session, res))


@router.post("/hold")
async def hold(request: Request, call_id: str, n: int = 0):
    await validate(request)
    session = sessions.get(call_id)
    vr = VoiceResponse()
    if not session:
        vr.hangup()
        return twiml(vr)
    if session.task and not session.task.done() and n < 20:
        vr.pause(length=1)
        if n == 6:
            await speak_into(vr, "Thanks for holding, nearly there.")
        vr.redirect(url("/twilio/hold", call_id=call_id, n=n + 1), method="POST")
        return twiml(vr)
    res = await session.after_hold(timeout=5)
    return twiml(await turn_twiml(session, res))


@router.post("/after-stream")
async def after_stream(request: Request, call_id: str):
    await validate(request)
    s = get_settings()
    session = sessions.get(call_id)
    vr = VoiceResponse()
    if session and session.stage == "HANDOFF" and s.handoff_number:
        vr.dial(s.handoff_number)
    else:
        vr.hangup()
    return twiml(vr)


@router.post("/status")
async def status_callback(request: Request):
    """Twilio call status callback - triggers post-call case logging."""
    form = await validate(request)
    call_id, status = form.get("CallSid"), form.get("CallStatus")
    if status in {"completed", "busy", "failed", "no-answer", "canceled"} and call_id in sessions:
        await sessions[call_id].end(f"twilio_{status}")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Media Streams websocket
# ---------------------------------------------------------------------------

class MediaStreamCall:
    CHUNK = 160 * 25  # 0.5 s of 8 kHz μ-law per media message

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.stream_sid: str | None = None
        self.session: CallSession | None = None
        self.stt: StreamingRecognizer | None = None
        self.turns: asyncio.Queue[str] = asyncio.Queue()
        self.playing: str | None = None
        self.played = asyncio.Event()
        self.worker: asyncio.Task | None = None
        self.closing = False

    async def send(self, msg: dict):
        try:
            await self.ws.send_text(json.dumps(msg))
        except Exception:
            pass

    async def speak(self, text: str):
        if not text or self.closing:
            return
        self.session.voice_state("speaking")
        audio = await tts_service.synthesize_mulaw(text)
        for i in range(0, len(audio), self.CHUNK):
            await self.send({"event": "media", "streamSid": self.stream_sid,
                             "media": {"payload": base64.b64encode(audio[i:i + self.CHUNK]).decode()}})
        mark = f"m-{uuid.uuid4().hex[:6]}"
        self.playing = mark
        self.played.clear()
        await self.send({"event": "mark", "streamSid": self.stream_sid, "mark": {"name": mark}})
        self._audio_s = len(audio) / 8000

    async def wait_played(self):
        try:
            await asyncio.wait_for(self.played.wait(), timeout=getattr(self, "_audio_s", 5) + 3)
        except asyncio.TimeoutError:
            pass

    async def on_text(self, text: str, final: bool):
        if not final:
            self.session.add_line("caller", text, interim=True)
            if self.playing and len(text.split()) >= 2:  # barge-in: stop the bot talking
                await self.send({"event": "clear", "streamSid": self.stream_sid})
                self.playing = None
                self.played.set()
            return
        await self.turns.put(text)

    async def turn_worker(self):
        while not self.closing:
            text = await self.turns.get()
            # merge quick consecutive finals ("my name is" + "Aarav Mehta")
            await asyncio.sleep(0.25)
            while not self.turns.empty():
                text += " " + self.turns.get_nowait()
            res = await self.session.handle(text)
            await self.speak(res.say)
            while res.action == "hold":
                res = await self.session.after_hold()
                await self.speak(res.say)
            if res.action == "end" or (res.action == "handoff" and get_settings().handoff_number):
                await self.wait_played()
                await self.hangup_stream()
                return
            self.session.voice_state("listening")

    async def hangup_stream(self):
        """Closing the socket makes Twilio continue to /twilio/after-stream (Dial or Hangup)."""
        self.closing = True
        try:
            await self.ws.close()
        except Exception:
            pass

    async def run(self):
        await self.ws.accept()
        try:
            while True:
                msg = json.loads(await self.ws.receive_text())
                ev = msg.get("event")
                if ev == "start":
                    st = msg["start"]
                    self.stream_sid = st["streamSid"]
                    params = st.get("customParameters", {})
                    call_id = params.get("call_id") or st.get("callSid")
                    self.session = sessions.get(call_id) or create_session(call_id, "phone", params.get("caller"))
                    self.stt = StreamingRecognizer(self.on_text, HINTS)
                    self.stt.start()
                    self.worker = asyncio.create_task(self.turn_worker())
                    g = await self.session.greet()
                    await self.speak(g.say)
                elif ev == "media" and self.stt:
                    self.stt.feed(base64.b64decode(msg["media"]["payload"]))
                elif ev == "mark":
                    if msg.get("mark", {}).get("name") == self.playing:
                        self.playing = None
                        self.played.set()
                        if self.session:
                            self.session.voice_state("listening")
                elif ev == "stop":
                    break
        except WebSocketDisconnect:
            pass
        except Exception:
            log.exception("media stream error")
        finally:
            self.closing = True
            if self.stt:
                await self.stt.close()
            if self.worker:
                self.worker.cancel()
            if self.session and not (self.session.stage == "HANDOFF" and get_settings().handoff_number):
                await self.session.end("stream_closed")


@router.websocket("/media-stream")
async def media_stream(ws: WebSocket):
    await MediaStreamCall(ws).run()


@tts_router.get("/tts/{key}.mp3")
async def tts_audio(key: str):
    data = tts_service.cached(key)
    if data is None:
        raise HTTPException(404)
    return Response(content=data, media_type="audio/mpeg", headers={"Cache-Control": "public, max-age=3600"})
