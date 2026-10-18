"""
Streaming Speech-to-Text for Twilio Media Streams.

Twilio sends 8 kHz μ-law audio in 20 ms frames. We pipe those straight into
Cloud Speech-to-Text ``streaming_recognize`` (encoding MULAW, model
``telephony``) and surface interim + final transcripts through callbacks.

Cloud STT streams are limited to ~5 minutes, so the recogniser transparently
restarts a new stream every ``RESTART_S`` seconds (and after errors) while
the call is live.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

from app.config import get_settings

log = logging.getLogger("caseforge.stt")
OnText = Callable[[str, bool], Awaitable[None]]  # (text, is_final)

RESTART_S = 280


class StreamingRecognizer:
    def __init__(self, on_text: OnText, phrase_hints: list[str] | None = None):
        self.on_text = on_text
        self.queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.closed = False
        self.hints = phrase_hints or []
        self._task: asyncio.Task | None = None

    def start(self):
        self._task = asyncio.create_task(self._run())

    def feed(self, audio: bytes):
        if not self.closed:
            self.queue.put_nowait(audio)

    async def close(self):
        self.closed = True
        self.queue.put_nowait(None)
        if self._task:
            self._task.cancel()

    async def _run(self):
        from google.cloud import speech_v1 as speech

        s = get_settings()
        client = speech.SpeechAsyncClient()
        config = speech.StreamingRecognitionConfig(
            config=speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.MULAW, sample_rate_hertz=8000,
                language_code=s.stt_language, model=s.stt_model,  # "telephony" supports en-IN / en-US 8 kHz
                enable_automatic_punctuation=True,
                speech_contexts=[speech.SpeechContext(phrases=self.hints, boost=12)] if self.hints else []),
            interim_results=True, single_utterance=False)
        while not self.closed:
            started = time.monotonic()

            async def requests():
                yield speech.StreamingRecognizeRequest(streaming_config=config)
                while not self.closed and time.monotonic() - started < RESTART_S:
                    try:
                        chunk = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    if chunk is None:
                        return
                    yield speech.StreamingRecognizeRequest(audio_content=chunk)

            try:
                stream = await client.streaming_recognize(requests=requests())
                async for resp in stream:
                    for result in resp.results:
                        if not result.alternatives:
                            continue
                        text = result.alternatives[0].transcript.strip()
                        if text:
                            await self.on_text(text, bool(result.is_final))
            except asyncio.CancelledError:
                return
            except Exception as exc:
                if self.closed:
                    return
                log.warning("STT stream error, restarting: %s", exc)
                await asyncio.sleep(0.2)
