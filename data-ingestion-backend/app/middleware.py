"""요청량 제한 + 관측성 미들웨어 (docs/06-conventions.md §8·조직 정책, 2026-07-22 리뷰 B-1).

레이트리밋은 프로세스 내 메모리 카운터다 — 단일 인스턴스 로컬/MVP 배포 전제다(backend/app와
동일한 트레이드오프, 그쪽 middleware.py 패턴 재사용). 여러 인스턴스로 수평 확장하면 공유
스토어(Redis 등) 기반으로 교체해야 한다.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger("app.request")


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int) -> None:
        super().__init__(app)
        self._limit = requests_per_minute
        self._window_seconds = 60.0
        self._hits: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        hits = self._hits[client_ip]
        cutoff = now - self._window_seconds
        while hits and hits[0] < cutoff:
            hits.pop(0)
        if not hits:
            del self._hits[client_ip]
        if len(hits) >= self._limit:
            return JSONResponse(
                status_code=429,
                content={"detail": "요청이 너무 많음 — 잠시 후 다시 시도"},
            )
        self._hits[client_ip].append(now)
        return await call_next(request)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.monotonic()
        response = await call_next(request)
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(
            "%s %s %d %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response
