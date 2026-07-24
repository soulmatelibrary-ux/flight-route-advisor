"""경로추천(ODR2) 엔드포인트 (docs/03-backend-api.md §4.1, MVP 유일 운항 API)."""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.exc import DBAPIError, OperationalError

from app.envelope import envelope
from app.queries import flow_reasoning as flow_query
from app.queries import odhr as odhr_query
from app.queries import routes as routes_query

router = APIRouter(prefix="/api/routes", tags=["routes"])

_ICAO_RE = re.compile(r"^[A-Z]{4}$")

# odhr(GET /delay-history)은 여전히 파일 아티팩트를 읽는다(2026-07-23 DB 통합 범위 밖) —
# 아티팩트 손상(JSONDecodeError)·권한/IO 문제(OSError)도 FileNotFoundError와 함께 503으로
# 통일한다(reference.py와 동일 매핑, 2026-07-22 리뷰 A-1).
_ASSET_ERRORS = (FileNotFoundError, OSError, json.JSONDecodeError)

# od-pairs/routes/flow는 2026-07-23 DB 통합으로 파일 대신 DB를 읽는다. DB 연결 실패는
# fois.py/flow_management.py와 동일하게 OperationalError/DBAPIError를 503으로 매핑하고,
# 배치가 아직 한 번도 안 돈 경우(테이블이 비어 있음)는 각 쿼리 모듈의 전용 예외로 구분한다.
_DB_ERRORS = (OperationalError, DBAPIError)
_ODR2_ERRORS = _DB_ERRORS + (routes_query.Odr2NotBuiltError,)
_FLOW_ERRORS = _DB_ERRORS + (flow_query.FlowNotBuiltError,)


def _validate_icao(value: str, field: str) -> str:
    value = value.strip().upper()
    if not _ICAO_RE.match(value):
        raise HTTPException(status_code=400, detail=f"{field}는 ICAO 4자리 영문이어야 함: {value!r}")
    return value


@router.get("/od-pairs")
def get_od_pairs():
    try:
        data, period = routes_query.od_pairs()
    except _ODR2_ERRORS as exc:
        raise HTTPException(status_code=503, detail="ODR2 데이터가 아직 생성되지 않음") from exc
    return envelope(data, source="odr2-batch", data_period=period)


@router.get("")
def get_routes(
    dep: str = Query(..., min_length=4, max_length=4),
    arr: str = Query(..., min_length=4, max_length=4),
):
    dep = _validate_icao(dep, "dep")
    arr = _validate_icao(arr, "arr")
    try:
        data, period = routes_query.routes_for(dep, arr)
    except _ODR2_ERRORS as exc:
        raise HTTPException(status_code=503, detail="ODR2 데이터가 아직 생성되지 않음") from exc
    if data is None:
        raise HTTPException(status_code=404, detail=f"OD 쌍을 찾을 수 없음: {dep}|{arr}")
    return envelope(data, source="odr2-batch", data_period=period)


@router.get("/flow")
def get_route_flow(
    dep: str = Query(..., min_length=4, max_length=4),
    arr: str = Query(..., min_length=4, max_length=4),
):
    """OD 흐름관리 영향률(docs/13 STEP A1). 기록 부족은 404가 아니라
    `data.found=false`(수용기준 — 완성본 routeFlowBrief와 동일 동작)."""
    dep = _validate_icao(dep, "dep")
    arr = _validate_icao(arr, "arr")
    try:
        data, period = flow_query.flow_for(dep, arr)
    except _FLOW_ERRORS as exc:
        raise HTTPException(status_code=503, detail="흐름관리 영향률 데이터가 아직 생성되지 않음") from exc
    return envelope(data, source="flow-batch", data_period=period)


@router.get("/delay-history")
def get_delay_history(
    dep: str = Query(..., min_length=4, max_length=4),
    arr: str = Query(..., min_length=4, max_length=4),
    hour: int | None = Query(None, ge=0, le=23),
):
    """OD 시간대별 교통량·평균 소요시간(docs/13 STEP A2). `on_time_pct`는 항상 null —
    검증된 계산식이 없어 근사치를 내보내지 않는다(배치 docstring 참고). 기록 부족은
    404가 아니라 `data.found=false`(A1과 동일 컨벤션)."""
    dep = _validate_icao(dep, "dep")
    arr = _validate_icao(arr, "arr")
    try:
        data = odhr_query.delay_history_for(dep, arr, hour)
        period = odhr_query.data_period()
    except _ASSET_ERRORS as exc:
        raise HTTPException(status_code=503, detail="시간대 교통량 아티팩트가 아직 생성되지 않음") from exc
    return envelope(data, source="odhr-batch", data_period=period)
