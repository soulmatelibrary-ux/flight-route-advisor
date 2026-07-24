"""ODR2 DB 조회 (docs/03-backend-api.md §4.1, MVP 유일 운항 API).

`backend/batch/build_odr2.py`가 `advisor_odr2_*` 6종에 적재한 결과를 읽기전용 role
(`advisor_readonly`)로 조회한다(예전 파일 아티팩트 `odr2.json` 읽기를 대체, 2026-07-23
DB 통합). 반환 dict 모양은 예전 파일 기반 버전과 동일하게 유지해 `routers/routes.py`·
프론트는 무변경으로 둔다.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select

from app.db import tables
from app.db.session import get_engine


class Odr2NotBuiltError(RuntimeError):
    """`advisor_odr2_od`가 비어 있음 — `python -m batch.build_odr2`가 아직 한 번도 안 돌았음."""


def _table(name: str):
    return tables.get_table(name)


def _repeatable_read_connect():
    """한 요청 안의 여러 SELECT가 전부 같은 스냅샷을 보게 한다.

    기본 READ COMMITTED는 같은 커넥션이라도 SQL문마다 그 시점의 최신 커밋을 새로
    본다(Postgres 공식 동작) — `routes_for()`처럼 od/route/fir/fix/track/frc를 순차
    조회하는 도중 배치의 TRUNCATE+INSERT 트랜잭션이 끼어들면 한 응답 안에 신·구
    세대 데이터가 섞일 수 있다(리뷰 지적사항, 2026-07-23). REPEATABLE READ로 트랜잭션
    시작 시점의 스냅샷을 고정해 막는다.
    """
    return get_engine().connect().execution_options(isolation_level="REPEATABLE READ")


def _ensure_built(conn) -> None:
    t = _table("advisor_odr2_od")
    exists = conn.execute(select(t.c.dep).limit(1)).first()
    if exists is None:
        raise Odr2NotBuiltError(
            "advisor_odr2_od 비어 있음 — 먼저 `python -m batch.build_odr2` 실행 필요"
        )


def od_pairs() -> tuple[list[dict[str, Any]], str | None]:
    """출발/도착 OD 쌍 목록(편수순, docs §4.1 od-pairs) + data_period.

    같은 트랜잭션에서 함께 조회해 목록과 data_period가 서로 다른 배치 세대를
    가리키는 일이 없게 한다(리뷰 지적사항, 2026-07-23 — 예전엔 라우터가 이 함수와
    `data_period()`를 별도 커넥션 2번으로 호출해 그 사이에 배치가 끼어들 여지가 있었음).

    `total_flights` 동률 시 `dep, arr`로 2차 정렬해 결정적 순서를 보장한다 — DB 정렬은
    동률 그룹 내부 순서를 보장하지 않아(파일 아티팩트 시절엔 dict 삽입 순서로 우연히
    안정적이었음), 2차 키 없이는 응답 순서가 실행마다 달라질 수 있다(실측 확인,
    2026-07-23 DB 통합 검증 중 — `latest_run.py`/`build_odr2.py`에서 이미 겪은 동률
    비결정성 함정과 동일 종류).
    """
    t = _table("advisor_odr2_od")
    with _repeatable_read_connect() as conn, conn.begin():
        _ensure_built(conn)
        rows = conn.execute(
            select(t.c.dep, t.c.arr, t.c.total_flights)
            .order_by(t.c.total_flights.desc(), t.c.dep, t.c.arr)
        ).all()
        period_row = conn.execute(select(t.c.data_period).limit(1)).first()
    data = [{"dep": dep, "arr": arr, "total_flights": total} for dep, arr, total in rows]
    return data, (period_row[0] if period_row else None)


def routes_for(dep: str, arr: str) -> tuple[dict[str, Any] | None, str | None]:
    """특정 OD의 경로옵션 목록(docs §4.1 응답 예시 형태) + data_period. OD 없으면 (None, period)."""
    od_t = _table("advisor_odr2_od")
    route_t = _table("advisor_odr2_route")
    fir_t = _table("advisor_odr2_route_fir")
    fix_t = _table("advisor_odr2_route_fix")
    runway_t = _table("advisor_odr2_route_runway")
    track_t = _table("advisor_odr2_track_point")
    frc_t = _table("advisor_odr2_full_route_point")

    with _repeatable_read_connect() as conn, conn.begin():
        _ensure_built(conn)

        period_row = conn.execute(select(od_t.c.data_period).limit(1)).first()
        period = period_row[0] if period_row else None

        od_row = conn.execute(
            select(od_t.c.total_flights).where(od_t.c.dep == dep, od_t.c.arr == arr)
        ).first()
        if od_row is None:
            return None, period
        total_flights = od_row[0]

        route_rows = conn.execute(
            select(
                route_t.c.rank, route_t.c.flights, route_t.c.avg_min, route_t.c.delay_count,
                route_t.c.heavy_count, route_t.c.cruise_parity, route_t.c.gate_in, route_t.c.gate_out,
            )
            .where(route_t.c.dep == dep, route_t.c.arr == arr)
            .order_by(route_t.c.rank)
        ).all()

        firs_by_rank: dict[int, list[str]] = defaultdict(list)
        for rank, fir_icao in conn.execute(
            select(fir_t.c.rank, fir_t.c.fir_icao)
            .where(fir_t.c.dep == dep, fir_t.c.arr == arr)
            .order_by(fir_t.c.rank, fir_t.c.seq)
        ):
            firs_by_rank[rank].append(fir_icao)

        fixes_by_rank: dict[int, list[str]] = defaultdict(list)
        for rank, fix_name in conn.execute(
            select(fix_t.c.rank, fix_t.c.fix_name)
            .where(fix_t.c.dep == dep, fix_t.c.arr == arr)
            .order_by(fix_t.c.rank, fix_t.c.seq)
        ):
            fixes_by_rank[rank].append(fix_name)

        track_by_rank: dict[int, list[list[float]]] = defaultdict(list)
        for rank, lat, lon in conn.execute(
            select(track_t.c.rank, track_t.c.lat, track_t.c.lon)
            .where(track_t.c.dep == dep, track_t.c.arr == arr)
            .order_by(track_t.c.rank, track_t.c.seq)
        ):
            track_by_rank[rank].append([lat, lon])

        frc_by_rank: dict[int, list[list[float]]] = defaultdict(list)
        for rank, lat, lon in conn.execute(
            select(frc_t.c.rank, frc_t.c.lat, frc_t.c.lon)
            .where(frc_t.c.dep == dep, frc_t.c.arr == arr)
            .order_by(frc_t.c.rank, frc_t.c.seq)
        ):
            frc_by_rank[rank].append([lat, lon])

        # 터미널 신호(A6, docs/13 STEP A6) — 출발 활주로 분포. gate_in/gate_out은 route_t
        # 자체 스칼라 컬럼이라 위 route_rows에서 이미 가져왔다.
        runway_by_rank: dict[int, list[list]] = defaultdict(list)
        for rank, runway, pct in conn.execute(
            select(runway_t.c.rank, runway_t.c.runway, runway_t.c.pct)
            .where(runway_t.c.dep == dep, runway_t.c.arr == arr)
            .order_by(runway_t.c.rank, runway_t.c.seq)
        ):
            runway_by_rank[rank].append([runway, pct])

    options = [
        {
            "flights": flights,
            "avg_min": avg_min,
            "delay_count": delay_count,
            "heavy_count": heavy_count,
            "enroute_firs": firs_by_rank.get(rank, []),
            "incheon_track_fixes": fixes_by_rank.get(rank, []),
            "track_coords": track_by_rank.get(rank, []),
            "full_route_coords": frc_by_rank.get(rank, []),
            "cruise_parity": cruise_parity,
            "gate_in": gate_in,
            "gate_out": gate_out,
            "runway_dist": runway_by_rank.get(rank, []),
        }
        for rank, flights, avg_min, delay_count, heavy_count, cruise_parity, gate_in, gate_out in route_rows
    ]
    data = {"dep": dep, "arr": arr, "total_flights": total_flights, "options": options}
    return data, period
