"""공통 응답 봉투 (docs/03-backend-api.md §2, §7)."""

from __future__ import annotations

from typing import Any


def envelope(
    data: Any,
    *,
    source: str,
    run_id: str | None = None,
    data_period: str | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "data": data,
        "meta": {
            "source": source,
            "run_id": run_id,
            "data_period": data_period,
            "warnings": warnings or [],
        },
    }


# status_code → 기계 판독용 code(docs/03 §7 "표준 {error:{code,message}}"). 목록에 없는
# 상태코드는 "ERROR"로 폴백 — 새 상태코드를 쓰게 되면 여기 추가한다.
_ERROR_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    404: "NOT_FOUND",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


def error_envelope(status_code: int, message: str) -> dict[str, Any]:
    """표준 에러 응답 {error:{code,message}}(docs/03 §7). 모든 에러 경로가 이 모양 하나로
    수렴하도록 main.py의 전역 예외 핸들러·middleware.py에서만 호출한다(라우터는 여전히
    HTTPException(detail=...)만 던지면 됨 — 중앙에서 이 모양으로 재포장)."""
    return {"error": {"code": _ERROR_CODES.get(status_code, "ERROR"), "message": message}}
