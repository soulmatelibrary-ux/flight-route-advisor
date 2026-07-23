"""공항 운항 KPI(ACDM) 엔드포인트 (docs/03-backend-api.md §4.2, 2단계)."""

from __future__ import annotations

import re
from datetime import date

from fastapi import APIRouter, HTTPException, Path, Query
from sqlalchemy.exc import DBAPIError, OperationalError

from app.envelope import envelope
from app.queries import airport_ops

router = APIRouter(prefix="/api/airports", tags=["airports"])

_ICAO_RE = re.compile(r"^[A-Z]{4}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DB_ERRORS = (OperationalError, DBAPIError)


def _validate_icao(value: str, field: str) -> str:
    value = value.strip().upper()
    if not _ICAO_RE.match(value):
        raise HTTPException(status_code=400, detail=f"{field}는 ICAO 4자리 영문이어야 함: {value!r}")
    return value


def _validate_date(value: str, field: str) -> str:
    if not _DATE_RE.match(value):
        raise HTTPException(status_code=400, detail=f"{field}는 YYYY-MM-DD 형식이어야 함: {value!r}")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field}는 존재하는 날짜여야 함: {value!r}") from exc
    return value


@router.get("/{icao}/ops")
def get_airport_ops(
    icao: str = Path(..., min_length=4, max_length=4),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
):
    icao = _validate_icao(icao, "icao")
    if date_from is not None:
        date_from = _validate_date(date_from, "date_from")
    if date_to is not None:
        date_to = _validate_date(date_to, "date_to")
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(status_code=400, detail="date_from은 date_to보다 앞이거나 같아야 함")

    try:
        data, period = airport_ops.ops_summary(icao=icao, date_from=date_from, date_to=date_to)
    except _DB_ERRORS as exc:
        raise HTTPException(status_code=503, detail="DB에 연결할 수 없음") from exc
    return envelope(data, source="processed_acdm", data_period=period)
