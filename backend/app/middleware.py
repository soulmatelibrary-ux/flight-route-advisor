"""요청량 제한 + 관측성 미들웨어 (docs/06-conventions.md §8, docs/07-checklist.md 공통 게이트).

레이트리밋은 프로세스 내 메모리 카운터다 — 단일 인스턴스 로컬/MVP 배포 전제다.
여러 인스턴스로 수평 확장하면 인스턴스별로 따로 카운트되어 전체 한도가 느슨해지므로,
그 시점에는 공유 스토어(Redis 등) 기반으로 교체해야 한다(지금은 과설계 방지 차원에서
미룬다).

레이트리밋 대상은 "/api"(routers/*.py의 기존 prefix 관례와 동일) 이하 요청만이다(사용자
제보, 2026-07-24) — 원래는 main.py가 이 미들웨어를 앱 전체(정적 프론트 서빙 마운트
포함)에 걸어놔서, 페이지 새로고침 한 번(JS 모듈 파일 수십 개 + index.html)만으로도
API 남용 방지용으로 잡아둔 분당 한도를 정적 자산 요청만으로 소진해 실제 API 호출이나
후속 새로고침이 무고하게 429를 맞는 문제가 있었다. 정적 파일은 남용 여지가 없는
읽기 전용 자원이라 대상에서 뺀다.
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
        if not request.url.path.startswith("/api"):
            return await call_next(request)
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
                content=error_envelope(429, "요청이 너무 많음 — 잠시 후 다시 시도"),
            )
        self._hits[client_ip].append(now)
        return await call_next(request)


class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    """요청 본문 크기 상한 (C4 리뷰 지적, 2026-07-24 — `POST /api/reasoning/complete`가 이
    저장소 첫 본문 있는 엔드포인트라 새로 생긴 표면). `Content-Length` 헤더만으로 사전 거부해
    다운스트림(Pydantic 검증 등)이 거대한 본문을 실제로 읽어 메모리에 올리기 전에 막는다 —
    `Field(max_length=...)`는 이미 파싱된 문자열 길이만 제한할 뿐, 파싱 자체를 막지 않는다.

    ⚠ 알려진 한계: `Content-Length` 헤더가 없는 청크 전송(chunked transfer-encoding) 요청은
    이 검사를 우회한다(헤더 기반 사전 검사의 근본적 한계 — 본문을 읽어야 실제 크기를 알 수
    있음). 이 앱의 유일한 POST 소비자(브라우저 fetch/JSON.stringify)는 항상 Content-Length를
    보내므로 실질적 위험은 낮지만, 완전한 방어는 아니다."""

    def __init__(self, app, max_bytes: int) -> None:
        super().__init__(app)
        self._max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                length = int(content_length)
            except ValueError:
                length = None  # 형식이 이상하면 다운스트림이 알아서 처리하게 둠(여기선 판단 보류)
            if length is not None and length > self._max_bytes:
                return JSONResponse(
                    status_code=413,
                    content=error_envelope(413, f"요청 본문이 너무 큼(최대 {self._max_bytes:,}바이트)"),
                )
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
