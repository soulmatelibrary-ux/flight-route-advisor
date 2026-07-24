#!/usr/bin/env python3
"""정적 참조 데이터(사전빌드_JSON 8종) → reference_* DB 테이블 1회 이관.

`PORTING_PACKAGE_ROOT/사전빌드_JSON/{firs,firlbl,tca,airways,airports,navaids,waypoints,
acc_sectors}.json`을 읽어 `app.db.reference_tables`(단일 출처) 스키마에 맞춰
truncate-and-reload한다. 원본 JSON은 읽기 전용으로만 다루고 수정하지 않는다(CLAUDE.md §0.1).
업로드 폼/ingestion_runs 감사 추적을 거치지 않는다 — 이 8종은 run_id로 버전 구분할 필요가
없는 정적 마스터 데이터이기 때문(reference_tables.py 모듈 docstring 참고). 재실행해도
안전(idempotent, DELETE 후 재적재).

사용법: python scripts/migrate_static_reference_to_db.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, insert  # noqa: E402

from app.config import settings  # noqa: E402
from app.db.reference_tables import (  # noqa: E402
    reference_acc_boundary,
    reference_acc_sector,
    reference_airport,
    reference_airway,
    reference_fir,
    reference_navaid,
    reference_tca,
    reference_waypoint,
)
from app.db.session import get_engine  # noqa: E402


def _load_json(filename: str) -> object:
    path = settings.porting_package_root / "사전빌드_JSON" / filename
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _build_fir_rows() -> list[dict]:
    firs = _load_json("firs.json")  # [icao, name_en, [poly1_flat, poly2_flat, ...]]
    labels = {row[0]: (row[1], row[2]) for row in _load_json("firlbl.json")}  # icao -> (lat, lon)
    rows = []
    for icao, name_en, polygons in firs:
        label = labels.get(icao)
        rows.append(
            {
                "icao": icao,
                "name_en": name_en,
                "polygons": [_to_pairs(poly) for poly in polygons],
                "label_lat": label[0] if label else None,
                "label_lon": label[1] if label else None,
            }
        )
    return rows


def _to_pairs(flat: list[float]) -> list[list[float]]:
    return [[flat[i], flat[i + 1]] for i in range(0, len(flat), 2)]


def _build_tca_rows() -> list[dict]:
    rows = _load_json("tca.json")  # [name, name_ko, flat_coords]
    return [
        {"name": name, "name_ko": name_ko, "polygon": _to_pairs(flat)}
        for name, name_ko, flat in rows
    ]


def _build_airway_rows() -> list[dict]:
    # loader.py._load_airways_with_seq와 동일한 규칙: seq는 필터링 전 원본 파일 순서 그대로,
    # 같은 ident 안에서 1부터 매긴다(과거 실측 버그 — bbox로 거른 부분집합 위에서 다시 매기면
    # 같은 물리 구간이 요청마다 다른 seq를 받는다). 여기서 한 번만 계산해 저장해 두면
    # Stage 1 조회 시 매번 재계산할 필요가 없다.
    rows = _load_json("airways.json")  # [{n, l, c:[lat_a,lon_a,lat_b,lon_b], ul, ll}, ...]
    seq_by_ident: dict[str, int] = {}
    built = []
    for row in rows:
        ident = row["n"]
        seq_by_ident[ident] = seq_by_ident.get(ident, 0) + 1
        lat_a, lon_a, lat_b, lon_b = row["c"]
        built.append(
            {
                "ident": ident,
                "seq": seq_by_ident[ident],
                "lat_a": lat_a,
                "lon_a": lon_a,
                "lat_b": lat_b,
                "lon_b": lon_b,
                "upper": row.get("ul"),
                "lower": row.get("ll"),
            }
        )
    return built


def _build_airport_rows() -> list[dict]:
    rows = _load_json("airports.json")  # [{i, n, c:[lat,lon], e, t}, ...]
    built = []
    for row in rows:
        lat, lon = row["c"]
        built.append(
            {
                "icao": row["i"],
                "name": row.get("n"),
                "lat": lat,
                "lon": lon,
                "elev_ft": float(row["e"]) if row.get("e") not in (None, "") else None,
                "type": row.get("t"),
            }
        )
    return built


def _build_navaid_rows() -> list[dict]:
    rows = _load_json("navaids.json")  # [{i, n, t, c:[lat,lon], f}, ...]
    built = []
    for row in rows:
        lat, lon = row["c"]
        built.append(
            {
                "ident": row["i"],
                "name": row.get("n"),
                "type": row.get("t"),
                "lat": lat,
                "lon": lon,
                "freq": row.get("f"),
            }
        )
    return built


def _build_waypoint_rows() -> list[dict]:
    rows = _load_json("waypoints.json")  # [ident, lat, lon, country]
    return [
        {"ident": ident, "lat": lat, "lon": lon, "country": country}
        for ident, lat, lon, country in rows
    ]


def _build_acc_sector_rows() -> list[dict]:
    doc = _load_json("acc_sectors.json")  # {acc:{IN:[flat,...],DG:[flat,...]}, sectors:[[id,name,acc,flat],...]}
    sectors = doc.get("sectors", [])
    # seq는 원본 배열 순서를 그대로 보존한다 — analyzeFIR 이식(A4)의 point-in-polygon
    # 배정이 이 순서대로 첫 매치에서 멈추므로(GH/GL처럼 동일 폴리곤을 공유하는 섹터가
    # 있어 순서가 배정 결과를 바꾼다), DB 조회 시에도 반드시 이 순서를 복원해야 한다.
    return [
        {
            "sector_id": sector_id,
            "name_en": name_en,
            "acc": acc,
            "seq": i,
            "polygon": _to_pairs(flat),
        }
        for i, (sector_id, name_en, acc, flat) in enumerate(sectors)
    ]


def _build_acc_boundary_rows() -> list[dict]:
    doc = _load_json("acc_sectors.json")
    acc_map = doc.get("acc", {})
    return [
        {"acc": acc, "polygon": _to_pairs(flat)}
        for acc, polys in acc_map.items()
        for flat in polys
    ]


_BUILDERS = (
    (reference_fir, _build_fir_rows),
    (reference_tca, _build_tca_rows),
    (reference_airway, _build_airway_rows),
    (reference_airport, _build_airport_rows),
    (reference_navaid, _build_navaid_rows),
    (reference_waypoint, _build_waypoint_rows),
    (reference_acc_sector, _build_acc_sector_rows),
    (reference_acc_boundary, _build_acc_boundary_rows),
)


def main() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        for table, builder in _BUILDERS:
            rows = builder()
            conn.execute(delete(table))
            if rows:
                conn.execute(insert(table), rows)
            print(f"{table.name}: {len(rows)}행 적재")


if __name__ == "__main__":
    main()
