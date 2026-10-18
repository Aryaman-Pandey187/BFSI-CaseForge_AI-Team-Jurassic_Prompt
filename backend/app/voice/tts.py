"""
Text-to-Speech.

* ``synthesize_mulaw`` -> raw 8 kHz μ-law bytes for Twilio Media Streams.
* ``synthesize_mp3``   -> MP3 served at ``/tts/<key>.mp3`` for ``<Play>`` in Gather mode.

Uses Cloud Text-to-Speech (Neural2 / Chirp voices). Results are cached in
memory by (text, format) so repeated prompts are instant. If Cloud TTS is not
available (local mock mode) we return silence of a plausible length so the
media-stream code path still works end-to-end.
"""
from __future__ import annotations

import hashlib
import logging
import struct
from collections import OrderedDict

from app.config import get_settings

log = logging.getLogger("caseforge.tts")


class TTSService:
    def __init__(self) -> None:
        self._client = None
        self._cache: "OrderedDict[str, bytes]" = OrderedDict()

    def client(self):
        if self._client is None:
            from google.cloud import texttospeech

            self._client = texttospeech.TextToSpeechAsyncClient()
        return self._client

    @staticmethod
    def key(text: str, fmt: str) -> str:
        s = get_settings()
        return hashlib.sha1(f"{s.tts_voice}|{s.tts_speaking_rate}|{fmt}|{text}".encode()).hexdigest()[:20]

    def cached(self, key: str) -> bytes | None:
        return self._cache.get(key)

    def _put(self, key: str, data: bytes):
        self._cache[key] = data
        while len(self._cache) > 300:
            self._cache.popitem(last=False)

    async def _synth(self, text: str, encoding: str, rate: int | None) -> bytes:
        from google.cloud import texttospeech as tts

        s = get_settings()
        req = tts.SynthesizeSpeechRequest(
            input=tts.SynthesisInput(text=text),
            voice=tts.VoiceSelectionParams(language_code=s.tts_language, name=s.tts_voice),
            audio_config=tts.AudioConfig(audio_encoding=getattr(tts.AudioEncoding, encoding),
                                         sample_rate_hertz=rate or 0, speaking_rate=s.tts_speaking_rate,
                                         effects_profile_id=["telephony-class-application"]))
        resp = await self.client().synthesize_speech(request=req)
        return resp.audio_content

    async def synthesize_mulaw(self, text: str) -> bytes:
        k = self.key(text, "mulaw")
        if (hit := self.cached(k)) is not None:
            return hit
        try:
            audio = strip_wav_header(await self._synth(text, "MULAW", 8000))
        except Exception as exc:
            log.warning("Cloud TTS unavailable (%s) - sending silence", exc)
            audio = b"\xff" * int(8000 * min(8.0, 0.06 * len(text)))  # μ-law silence
        self._put(k, audio)
        return audio

    async def synthesize_mp3(self, text: str) -> str:
        """Synthesise + cache, return the cache key (served by /tts/{key}.mp3)."""
        k = self.key(text, "mp3")
        if k not in self._cache:
            self._put(k, await self._synth(text, "MP3", None))
        return k


def strip_wav_header(data: bytes) -> bytes:
    """Cloud TTS wraps LINEAR16/MULAW output in a RIFF header - Twilio wants raw frames."""
    if data[:4] != b"RIFF":
        return data
    i = 12
    while i + 8 <= len(data):
        cid, size = data[i:i + 4], struct.unpack("<I", data[i + 4:i + 8])[0]
        if cid == b"data":
            return data[i + 8:i + 8 + size]
        i += 8 + size
    return data[44:]


tts_service = TTSService()
