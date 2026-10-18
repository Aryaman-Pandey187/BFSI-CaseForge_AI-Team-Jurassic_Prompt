"""Twilio webhook + Media Streams tests with fake STT/TTS (no network)."""
import base64
import json

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings


@pytest.fixture()
def client(monkeypatch):
    from app.main import app
    return TestClient(app)


def test_gather_mode_full_call(client, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "voice_mode", "gather")
    monkeypatch.setattr(s, "tts_mode", "twilio")
    sid = "CA_TEST_GATHER"
    r = client.post("/twilio/voice", data={"CallSid": sid, "From": "+919884019047"})
    assert r.status_code == 200 and "<Gather" in r.text and "Horizon Bank" in r.text
    r = client.post(f"/twilio/gather?call_id={sid}", data={"CallSid": sid, "SpeechResult": "Hi, I'm Sneha Iyer, mobile ending 9047."})
    assert "verified" in r.text
    r = client.post(f"/twilio/gather?call_id={sid}", data={"CallSid": sid, "SpeechResult": "What's my savings account balance?"})
    assert "<Redirect" in r.text and "/twilio/hold" in r.text  # hold loop while agents run
    for n in range(30):
        r = client.post(f"/twilio/hold?call_id={sid}&n={n}", data={"CallSid": sid})
        if "/twilio/hold" not in r.text:
            break
    assert "available balance" in r.text and "<Gather" in r.text
    r = client.post(f"/twilio/gather?call_id={sid}", data={"CallSid": sid, "SpeechResult": "No, that's all, thanks."})
    assert "<Hangup" in r.text


def test_media_stream_mode(client, monkeypatch):
    """Drive the Media Streams websocket: fake STT decodes 'TEXT:' payloads, fake TTS returns bytes."""
    import app.voice.twilio_routes as tr

    s = get_settings()
    monkeypatch.setattr(s, "voice_mode", "media_stream")

    class FakeSTT:
        def __init__(self, on_text, hints=None):
            self.on_text = on_text

        def start(self):
            pass

        def feed(self, audio: bytes):
            import asyncio
            if audio.startswith(b"TEXT:"):
                asyncio.get_event_loop().create_task(self.on_text(audio[5:].decode(), True))

        async def close(self):
            pass

    async def fake_mulaw(text):
        return b"\xff" * 800

    monkeypatch.setattr(tr, "StreamingRecognizer", FakeSTT)
    monkeypatch.setattr(tr.tts_service, "synthesize_mulaw", fake_mulaw)
    sid = "CA_TEST_STREAM"
    r = client.post("/twilio/voice", data={"CallSid": sid, "From": "+919820114821"})
    assert "<Connect>" in r.text and "media-stream" in r.text

    def say(ws, text):
        ws.send_text(json.dumps({"event": "media", "media": {"payload": base64.b64encode(b"TEXT:" + text.encode()).decode()}}))

    def drain_until_mark(ws):
        while True:
            m = json.loads(ws.receive_text())
            if m["event"] == "mark":
                ws.send_text(json.dumps({"event": "mark", "mark": m["mark"]}))  # playback finished
                return

    with client.websocket_connect("/twilio/media-stream") as ws:
        ws.send_text(json.dumps({"event": "connected"}))
        ws.send_text(json.dumps({"event": "start", "start": {"streamSid": "MZ1", "callSid": sid,
                                                              "customParameters": {"call_id": sid, "caller": "+919820114821"}}}))
        drain_until_mark(ws)  # greeting
        say(ws, "Hi, my name is Aarav Mehta.")
        drain_until_mark(ws)
        say(ws, "The last four digits are 4821.")
        drain_until_mark(ws)
        say(ws, "There is a one lakh eighty four thousand rupees charge on my credit card from Romania I never made.")
        drain_until_mark(ws)  # hold line
        drain_until_mark(ws)  # case-ready handoff message
        ws.send_text(json.dumps({"event": "stop"}))
    from app.core.events import hub
    types = [e["type"] for e in hub.events_for(sid)]
    assert "case.assembled" in types and "case.logged" in types
    case = next(e for e in hub.events_for(sid) if e["type"] == "case.assembled")["data"]
    assert case["risk"]["band"] == "CRITICAL"
