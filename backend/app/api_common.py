from __future__ import annotations

from datetime import date, timedelta

from fastapi import Header, HTTPException
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import get_settings
from app.forecasting.features import HORIZONS

limiter = Limiter(key_func=get_remote_address, default_limits=[get_settings().rate_limit])


class ApiError(HTTPException):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(status_code=status, detail={"code": code, "message": message})


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    """Admin/data-management endpoints are disabled unless ADMIN_TOKEN is configured."""
    import hmac
    tok = get_settings().admin_token
    if not tok:
        raise ApiError(403, "admin_disabled", "Admin endpoints are disabled: ADMIN_TOKEN is not configured.")
    if not x_admin_token or not hmac.compare_digest(x_admin_token, tok):
        raise ApiError(401, "unauthorized", "Missing or invalid X-Admin-Token.")


def horizon_label(h: int) -> str:
    return HORIZONS.get(h, f"{h} trading days")


def is_stale(last: date | None) -> bool:
    return last is None or (date.today() - last) > timedelta(days=get_settings().price_stale_days)
