import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api_common import limiter
from app.config import get_settings
from app.routers import admin, public

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="FinIntel API",
    version="0.1.0",
    description="Research and decision-support API. Forecasts are model estimates, not facts or advice; "
                "see /api/backtests for out-of-sample validation.")
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_list, allow_methods=["GET", "POST"],
                   allow_headers=["X-Admin-Token", "Content-Type"])


def _err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


@app.exception_handler(StarletteHTTPException)
async def http_exc(request: Request, exc: StarletteHTTPException):
    d = exc.detail
    if isinstance(d, dict) and "code" in d:
        return _err(exc.status_code, d["code"], d["message"])
    return _err(exc.status_code, "http_error", str(d))


@app.exception_handler(RequestValidationError)
async def validation_exc(request: Request, exc: RequestValidationError):
    msg = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
    return _err(422, "validation_error", msg)


@app.exception_handler(RateLimitExceeded)
async def rl_exc(request: Request, exc: RateLimitExceeded):
    return _err(429, "rate_limited", f"Rate limit exceeded: {exc.detail}")


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    logging.getLogger("app").exception("unhandled error on %s", request.url.path)
    return _err(500, "internal_error", "Internal server error")


app.include_router(public.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
