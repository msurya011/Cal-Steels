"""JWT verification and current-user extraction for CalSteel Estimator."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import create_client

from app.core.config import get_settings

logger = logging.getLogger(__name__)
_bearer = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    id: str           # Supabase auth.users UUID
    email: str
    company_id: Optional[str] = None
    role: str = "estimator"


def _get_supabase_admin():
    """Admin client with service-role key (server-side only)."""
    cfg = get_settings()
    if not cfg.supabase_url or not cfg.supabase_service_role_key:
        return None
    try:
        return create_client(cfg.supabase_url, cfg.supabase_service_role_key)
    except Exception as exc:
        logger.warning("Supabase admin client unavailable: %s", exc)
        return None


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = None,
) -> CurrentUser:
    """
    FastAPI dependency — verifies the Supabase JWT in Authorization: Bearer.
    Returns a CurrentUser with id, email, company_id, and role.
    Raises HTTP 401 if the token is missing or invalid.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    cfg = get_settings()

    if (
        not cfg.supabase_url
        or "cfsrdgoapoziffjesllw" in cfg.supabase_url
        or "your_supabase_project_url" in cfg.supabase_url
        or not cfg.supabase_anon_key
        or cfg.supabase_anon_key == "your_supabase_anon_key"
    ):
        # Dev fallback: if Supabase is not configured, accept any token and
        # return a dummy user. HARD-DISABLED outside development.
        if cfg.environment.lower() not in ("development", "dev", "local"):
            logger.error("Supabase not configured and ENVIRONMENT=%s — refusing dev fallback auth", cfg.environment)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication backend not configured",
            )
        logger.warning("Supabase not configured or using default/placeholder URL — using dev fallback user")
        return CurrentUser(id="00000000-0000-0000-0000-000000000000", email="dev@calsteel.local")

    try:
        # Use Supabase anon client to verify the user token
        anon_client = create_client(cfg.supabase_url, cfg.supabase_anon_key)
        response = anon_client.auth.get_user(token)

        if not response or not response.user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        user = response.user

        # Fetch company_id and role from the public.users table
        admin = _get_supabase_admin()
        company_id: Optional[str] = None
        role = "estimator"

        if admin:
            try:
                row = (
                    admin.table("users")
                    .select("company_id, role")
                    .eq("id", user.id)
                    .maybe_single()
                    .execute()
                )
                if row and row.data:
                    company_id = row.data.get("company_id")
                    role = row.data.get("role", "estimator")
            except Exception as exc:
                logger.warning("Could not fetch user profile: %s", exc)

        return CurrentUser(
            id=user.id,
            email=user.email or "",
            company_id=company_id,
            role=role,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Auth error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
            headers={"WWW-Authenticate": "Bearer"},
        )
