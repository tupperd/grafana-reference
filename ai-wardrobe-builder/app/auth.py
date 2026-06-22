"""Intentionally minimal auth: one user from .env, cookie session via Starlette."""
from fastapi import HTTPException, Request

from . import config


def check_credentials(username: str, password: str) -> bool:
    return username == config.APP_USERNAME and password == config.APP_PASSWORD


def require_user(request: Request) -> str:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
