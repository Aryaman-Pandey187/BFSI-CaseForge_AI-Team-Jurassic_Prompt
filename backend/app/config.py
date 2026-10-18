"""
Central configuration.

Every setting comes from environment variables (optionally loaded from a
`.env` file). Any value can be a Secret Manager reference of the form
``sm://<secret-id>`` or ``sm://<secret-id>/<version>``; it is resolved at
start-up using the Cloud Run service account. On Cloud Run you can also mount
secrets directly as env vars with ``--set-secrets`` (the deploy script does).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

log = logging.getLogger("caseforge.config")

# Load backend/.env first, then repo-root .env (first one wins per variable).
_BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(_BACKEND_DIR / ".env")
load_dotenv(_BACKEND_DIR.parent / ".env")


def _resolve_secret(value: str | None, project: str | None) -> str | None:
    """Resolve ``sm://name[/version]`` references through Secret Manager."""
    if not value or not value.startswith("sm://"):
        return value
    ref = value[len("sm://"):]
    name, _, version = ref.partition("/")
    version = version or "latest"
    try:
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        path = name if name.startswith("projects/") else (
            f"projects/{project}/secrets/{name}/versions/{version}"
        )
        resp = client.access_secret_version(name=path)
        return resp.payload.data.decode("utf-8").strip()
    except Exception as exc:  # pragma: no cover - only hit with GCP creds
        log.error("Could not resolve secret %s: %s", value, exc)
        return None


def _env(name: str, default: str | None = None) -> str | None:
    return os.getenv(name, default)


def _bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    # --- General -----------------------------------------------------------
    app_name: str = "CaseForge AI"
    env: str = "local"
    log_level: str = "INFO"
    public_base_url: str = "http://localhost:8080"  # used to build Twilio URLs
    cors_origins: list[str] = field(default_factory=lambda: ["*"])
    static_dir: str | None = None  # built frontend served by FastAPI if set

    # --- Google Cloud ------------------------------------------------------
    gcp_project: str | None = None
    gcp_location: str = "global"

    # --- LLM ---------------------------------------------------------------
    llm_mode: str = "mock"  # "vertex" | "gemini_api" | "mock"
    gemini_model: str = "gemini-3.5-flash"
    gemini_fallback_models: list[str] = field(default_factory=list)
    gemini_api_key: str | None = None
    llm_timeout_s: float = 20.0

    # --- Data --------------------------------------------------------------
    data_backend: str = "memory"  # "firestore" | "memory"
    firestore_database: str = "(default)"
    auto_seed: bool = True
    time_shift_data: bool = True  # shift seed dates so "today" == anchor date

    # --- Voice -------------------------------------------------------------
    voice_mode: str = "media_stream"  # "media_stream" | "gather"
    tts_mode: str = "cloud"  # "cloud" (Cloud TTS) | "twilio" (<Say>)
    tts_voice: str = "en-IN-Neural2-A"
    tts_language: str = "en-IN"
    tts_speaking_rate: float = 1.05
    twilio_say_voice: str = "Polly.Aditi"
    stt_language: str = "en-IN"
    stt_model: str = "telephony"
    bank_name: str = "Horizon Bank"
    agent_persona: str = "Maya"

    # --- Twilio ------------------------------------------------------------
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    validate_twilio_signature: bool = False
    handoff_number: str | None = None  # optional E.164 number to <Dial> at handoff

    # --- Demo knobs --------------------------------------------------------
    demo_trusted_caller_numbers: list[str] = field(default_factory=list)
    simulator_turn_delay_s: float = 1.6

    @property
    def is_mock_llm(self) -> bool:
        return self.llm_mode == "mock"


def _list(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [x.strip() for x in raw.split(",") if x.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    project = _env("GOOGLE_CLOUD_PROJECT") or _env("GCP_PROJECT")
    s = Settings(
        env=_env("APP_ENV", "local"),
        log_level=_env("LOG_LEVEL", "INFO"),
        public_base_url=(_env("PUBLIC_BASE_URL", "http://localhost:8080") or "").rstrip("/"),
        cors_origins=_list("CORS_ORIGINS") or ["*"],
        static_dir=_env("STATIC_DIR"),
        gcp_project=project,
        gcp_location=_env("GOOGLE_CLOUD_LOCATION", "global"),
        llm_mode=_env("LLM_MODE", "mock"),
        gemini_model=_env("GEMINI_MODEL", "gemini-3.5-flash"),
        gemini_fallback_models=_list("GEMINI_FALLBACK_MODELS") or ["gemini-3.1-flash-lite"],
        gemini_api_key=_resolve_secret(_env("GEMINI_API_KEY"), project),
        llm_timeout_s=float(_env("LLM_TIMEOUT_S", "20")),
        data_backend=_env("DATA_BACKEND", "memory"),
        firestore_database=_env("FIRESTORE_DATABASE", "(default)"),
        auto_seed=_bool("AUTO_SEED", True),
        time_shift_data=_bool("TIME_SHIFT_DATA", True),
        voice_mode=_env("VOICE_MODE", "media_stream"),
        tts_mode=_env("TTS_MODE", "cloud"),
        tts_voice=_env("TTS_VOICE", "en-IN-Neural2-A"),
        tts_language=_env("TTS_LANGUAGE", "en-IN"),
        tts_speaking_rate=float(_env("TTS_SPEAKING_RATE", "1.05")),
        twilio_say_voice=_env("TWILIO_SAY_VOICE", "Polly.Aditi"),
        stt_language=_env("STT_LANGUAGE", "en-IN"),
        stt_model=_env("STT_MODEL", "telephony"),
        bank_name=_env("BANK_NAME", "Horizon Bank"),
        agent_persona=_env("AGENT_PERSONA", "Maya"),
        twilio_account_sid=_resolve_secret(_env("TWILIO_ACCOUNT_SID"), project),
        twilio_auth_token=_resolve_secret(_env("TWILIO_AUTH_TOKEN"), project),
        validate_twilio_signature=_bool("VALIDATE_TWILIO_SIGNATURE", False),
        handoff_number=_env("HANDOFF_NUMBER") or None,
        demo_trusted_caller_numbers=_list("DEMO_TRUSTED_CALLER_NUMBERS"),
        simulator_turn_delay_s=float(_env("SIMULATOR_TURN_DELAY_S", "1.6")),
    )
    return s
