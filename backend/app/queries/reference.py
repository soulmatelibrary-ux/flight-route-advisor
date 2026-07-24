"""참조 데이터(공역·항공로·지점·SID/STAR) DB 조회 (docs/03-backend-api.md §3, DB 전환).

`app/reference/loader.py`가 예전에 `사전빌드_JSON/*.json`에서 읽던 것과 동일한 모양의
파이썬 자료구조를 반환한다 — loader.py의 bbox 필터/도형 가공 코드는 그대로 재사용하고
행의 출처만 파일→DB로 바꾸는 것이 목적이라, 여기서 반환하는 튜플/딕셔너리 키는 예전
JSON 행 모양과 의도적으로 맞춰져 있다. `reference_*` 10종은 processed_*와 달리
run_id/최신-run 윈도잉이 없는 정적 마스터 데이터라(단순 SELECT) `latest_view`를 쓰지 않는다.

정적 빌드 산출물과 동일하게 프로세스 생애주기 동안 메모리에 캐시한다(예전 loader.py
`_cache`와 동일한 이유 — 매 요청마다 DB 왕복하지 않음).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.db import tables
from app.db.session import get_engine

_cache: dict[str, Any] = {}


def _table(name: str):
    return tables.get_table(name)


def fetch_firs() -> list[tuple[str, str, list[list[float]]]]:
    """[(icao, name_en, [flat_ring1, flat_ring2, ...]), ...] — firs.json 원본 행 모양과 동일."""
    if "firs" not in _cache:
        t = _table("reference_fir")
        with get_engine().connect() as conn:
            rows = conn.execute(select(t.c.icao, t.c.name_en, t.c.polygons)).all()
        result = []
        for icao, name_en, polygons in rows:
            flat_rings = [[coord for pair in ring for coord in pair] for ring in polygons]
            result.append((icao, name_en, flat_rings))
        _cache["firs"] = result
    return _cache["firs"]


def fetch_fir_labels() -> list[tuple[str, float, float]]:
    """[(icao, lat, lon), ...] — firlbl.json 원본 행 모양과 동일."""
    if "fir_labels" not in _cache:
        t = _table("reference_fir")
        with get_engine().connect() as conn:
            rows = conn.execute(
                select(t.c.icao, t.c.label_lat, t.c.label_lon).where(t.c.label_lat.is_not(None))
            ).all()
        _cache["fir_labels"] = [(icao, lat, lon) for icao, lat, lon in rows]
    return _cache["fir_labels"]


def fetch_tca() -> list[tuple[str, str, list[float]]]:
    """[(name, name_ko, flat_coords), ...] — tca.json 원본 행 모양과 동일."""
    if "tca" not in _cache:
        t = _table("reference_tca")
        with get_engine().connect() as conn:
            rows = conn.execute(select(t.c.name, t.c.name_ko, t.c.polygon)).all()
        _cache["tca"] = [
            (name, name_ko, [coord for pair in polygon for coord in pair])
            for name, name_ko, polygon in rows
        ]
    return _cache["tca"]


def fetch_airways_with_seq() -> list[dict]:
    """[{ident, seq, a:[lat,lon], b:[lat,lon], upper, lower}, ...].

    seq는 적재 스크립트(data-ingestion-backend/scripts/migrate_static_reference_to_db.py)가
    원본 사전빌드 JSON 순서 그대로 미리 계산해 저장해 둔 값이다 — 예전 loader.py처럼 매
    요청마다(혹은 첫 캐시 채움 시) 다시 계산할 필요가 없다(bbox로 거른 부분집합 위에서
    재계산하면 같은 물리 구간이 요청마다 다른 seq를 받는 과거 버그를 애초에 재현하지 않음).
    """
    if "airways_with_seq" not in _cache:
        t = _table("reference_airway")
        with get_engine().connect() as conn:
            rows = conn.execute(
                select(t.c.ident, t.c.seq, t.c.lat_a, t.c.lon_a, t.c.lat_b, t.c.lon_b, t.c.upper, t.c.lower)
            ).all()
        _cache["airways_with_seq"] = [
            {
                "ident": ident,
                "seq": seq,
                "a": [lat_a, lon_a],
                "b": [lat_b, lon_b],
                "upper": upper,
                "lower": lower,
            }
            for ident, seq, lat_a, lon_a, lat_b, lon_b, upper, lower in rows
        ]
    return _cache["airways_with_seq"]


def fetch_airports() -> list[dict]:
    """[{i, n, c:[lat,lon], e, t}, ...] — airports.json 원본 행 모양과 동일."""
    if "airports" not in _cache:
        t = _table("reference_airport")
        with get_engine().connect() as conn:
            rows = conn.execute(select(t.c.icao, t.c.name, t.c.lat, t.c.lon, t.c.elev_ft, t.c.type)).all()
        _cache["airports"] = [
            {"i": icao, "n": name, "c": [lat, lon], "e": elev_ft, "t": type_}
            for icao, name, lat, lon, elev_ft, type_ in rows
        ]
    return _cache["airports"]


def fetch_navaids() -> list[dict]:
    """[{i, n, t, c:[lat,lon], f}, ...] — navaids.json 원본 행 모양과 동일."""
    if "navaids" not in _cache:
        t = _table("reference_navaid")
        with get_engine().connect() as conn:
            rows = conn.execute(select(t.c.ident, t.c.name, t.c.type, t.c.lat, t.c.lon, t.c.freq)).all()
        _cache["navaids"] = [
            {"i": ident, "n": name, "t": type_, "c": [lat, lon], "f": freq}
            for ident, name, type_, lat, lon, freq in rows
        ]
    return _cache["navaids"]


def fetch_waypoints() -> list[list]:
    """[[ident, lat, lon, country], ...] — waypoints.json 원본 행 모양과 동일."""
    if "waypoints" not in _cache:
        t = _table("reference_waypoint")
        with get_engine().connect() as conn:
            rows = conn.execute(select(t.c.ident, t.c.lat, t.c.lon, t.c.country)).all()
        _cache["waypoints"] = [[ident, lat, lon, country] for ident, lat, lon, country in rows]
    return _cache["waypoints"]


# --- SID/STAR fix 좌표 해석 (승인된 계획 "핵심 설계 결정 3" 그대로) ---


def _navaid_index() -> dict[str, list[tuple[float, float]]]:
    if "navaid_index" not in _cache:
        t = _table("reference_navaid")
        with get_engine().connect() as conn:
            rows = conn.execute(select(t.c.ident, t.c.lat, t.c.lon)).all()
        index: dict[str, list[tuple[float, float]]] = {}
        for ident, lat, lon in rows:
            index.setdefault(ident, []).append((lat, lon))
        _cache["navaid_index"] = index
    return _cache["navaid_index"]


def _terminal_waypoint_index() -> dict[tuple[str, str], tuple[float, float]]:
    if "terminal_waypoint_index" not in _cache:
        t = _table("reference_waypoint_terminal")
        with get_engine().connect() as conn:
            rows = conn.execute(select(t.c.region_code, t.c.waypoint_id, t.c.lat, t.c.lon)).all()
        _cache["terminal_waypoint_index"] = {
            (region_code, waypoint_id): (lat, lon) for region_code, waypoint_id, lat, lon in rows
        }
    return _cache["terminal_waypoint_index"]


def _enroute_waypoint_index() -> dict[tuple[str, str], tuple[float, float]]:
    if "enroute_waypoint_index" not in _cache:
        t = _table("reference_waypoint_enroute")
        with get_engine().connect() as conn:
            rows = conn.execute(select(t.c.icao_code, t.c.waypoint_id, t.c.lat, t.c.lon)).all()
        _cache["enroute_waypoint_index"] = {
            (icao_code, waypoint_id): (lat, lon) for icao_code, waypoint_id, lat, lon in rows
        }
    return _cache["enroute_waypoint_index"]


def _airport_coord_index() -> dict[str, tuple[float, float]]:
    if "airport_coord_index" not in _cache:
        t = _table("reference_airport")
        with get_engine().connect() as conn:
            rows = conn.execute(select(t.c.icao, t.c.lat, t.c.lon)).all()
        # 같은 icao가 여러 행(원본 데이터 품질 이슈, 실측 확인)일 수 있어 첫 값을 쓴다 —
        # 어차피 SID/STAR가 있는 공항은 정규 상업공항이라 사실상 유일하다.
        index: dict[str, tuple[float, float]] = {}
        for icao, lat, lon in rows:
            index.setdefault(icao, (lat, lon))
        _cache["airport_coord_index"] = index
    return _cache["airport_coord_index"]


def _resolve_fix(airport_icao: str, fix_id: str) -> tuple[float, float] | None:
    """우선순위: (1) 해당 공항 터미널 지점 (2) 같은 리전(ICAO 접두 2글자) 엔루트 지점
    (3) navaid(동일 ident 여럿이면 공항 좌표에 가장 가까운 후보). 승인된 계획 참고."""
    terminal = _terminal_waypoint_index().get((airport_icao, fix_id))
    if terminal is not None:
        return terminal

    region_prefix = airport_icao[:2]
    enroute = _enroute_waypoint_index().get((region_prefix, fix_id))
    if enroute is not None:
        return enroute

    candidates = _navaid_index().get(fix_id)
    if candidates:
        if len(candidates) == 1:
            return candidates[0]
        airport_coord = _airport_coord_index().get(airport_icao)
        if airport_coord is None:
            return candidates[0]
        a_lat, a_lon = airport_coord
        return min(candidates, key=lambda c: (c[0] - a_lat) ** 2 + (c[1] - a_lon) ** 2)

    return None


def _procedure_rows(table_name: str, id_column: str, airport: str | None) -> list[dict]:
    t = _table(table_name)
    columns = (
        t.c.airport_icao, t.c[id_column], t.c.transition_id, t.c.sequence_number, t.c.fix_id,
    )
    stmt = select(*columns)
    if airport is not None:
        stmt = stmt.where(t.c.airport_icao == airport)
    stmt = stmt.order_by(t.c.airport_icao, t.c[id_column], t.c.transition_id, t.c.sequence_number)
    with get_engine().connect() as conn:
        return [dict(row._mapping) for row in conn.execute(stmt)]


def _build_procedures(rows: list[dict], id_column: str, proc: int) -> list[dict]:
    procedures: dict[tuple[str, str, str | None], list[dict]] = {}
    order: list[tuple[str, str, str | None]] = []
    for row in rows:
        key = (row["airport_icao"], row[id_column], row["transition_id"])
        if key not in procedures:
            procedures[key] = []
            order.append(key)
        procedures[key].append(row)

    result = []
    for airport_icao, proc_id, transition_id in order:
        legs = procedures[(airport_icao, proc_id, transition_id)]
        coords = []
        for leg in legs:
            resolved = _resolve_fix(airport_icao, leg["fix_id"])
            if resolved is not None:
                coords.append([resolved[0], resolved[1]])
        if len(coords) < 2:
            # 좌표를 하나도(또는 하나만) 못 찾은 절차는 선으로 그릴 수 없으므로 제외한다
            # (전체 SID/STAR 조회를 실패시키지 않고 이 절차만 조용히 빠진다).
            continue
        name = proc_id if transition_id in (None, proc_id) else f"{proc_id} ({transition_id})"
        result.append({"proc": proc, "name": name, "airport": airport_icao, "coords": coords})
    return result


def fetch_sidstar(airport: str | None = None) -> list[dict]:
    """[{proc, name, airport, coords:[[lat,lon],...]}, ...] — 예전 sidstar.json 응답과 동일 모양.

    proc: 1=SID(파랑), 2=STAR(녹색). 좌표는 fix_id를 터미널/엔루트 지점→navaid 순으로
    해석해 조립한다(_resolve_fix). 지점 인덱스는 프로세스 생애주기 동안 캐시되므로 이
    함수 자체는 캐시하지 않고 매번 절차 행만 다시 조회한다(airport 필터가 있어 가볍다).
    """
    if airport:
        # load_firs/load_airports의 icao 정규화(strip+upper)와 동일 관례 — 안 하면
        # ?airport=rksi가 조용히 빈 배열을 반환한다(Postgres 텍스트 비교는 대소문자 구분).
        airport = airport.strip().upper()
    sid_rows = _procedure_rows("reference_sid", "sid_id", airport)
    star_rows = _procedure_rows("reference_star", "star_id", airport)
    return _build_procedures(sid_rows, "sid_id", 1) + _build_procedures(star_rows, "star_id", 2)
