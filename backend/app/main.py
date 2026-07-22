"""FastAPI 앱 진입점 (docs/05 §1). 라우터 등록·CORS·요청량 제한·공통 에러 처리."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.envelope import error_envelope
from app.middleware import RateLimitMiddleware, RequestLoggingMiddleware
from app.routers import reference, routes

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="flight-route-advisor API")

app.add_middleware(RateLimitMiddleware, requests_per_minute=settings.rate_limit_per_minute)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_allowed_origins),
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    # 라우터는 HTTPException(status_code=.., detail=..)만 던지고, 여기서 표준 봉투
    # {error:{code,message}}(docs/03 §7)로 일괄 재포장한다 — FastAPI 기본값인
    # {"detail": ...}이 그대로 나가지 않도록.
    return JSONResponse(
        status_code=exc.status_code,
        content=error_envelope(exc.status_code, str(exc.detail)),
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Query(ge=/le=/min_length= 등) 위반 시 FastAPI가 자동으로 던지는 422도 같은
    # 표준 봉투로 통일한다.
    message = "; ".join(
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors()
    )
    return JSONResponse(status_code=422, content=error_envelope(422, message))


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # 내부 구현/스택 비노출(docs/06-conventions.md §8) — 상세는 서버 로그에만 남긴다.
    logging.getLogger("app.error").exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content=error_envelope(500, "internal server error"))


app.include_router(reference.router)
app.include_router(routes.router)
