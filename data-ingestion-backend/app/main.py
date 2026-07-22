"""Stage 0 전처리 적재 백엔드 FastAPI 앱 진입점(작업계획서.md §6)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db.session import get_engine
from app.ingestion.loaders import recover_interrupted_runs
from app.middleware import RateLimitMiddleware, RequestLoggingMiddleware
from app.routers import runs, tables, upload

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작 훅. 이전 프로세스가 QUEUED/RUNNING으로 남긴 run은 BackgroundTasks가
    프로세스 메모리 상태라 재시작하면 진행 정보가 유실된다 — FAILED(INTERRUPTED)로
    정리해 영구 고착·삭제 불가 상태를 막는다(리뷰 2026-07-22 B-3)."""
    engine = get_engine()
    recovered = recover_interrupted_runs(engine)
    if recovered:
        logger.warning("기동 시 중단된 run %d건을 FAILED(INTERRUPTED)로 정리함: %s", len(recovered), recovered)
    yield


app = FastAPI(title="data-ingestion-backend", lifespan=lifespan)

app.add_middleware(RateLimitMiddleware, requests_per_minute=settings.rate_limit_per_minute)
app.add_middleware(RequestLoggingMiddleware)

_STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

app.include_router(upload.router)
app.include_router(runs.router)
app.include_router(tables.router)
