"""Stage 0 전처리 적재 백엔드 FastAPI 앱 진입점(작업계획서.md §6)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routers import runs, upload

app = FastAPI(title="data-ingestion-backend")

_STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

app.include_router(upload.router)
app.include_router(runs.router)
