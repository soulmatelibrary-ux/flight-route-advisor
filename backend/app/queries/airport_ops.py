"""공항 운항 KPI(ACDM) 집계 (docs/03-backend-api.md §4.2, 2단계).

`processed_acdm_departure`/`processed_acdm_arrival`을 "일자별 최신 run 우선"
윈도우(`latest_run.latest_view`)로 조회해 정시성/택시/CTOT 준수 요약을 만든다.
ACDM 스킬(preprocess-acdm)이 계산해 둔 KPI 컬럼을 그대로 집계만 한다 — 이 모듈이
새로 판정 로직을 만들지 않는다(스킬을 블랙박스로 다루는 원칙, docs/07-checklist.md
Stage 0 §제외 건수 기록 사례와 동일).

**on_time_rate 임계값(2026-07-23 확정)**: 원본 스킬 계약(data-contract.md)·전처리
스크립트(prepare_acdm_{departure,arrival}_core5.py)는 punctuality_min의 부호·단위만
정의하고 "정시" 판정 임계는 정의하지 않는다(코드에 없음, 문서에도 없음 — 임의 판정
발명 금지 원칙상 확인 필요한 갭). EUROCONTROL/ICAO가 공통으로 쓰는 산업표준 On-Time
Performance 정의(스케줄 대비 15분 이내)를 채택해 `punctuality_min <= 15`(조기는
항상 정시로 침, 늦음만 15분까지 허용)로 확정한다 — docs/03 §4.2에 근거를 남겨둔다.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Numeric, case, cast, func, select
from sqlalchemy.engine import Connection

from app.db.session import get_engine
from app.queries.latest_run import latest_view

_ON_TIME_THRESHOLD_MIN = 15

# ctot_slot_adherence는 스킬이 이미 계산해 둔 범주값(문자열)이다 — "조기"/"준수"/"지연"만
# 판정 가능한 모집단(분모)이고, "CTOT없음"(CTOT 미배정)·"계산불가"(CTOT는 있으나 편차를
# 계산할 수 없던 행)는 판정 대상 자체가 아니라 분모에서 제외한다.
_CTOT_JUDGED_VALUES = ("조기", "준수", "지연")


def _numeric(column):
    """이 테이블의 KPI 컬럼은 전부 text(스킬의 number_text()가 NaN을 빈 문자열로 직렬화,
    ingestion이 원본 타입을 그대로 보존). Postgres는 text<=int/avg(text)를 바로 못 해서
    (실측: "operator does not exist: text <= integer") 캐스팅이 필요하고, 빈 문자열은
    NULL로 취급해야 한다(''::numeric은 에러가 아니라 예외를 던짐) — 그래서 반드시
    nullif로 빈 문자열을 먼저 걷어낸 뒤 캐스팅한다."""
    return cast(func.nullif(column, ""), Numeric)


def _departure_summary(conn: Connection, window, conditions) -> dict[str, Any]:
    punctuality = _numeric(window.c.departure_punctuality_min)
    taxi_out = _numeric(window.c.taxi_out_additional_min)
    ctot = window.c.ctot_slot_adherence

    stmt = select(
        func.count().label("flights"),
        func.count(punctuality).label("punctuality_n"),
        func.sum(case((punctuality <= _ON_TIME_THRESHOLD_MIN, 1), else_=0)).label("on_time_n"),
        func.avg(taxi_out).label("avg_taxi_out_min"),
        func.count(case((ctot.in_(_CTOT_JUDGED_VALUES), 1))).label("ctot_judged_n"),
        func.sum(case((ctot == "준수", 1), else_=0)).label("ctot_ontime_n"),
    ).where(*conditions)
    row = conn.execute(stmt).one()

    return {
        "flights": row.flights,
        "on_time_rate": (row.on_time_n / row.punctuality_n) if row.punctuality_n else None,
        "avg_taxi_out_min": float(row.avg_taxi_out_min) if row.avg_taxi_out_min is not None else None,
        "ctot_adherence": (row.ctot_ontime_n / row.ctot_judged_n) if row.ctot_judged_n else None,
    }


def _arrival_summary(conn: Connection, window, conditions) -> dict[str, Any]:
    punctuality = _numeric(window.c.arrival_punctuality_min)
    taxi_in = _numeric(window.c.actual_taxi_in_min)
    fir_to_app = _numeric(window.c.fir_to_app_min)

    stmt = select(
        func.count().label("flights"),
        func.count(punctuality).label("punctuality_n"),
        func.sum(case((punctuality <= _ON_TIME_THRESHOLD_MIN, 1), else_=0)).label("on_time_n"),
        func.avg(taxi_in).label("avg_taxi_in_min"),
        func.avg(fir_to_app).label("avg_fir_to_app_min"),
    ).where(*conditions)
    row = conn.execute(stmt).one()

    return {
        "flights": row.flights,
        "on_time_rate": (row.on_time_n / row.punctuality_n) if row.punctuality_n else None,
        "avg_taxi_in_min": float(row.avg_taxi_in_min) if row.avg_taxi_in_min is not None else None,
        "avg_fir_to_app_min": float(row.avg_fir_to_app_min) if row.avg_fir_to_app_min is not None else None,
    }


def _period(conn: Connection, window, conditions) -> tuple[str | None, str | None]:
    date_col = window.c.operation_date
    stmt = select(func.min(date_col), func.max(date_col)).where(*conditions)
    return conn.execute(stmt).one()


def ops_summary(
    *, icao: str, date_from: str | None = None, date_to: str | None = None
) -> tuple[dict[str, Any], str | None]:
    """icao(ICAO 4자리)·date_from/date_to(YYYY-MM-DD)로 필터링한 출발·도착 KPI 요약.

    호출자(routers/airports.py)가 입력 형식을 이미 검증했다고 신뢰한다(fois.py/
    flow_management.py와 동일한 책임 분리). 반환: (응답 data dict, data_period).
    data_period는 출발·도착 양쪽을 합친 실제 걸린 날짜의 min/max(둘 다 0건이면 null).
    """
    dep_window = latest_view("processed_acdm_departure").subquery("dep_window")
    arr_window = latest_view("processed_acdm_arrival").subquery("arr_window")

    dep_conditions = [dep_window.c.airport_icao == icao]
    arr_conditions = [arr_window.c.airport_icao == icao]
    if date_from is not None:
        dep_conditions.append(dep_window.c.operation_date >= date_from)
        arr_conditions.append(arr_window.c.operation_date >= date_from)
    if date_to is not None:
        dep_conditions.append(dep_window.c.operation_date <= date_to)
        arr_conditions.append(arr_window.c.operation_date <= date_to)

    engine = get_engine()
    with engine.connect() as conn:
        departure = _departure_summary(conn, dep_window, dep_conditions)
        arrival = _arrival_summary(conn, arr_window, arr_conditions)
        dep_min, dep_max = _period(conn, dep_window, dep_conditions)
        arr_min, arr_max = _period(conn, arr_window, arr_conditions)

    dates = [d for d in (dep_min, dep_max, arr_min, arr_max) if d is not None]
    period = f"{min(dates).replace('-', '')}-{max(dates).replace('-', '')}" if dates else None

    data = {"icao": icao, "departure": departure, "arrival": arrival}
    return data, period
