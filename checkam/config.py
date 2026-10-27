"""Settings from environment variables (and a local .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:  # optional; plain environment variables also work
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


def _int(value: str | None, default: int) -> int:
    return int(value) if value and value.strip() else default


@dataclass
class Settings:
    db_path: Path = Path("checkam.db")
    # Reasoning model. "auto" = Meterless Nightshift if a runtime token is set, else NVIDIA's API, else Gemini, else offline rules.
    provider: str = "auto"
    # Meterless Nightshift: the local AI hotspot. It holds the NVIDIA key and serves Nemotron lanes over an OpenAI-style API.
    meterless_base_url: str = "http://127.0.0.1:8088/v1"
    meterless_runtime_token: str = ""
    meterless_model: str = ""  # empty = pick a Nemotron route from Nightshift's model list, else meterless/auto
    nvidia_api_key: str = ""
    nvidia_model: str = "nvidia/nemotron-3-ultra-550b-a55b"
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    tavily_api_key: str = ""
    # Zetaris, the data layer (local install). Empty key = sample mode from the bundled JSON files.
    zetaris_rest_url: str = "http://localhost:8888/api/v1.0"
    zetaris_api_key: str = ""
    zetaris_org_id: str = "1"
    safe_browsing_key: str = ""
    urlhaus_auth_key: str = ""
    # Chat platforms: each starts when its token is set.
    telegram_token: str = ""
    discord_token: str = ""
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = ""
    whatsapp_app_secret: str = ""
    whatsapp_graph_version: str = "v23.0"
    port: int = 8080
    # Limits
    user_limit: int = 10  # checks per user per window
    user_window_seconds: int = 600
    daily_cap: int = 500

    @property
    def reasoner(self) -> str:
        if self.provider != "auto":
            return self.provider
        if self.meterless_runtime_token:
            return "meterless"
        if self.nvidia_api_key:
            return "nvidia"
        if self.gemini_api_key:
            return "gemini"
        return "offline"


def meterless_url(url: str) -> str:
    """Nightshift URLs are pasted in many shapes; the runtime always lives at <host>/v1."""
    url = url.strip().rstrip("/")
    if "://" not in url:
        url = "http://" + url
    return url if url.endswith("/v1") else url.split("/v1")[0].rstrip("/") + "/v1"


def load_settings(env_file: str | os.PathLike | None = ".env") -> Settings:
    if load_dotenv and env_file and Path(env_file).exists():
        load_dotenv(env_file)
    env = os.environ.get
    provider = (env("PROVIDER") or "auto").strip().lower()
    if provider not in {"auto", "meterless", "nvidia", "gemini", "offline"}:
        raise ValueError("PROVIDER must be auto, meterless, nvidia, gemini or offline")
    return Settings(
        db_path=Path(env("DB_PATH") or "checkam.db"),
        provider=provider,
        meterless_base_url=meterless_url(env("METERLESS_BASE_URL") or Settings.meterless_base_url),
        meterless_runtime_token=env("METERLESS_RUNTIME_TOKEN") or "",
        meterless_model=env("METERLESS_MODEL") or "",
        nvidia_api_key=env("NVIDIA_API_KEY") or "",
        nvidia_model=env("NVIDIA_MODEL") or Settings.nvidia_model,
        nvidia_base_url=env("NVIDIA_BASE_URL") or Settings.nvidia_base_url,
        gemini_api_key=env("GEMINI_API_KEY") or "",
        gemini_model=env("GEMINI_MODEL") or Settings.gemini_model,
        tavily_api_key=env("TAVILY_API_KEY") or "",
        zetaris_rest_url=(env("ZETARIS_REST_URL") or Settings.zetaris_rest_url).rstrip("/"),
        zetaris_api_key=env("ZETARIS_API_KEY") or "",
        zetaris_org_id=env("ZETARIS_ORG_ID") or "1",
        safe_browsing_key=env("GOOGLE_SAFE_BROWSING_KEY") or "",
        urlhaus_auth_key=env("URLHAUS_AUTH_KEY") or "",
        telegram_token=env("TELEGRAM_BOT_TOKEN") or "",
        discord_token=env("DISCORD_BOT_TOKEN") or "",
        whatsapp_token=env("WHATSAPP_TOKEN") or "",
        whatsapp_phone_number_id=env("WHATSAPP_PHONE_NUMBER_ID") or "",
        whatsapp_verify_token=env("WHATSAPP_VERIFY_TOKEN") or "",
        whatsapp_app_secret=env("WHATSAPP_APP_SECRET") or "",
        whatsapp_graph_version=env("WHATSAPP_GRAPH_VERSION") or Settings.whatsapp_graph_version,
        port=_int(env("PORT"), 8080),
        user_limit=_int(env("USER_LIMIT"), 10),
        user_window_seconds=_int(env("USER_WINDOW_SECONDS"), 600),
        daily_cap=_int(env("DAILY_CAP"), 500),
    )
