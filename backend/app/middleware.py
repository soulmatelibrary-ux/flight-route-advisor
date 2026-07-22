"""요청량 제한 + 관측성 미들웨어 (docs/06-conventions.md §8, docs/07-checklist.md 공통 게이트).

레이트리밋은 프로세스 내 메모리 카운터다 — 단일 인스턴스 로컬/MVP 배포 전제다.
여러 인스턴스로 수평 확장하면 인스턴스별로 따로 카운트되어 전체 한도가 느슨해지므로,
그 시점에는 공유 스토어(Redis 등) 기반으로 교체해야 한다(지금은 과설계 방지 차원에서
미룬다).
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.envelope import error_envelope

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
        if len(hits) >= self._limit:
            return JSONResponse(
                status_code=429,
                content=error_envelope(429, "요청이 너무 많음 — 잠시 후 다시 시도"),
            )
        hits.append(now)
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
