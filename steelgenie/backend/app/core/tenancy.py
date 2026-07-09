"""
Tenancy helpers — FastAPI dependencies that wire the current user
into every database call.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import CurrentUser, get_current_user

_bearer = HTTPBearer(auto_error=False)


async def _resolve_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer)
    ] = None,
) -> CurrentUser:
    return await get_current_user(credentials)


# Primary dependency — use in every protected router
AuthUser = Annotated[CurrentUser, Depends(_resolve_user)]


def require_role(*roles: str):
    """
    Returns a dependency that raises 403 if the current user's role is not in *roles*.

    Usage::

        @router.post("/admin-only")
        async def admin_endpoint(user: AuthUser, _: None = Depends(require_role("admin","manager"))):
            ...
    """
    async def _check(user: AuthUser):
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role}' does not have access. Required: {roles}",
            )

    return Depends(_check)
