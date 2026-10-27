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
    # Reasoning model. "auto" = NVIDIA Nemotron if a key is set, else Gemini if a key is set, else offline rules.
    provider: str = "auto"
    nvidia_api_key: str = ""
    nvidia_model: str = "nvidia/nemotron-3-super-120b-a12b"
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    tavily_api_key: str = ""
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
        if self.nvidia_api_key:
            return "nvidia"
        if self.gemini_api_key:
            return "gemini"
        return "offline"


def load_settings(env_file: str | os.PathLike | None = ".env") -> Settings:
    if load_dotenv and env_file and Path(env_file).exists():
        load_dotenv(env_file)
    env = os.environ.get
    provider = (env("PROVIDER") or "auto").strip().lower()
    if provider not in {"auto", "nvidia", "gemini", "offline"}:
        raise ValueError("PROVIDER must be auto, nvidia, gemini or offline")
    return Settings(
        db_path=Path(env("DB_PATH") or "checkam.db"),
        provider=provider,
        nvidia_api_key=env("NVIDIA_API_KEY") or "",
        nvidia_model=env("NVIDIA_MODEL") or Settings.nvidia_model,
        nvidia_base_url=env("NVIDIA_BASE_URL") or Settings.nvidia_base_url,
        gemini_api_key=env("GEMINI_API_KEY") or "",
        gemini_model=env("GEMINI_MODEL") or Settings.gemini_model,
        tavily_api_key=env("TAVILY_API_KEY") or "",
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
