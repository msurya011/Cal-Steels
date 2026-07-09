"""Core configuration for CalSteel Estimator backend."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Supabase ──────────────────────────────────────────────────────────────
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""

    # ── Storage ───────────────────────────────────────────────────────────────
    storage_backend: str = "local"  # "local" | "r2"
    storage_local_dir: str = ""     # defaults to backend/uploads
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = "calsteel-drawings"
    r2_public_url: str = ""

    # ── API ───────────────────────────────────────────────────────────────────
    allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    max_pdf_size_mb: int = 500
    environment: str = "development"

    # ── Feature flags ─────────────────────────────────────────────────────────
    brace_extraction: str = "1"    # "1" = enabled, "0" = disabled

    # ── External tools ────────────────────────────────────────────────────────
    poppler_path: str = ""
    gemini_api_key: str = ""

    # ── Job queue ─────────────────────────────────────────────────────────────
    redis_url: str = ""   # if empty, asyncio background tasks are used

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def upload_dir(self) -> str:
        if self.storage_local_dir:
            return self.storage_local_dir
        # default: backend/uploads
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "uploads",
        )

    @property
    def brace_extraction_enabled(self) -> bool:
        return self.brace_extraction.strip() == "1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
