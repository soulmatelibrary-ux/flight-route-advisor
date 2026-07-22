"""경로추천(ODR2) 엔드포인트 (docs/03-backend-api.md §4.1, MVP 유일 운항 API)."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Query

from app.envelope import envelope
from app.queries import routes as routes_query

router = APIRouter(prefix="/api/routes", tags=["routes"])

_ICAO_RE = re.compile(r"^[A-Z]{4}$")


def _validate_icao(value: str, field: str) -> str:
    value = value.strip().upper()
    if not _ICAO_RE.match(value):
        raise HTTPException(status_code=400, detail=f"{field}는 ICAO 4자리 영문이어야 함: {value!r}")
    return value


@router.get("/od-pairs")
def get_od_pairs():
    try:
        data = routes_query.od_pairs()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="ODR2 아티팩트가 아직 생성되지 않음") from exc
    return envelope(data, source="odr2-batch", data_period=routes_query.data_period())


@router.get("")
def get_routes(
    dep: str = Query(..., min_length=4, max_length=4),
    arr: str = Query(..., min_length=4, max_length=4),
):
    dep = _validate_icao(dep, "dep")
    arr = _validate_icao(arr, "arr")
    try:
        data = routes_query.routes_for(dep, arr)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="ODR2 아티팩트가 아직 생성되지 않음") from exc
    if data is None:
        raise HTTPException(status_code=404, detail=f"OD 쌍을 찾을 수 없음: {dep}|{arr}")
    return envelope(data, source="odr2-batch", data_period=routes_query.data_period())
