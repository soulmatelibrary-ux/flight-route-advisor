"""흐름관리 조치 목록 엔드포인트 (docs/03-backend-api.md §4.4, 2단계 착수)."""

from __future__ import annotations

import re
from datetime import date

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.exc import DBAPIError, OperationalError

from app.envelope import envelope
from app.queries import flow_management as flow_query

router = APIRouter(prefix="/api/flow-management", tags=["flow-management"])

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_IDENT_RE = re.compile(r"^[A-Z0-9]{1,10}$")
_DB_ERRORS = (OperationalError, DBAPIError)


def _validate_date(value: str, field: str) -> str:
    if not _DATE_RE.match(value):
        raise HTTPException(status_code=400, detail=f"{field}는 YYYY-MM-DD 형식이어야 함: {value!r}")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field}는 존재하는 날짜여야 함: {value!r}") from exc
    return value


def _validate_ident(value: str, field: str) -> str:
    value = value.strip().upper()
    if not _IDENT_RE.match(value):
        raise HTTPException(status_code=400, detail=f"{field}는 영문·숫자 1~10자여야 함: {value!r}")
    return value


@router.get("")
def get_flow_management(
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    fir: str | None = Query(default=None, min_length=1, max_length=10),
    airway: str | None = Query(default=None, min_length=1, max_length=10),
    limit: int = Query(default=flow_query.DEFAULT_LIMIT, ge=1, le=flow_query.MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    if date_from is not None:
        date_from = _validate_date(date_from, "date_from")
    if date_to is not None:
        date_to = _validate_date(date_to, "date_to")
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(status_code=400, detail="date_from은 date_to보다 앞이거나 같아야 함")
    if fir is not None:
        fir = _validate_ident(fir, "fir")
    if airway is not None:
        airway = _validate_ident(airway, "airway")

    try:
        data, period = flow_query.list_flow_management(
            date_from=date_from, date_to=date_to, fir=fir, airway=airway, limit=limit, offset=offset
        )
    except _DB_ERRORS as exc:
        raise HTTPException(status_code=503, detail="DB에 연결할 수 없음") from exc
    return envelope(data, source="processed_flow_management", data_period=period)
