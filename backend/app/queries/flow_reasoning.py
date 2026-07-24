"""흐름관리 영향률 DB 조회 (docs/13-ai-reasoning-dev-plan.md STEP A1).

`backend/batch/build_flow.py`가 `advisor_flow_*` 6종에 적재한 결과를 읽기전용 role
(`advisor_readonly`)로 조회한다(예전 파일 아티팩트 `flow.json` 읽기를 대체, 2026-07-23
DB 통합). 반환 dict 모양은 예전 파일 기반 버전과 동일하게 유지해 `routers/routes.py`·
프론트는 무변경으로 둔다.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.db import tables
from app.db.session import get_engine


class FlowNotBuiltError(RuntimeError):
    """`advisor_flow_od`가 비어 있음 — `python -m batch.build_flow`가 아직 한 번도 안 돌았음."""


def _table(name: str):
    return tables.get_table(name)


def _repeatable_read_connect():
    """`queries/routes.py._repeatable_read_connect()`와 동일한 이유 —
    od/reason/limit/measure/hour/route_group 순차 조회가 배치 재적재 중간에 걸리면
    한 응답 안에 신·구 세대 데이터가 섞일 수 있어 REPEATABLE READ로 스냅샷을 고정한다
    (리뷰 지적사항, 2026-07-23)."""
    return get_engine().connect().execution_options(isolation_level="REPEATABLE READ")


def _ensure_built(conn) -> None:
    t = _table("advisor_flow_od")
    exists = conn.execute(select(t.c.dep).limit(1)).first()
    if exists is None:
        raise FlowNotBuiltError(
            "advisor_flow_od 비어 있음 — 먼저 `python -m batch.build_flow` 실행 필요"
        )


def flow_for(dep: str, arr: str) -> tuple[dict[str, Any], str | None]:
    """OD 하나의 흐름관리 영향 요약 + 그 OD의 경로그룹별 영향률(route_group 서브셋) + data_period.

    기록 부족(od에 행 없음)은 예외가 아니라 `found: false`로 반환한다
    (docs/13 STEP A1 수용기준: 미기록 OD는 404 아님 "기록 부족" 처리).
    """
    od_t = _table("advisor_flow_od")
    reason_t = _table("advisor_flow_od_reason")
    limit_t = _table("advisor_flow_od_limit")
    measure_t = _table("advisor_flow_od_measure")
    hour_t = _table("advisor_flow_od_hour")
    group_t = _table("advisor_flow_route_group")

    with _repeatable_read_connect() as conn, conn.begin():
        _ensure_built(conn)

        period_row = conn.execute(select(od_t.c.data_period).limit(1)).first()
        period = period_row[0] if period_row else None

        routes = {
            route_key: pct
            for route_key, pct in conn.execute(
                select(group_t.c.route_key, group_t.c.pct)
                .where(group_t.c.dep == dep, group_t.c.arr == arr)
            )
        }

        od_row = conn.execute(
            select(
                od_t.c.impact_pct, od_t.c.affected_flights, od_t.c.total_flights,
                od_t.c.on_time_affected, od_t.c.on_time_normal,
                od_t.c.delay_affected_min, od_t.c.delay_normal_min,
            ).where(od_t.c.dep == dep, od_t.c.arr == arr)
        ).first()

        if od_row is None:
            return {"dep": dep, "arr": arr, "found": False, "routes": routes}, period

        (
            impact_pct, affected_flights, total_flights,
            on_time_affected, on_time_normal, delay_affected_min, delay_normal_min,
        ) = od_row

        main_causes = [
            [reason_code, pct]
            for reason_code, pct in conn.execute(
                select(reason_t.c.reason_code, reason_t.c.pct)
                .where(reason_t.c.dep == dep, reason_t.c.arr == arr)
                .order_by(reason_t.c.seq)
            )
        ]
        main_limits = [
            limit_text
            for (limit_text,) in conn.execute(
                select(limit_t.c.limit_text)
                .where(limit_t.c.dep == dep, limit_t.c.arr == arr)
                .order_by(limit_t.c.seq)
            )
        ]
        measure_ids = [
            measure_id
            for (measure_id,) in conn.execute(
                select(measure_t.c.measure_id)
                .where(measure_t.c.dep == dep, measure_t.c.arr == arr)
                .order_by(measure_t.c.seq)
            )
        ]
        hour_by_hour = {
            hour: impact
            for hour, impact in conn.execute(
                select(hour_t.c.hour, hour_t.c.impact_pct)
                .where(hour_t.c.dep == dep, hour_t.c.arr == arr)
            )
        }

    hour_impact_pct = [
        -1 if hour_by_hour.get(hour) is None else hour_by_hour[hour] for hour in range(24)
    ]

    data = {
        "dep": dep,
        "arr": arr,
        "found": True,
        "impact_pct": impact_pct,
        "affected_flights": affected_flights,
        "total_flights": total_flights,
        "on_time_affected": on_time_affected,
        "on_time_normal": on_time_normal,
        "delay_affected_min": delay_affected_min,
        "delay_normal_min": delay_normal_min,
        "main_causes": main_causes,
        "main_limits": main_limits,
        "measure_ids": measure_ids,
        "hour_impact_pct": hour_impact_pct,
        "routes": routes,
    }
    return data, period
