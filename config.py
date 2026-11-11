"""Configuration loaded from environment variables (a `.env` file is supported)."""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Telegram ---
    telegram_bot_token: str
    telegram_allowed_user_id: int

    # --- Notion ---
    notion_api_key: str
    notion_db_ids: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "JSON object mapping logical database name -> Notion database id. "
            "Keys: inbox, projects, areas, resources, tasks, ideas, media."
        ),
    )

    # --- LLM (OpenAI-compatible endpoint) ---
    # Shared fallback for any service that doesn't set its own override below.
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"

    # Chat (classification, summarization, Q&A, execution)
    chat_api_key: str = ""
    chat_base_url: str = ""
    chat_model: str = "gpt-4o-mini"

    # Vision (video key-frame description)
    vision_api_key: str = ""
    vision_base_url: str = ""
    vision_model: str = "gpt-4o"

    # Audio (transcription, API backend)
    audio_api_key: str = ""
    audio_base_url: str = ""
    audio_model: str = "whisper-1"

    # --- Transcription ---
    transcription_backend: Literal["api", "local"] = "api"
    whisper_local_model: str = "base"

    # --- Scheduling ---
    timezone: str = "UTC"
    digest_time: str = "07:00"  # HH:MM, 24h

    # --- Behaviour ---
    max_capture_questions: int = 3
    data_dir: str = "data"

    @field_validator("notion_db_ids", mode="before")
    @classmethod
    def _parse_notion_db_ids(cls, v: object) -> object:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return {}
            return json.loads(v)
        return v

    def db_id(self, name: str) -> str | None:
        return self.notion_db_ids.get(name)

    def require_db_id(self, name: str) -> str:
        db_id = self.db_id(name)
        if not db_id:
            raise RuntimeError(
                f"Notion database id for '{name}' is missing. "
                f"Add it to the NOTION_DB_IDS JSON in your .env."
            )
        return db_id

    # --- Per-service LLM credentials (each falls back to OPENAI_*) ---
    def chat_credentials(self) -> tuple[str, str]:
        key = self.chat_api_key or self.openai_api_key
        base = self.chat_base_url or self.openai_base_url
        if not key:
            raise RuntimeError("Missing chat API key: set OPENAI_API_KEY or CHAT_API_KEY.")
        return key, base

    def vision_credentials(self) -> tuple[str, str]:
        return (
            self.vision_api_key or self.openai_api_key,
            self.vision_base_url or self.openai_base_url,
        )

    def audio_credentials(self) -> tuple[str, str]:
        return (
            self.audio_api_key or self.openai_api_key,
            self.audio_base_url or self.openai_base_url,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
