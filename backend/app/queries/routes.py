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


def _ensure_built(conn) -> None:
    t = _table("advisor_odr2_od")
    exists = conn.execute(select(t.c.dep).limit(1)).first()
    if exists is None:
        raise Odr2NotBuiltError(
            "advisor_odr2_od 비어 있음 — 먼저 `python -m batch.build_odr2` 실행 필요"
        )


def data_period() -> str | None:
    """모든 OD 행이 같은 배치 실행에서 나온 값을 공유하므로 아무 한 행이나 읽으면 된다."""
    t = _table("advisor_odr2_od")
    with get_engine().connect() as conn:
        row = conn.execute(select(t.c.data_period).limit(1)).first()
    return row[0] if row else None


def od_pairs() -> list[dict[str, Any]]:
    """출발/도착 OD 쌍 목록, 편수순(docs §4.1 od-pairs)."""
    t = _table("advisor_odr2_od")
    with get_engine().connect() as conn:
        _ensure_built(conn)
        rows = conn.execute(
            select(t.c.dep, t.c.arr, t.c.total_flights).order_by(t.c.total_flights.desc())
        ).all()
    return [{"dep": dep, "arr": arr, "total_flights": total} for dep, arr, total in rows]


def routes_for(dep: str, arr: str) -> dict[str, Any] | None:
    """특정 OD의 경로옵션 목록(docs §4.1 응답 예시 형태). 없으면 None."""
    od_t = _table("advisor_odr2_od")
    route_t = _table("advisor_odr2_route")
    fir_t = _table("advisor_odr2_route_fir")
    fix_t = _table("advisor_odr2_route_fix")
    track_t = _table("advisor_odr2_track_point")
    frc_t = _table("advisor_odr2_full_route_point")

    with get_engine().connect() as conn:
        _ensure_built(conn)

        od_row = conn.execute(
            select(od_t.c.total_flights).where(od_t.c.dep == dep, od_t.c.arr == arr)
        ).first()
        if od_row is None:
            return None
        total_flights = od_row[0]

        route_rows = conn.execute(
            select(
                route_t.c.rank, route_t.c.flights, route_t.c.avg_min, route_t.c.delay_count,
                route_t.c.heavy_count, route_t.c.cruise_parity,
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
        }
        for rank, flights, avg_min, delay_count, heavy_count, cruise_parity in route_rows
    ]
    return {"dep": dep, "arr": arr, "total_flights": total_flights, "options": options}
