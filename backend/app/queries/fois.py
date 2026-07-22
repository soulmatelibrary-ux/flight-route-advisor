"""FOIS 지연원인 집계 (docs/03-backend-api.md §4.3, 2단계 착수).

`processed_fois_departure`/`processed_fois_arrival`를 "일자별 최신 run 우선"
윈도우(`latest_run.latest_view`)로 조회해 원인대/소분류·공정·관여주체·사유별로
건수를 집계한다. run_id는 ODR2(§4.1)와 동일한 이유로 null — 날짜별 승자 run이
다를 수 있어 단일 run_id로 환원할 수 없다(docs/03 §2). 대신 data_period는 이번
조회 윈도우에서 실제로 걸린 날짜의 min/max를 계산해 채운다.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from app.db import column_map
from app.db.session import get_engine
from app.queries.latest_run import latest_view

_TABLE_BY_DIRECTION: dict[str, str] = {
    "dep": "processed_fois_departure",
    "arr": "processed_fois_arrival",
}
_AIRPORT_COLUMN_BY_DIRECTION: dict[str, str] = {
    "dep": "dep_airport",
    "arr": "arr_airport",
}


def delays(
    *,
    direction: str,
    airport: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    """direction("dep"|"arr")·airport(ICAO)·date_from/date_to(YYYY-MM-DD)로 필터링한
    사유 원인 집계. 호출자(routers/fois.py)가 입력 형식을 이미 검증했다고 신뢰한다
    (routers/routes.py의 ICAO 검증과 동일한 책임 분리, docs/06-conventions.md §8).

    반환: (응답 data dict, data_period). data_period는 실제 걸린 날짜 범위가 없으면
    (결과 0건) null.
    """
    table_name = _TABLE_BY_DIRECTION[direction]
    date_col_name = column_map.DATE_COLUMNS[table_name]
    airport_col_name = _AIRPORT_COLUMN_BY_DIRECTION[direction]

    window = latest_view(table_name).subquery("fois_window")
    date_col = window.c[date_col_name]
    airport_col = window.c[airport_col_name]

    conditions = []
    if airport is not None:
        conditions.append(airport_col == airport)
    if date_from is not None:
        conditions.append(date_col >= date_from)
    if date_to is not None:
        conditions.append(date_col <= date_to)

    group_cols = (
        window.c.cause_major,
        window.c.cause_minor,
        window.c.cause_process,
        window.c.involved_party,
        window.c.reason,
    )
    agg_stmt = (
        select(*group_cols, func.count().label("count"))
        .where(*conditions)
        .group_by(*group_cols)
        .order_by(func.count().desc())
    )
    period_stmt = select(func.min(date_col), func.max(date_col)).where(*conditions)

    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(agg_stmt).all()
        min_date, max_date = conn.execute(period_stmt).one()

    causes = [
        {
            "cause_major": row.cause_major,
            "cause_minor": row.cause_minor,
            "cause_process": row.cause_process,
            "involved_party": row.involved_party,
            "reason": row.reason,
            "count": row.count,
        }
        for row in rows
    ]
    total = sum(cause["count"] for cause in causes)
    period = (
        f"{min_date.replace('-', '')}-{max_date.replace('-', '')}"
        if min_date and max_date
        else None
    )
    data = {
        "airport": airport,
        "direction": direction,
        "total": total,
        "causes": causes,
    }
    return data, period
