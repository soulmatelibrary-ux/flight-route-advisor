"""FastAPI 앱 진입점 (docs/05 §1). 라우터 등록·CORS·요청량 제한·공통 에러 처리."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.db.session import get_engine
from app.envelope import error_envelope
from app.middleware import RateLimitMiddleware, RequestLoggingMiddleware
from app.routers import fois, flow_management, reference, routes

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작·종료 훅. DB 연결풀 리소스 정리(docs/06-conventions.md §8 defense-in-depth)."""
    yield
    # 앱 종료 시 cleanup
    engine = get_engine()
    if engine:
        engine.dispose()


app = FastAPI(title="flight-route-advisor API", lifespan=lifespan)

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
app.include_router(fois.router)
app.include_router(flow_management.router)

# 프론트(frontend/) 동일 오리진 서빙(완료검증 §D-4, 2026-07-22) — "/api/*"는 위 라우터가
# 먼저 매치되므로 이 마운트("/")는 그 외 경로(정적 파일·SPA index.html)만 담당한다.
# frontend_dir이 없으면(선택 기능) 조용히 건너뛴다 — backend 단독 기동(API 전용)도 계속
# 지원해야 하므로 필수 요건으로 만들지 않는다.
if settings.frontend_dir is not None:
    app.mount("/", StaticFiles(directory=str(settings.frontend_dir), html=True), name="frontend")
