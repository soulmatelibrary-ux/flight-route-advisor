#!/usr/bin/env python3
"""Jeppesen(ARINC 424 계열) 항행 DB 원본 CSV 4종 → reference_* DB 테이블 적재.

SID/STAR 절차와 엔루트/터미널 지점 CSV를 읽어 `app.db.reference_tables`(단일 출처) 스키마에
맞춰 truncate-and-reload한다. 지점 2종은 원본의 도분초(DMS) 좌표를 십진(decimal) [lat, lon]로
변환해 저장한다(N/E 양수, S/W 음수 — CLAUDE.md §7 좌표 규약). 재실행해도 안전(idempotent).

AIRAC 주기 갱신마다 새 CSV로 재실행할 수 있다(같은 이유로 truncate-and-reload).

사용법:
    python scripts/ingest_jepp_nav.py \\
        --sid t_jepp_sid_6_6g1_2.csv --star t_jepp_star_6_6g1_2.csv \\
        --waypoint-enroute t_jepp_waypoint_enroute_6_6g1_2.csv \\
        --waypoint-terminal t_jepp_waypoint_terminal_6_6g1_2.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402
from sqlalchemy import delete, insert  # noqa: E402

from app.db.reference_tables import (  # noqa: E402
    reference_sid,
    reference_star,
    reference_waypoint_enroute,
    reference_waypoint_terminal,
)
from app.db.session import get_engine  # noqa: E402

_READ_CSV_KW = {"dtype": "string", "keep_default_na": False, "na_values": [""]}


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _dms_to_decimal(hemisphere: str, deg: str, minute: str, sec: str, hund_secs: str) -> float:
    # 도(deg) + 분(min)/60 + 초(sec)/3600 + 초1/100(hund_secs)/360000, N/E 양수, S/W 음수
    # (실측 샘플로 검증: YEJIN N37 04 39.00 E126 44 13.00 -> 37.0775, 126.7369 — 인천 인근 일치).
    magnitude = (
        float(deg) + float(minute) / 60 + float(sec) / 3600 + float(hund_secs) / 360000
    )
    sign = -1 if hemisphere in ("S", "W") else 1
    return sign * magnitude


def _load_procedure_rows(path: Path, id_column: str) -> list[dict]:
    df = pd.read_csv(path, encoding="utf-8-sig", **_READ_CSV_KW)
    rows = []
    skipped = 0
    for record in df.to_dict(orient="records"):
        try:
            row = {
                "airport_icao": record["airport_icao_id"],
                id_column: record[id_column],
                "route_type": _clean(record.get("route_type")),
                "transition_id": _clean(record.get("transition_id")),
                "sequence_number": int(record["sequence_number"]),
                "fix_id": record["fix_id"],
                "fix_icao_code": _clean(record.get("fix_icao_code")),
                "path_and_termination": _clean(record.get("path_and_termination")),
                "recommended_navaid_id": _clean(record.get("recommended_navaid_id")),
                "center_fix_id": _clean(record.get("center_fix_id")),
                "cycle_date_year": _clean(record.get("cycle_date_year")),
                "cycle_number": _clean(record.get("cycle_number")),
            }
        except (KeyError, TypeError, ValueError):
            # airport_icao_id/id_column/sequence_number/fix_id는 절차 재구성의 필수값 —
            # 빠지거나 정수 변환이 안 되는 행은 이 leg만 제외한다(_load_waypoint_rows와
            # 동일한 원칙: 다음 AIRAC 주기 CSV에 결측이 생겨도 전체 적재가 죽지 않게).
            skipped += 1
            continue
        rows.append(row)
    if skipped:
        print(f"  경고: 필수값 누락/형식 오류로 {skipped}행 제외됨 ({path.name})")
    return rows


def _load_waypoint_rows(path: Path, area_column: str) -> list[dict]:
    df = pd.read_csv(path, encoding="utf-8-sig", **_READ_CSV_KW)
    rows = []
    skipped = 0
    for record in df.to_dict(orient="records"):
        try:
            lat = _dms_to_decimal(
                record["lat_hemisphere"], record["lat_deg"], record["lat_min"],
                record["lat_sec"], record["lat_hund_secs"],
            )
            lon = _dms_to_decimal(
                record["long_hemisphere"], record["long_deg"], record["long_min"],
                record["long_sec"], record["long_hund_secs"],
            )
        except (TypeError, ValueError):
            # 좌표 성분이 비어있는 등 변환 불가 행 — 절차 폴리라인이 그 지점에서 끊기는 정도로
            # 허용하고 전체 적재를 실패시키지 않는다(핵심 설계 결정 §3, 승인된 계획 참고).
            skipped += 1
            continue
        rows.append(
            {
                "waypoint_id": record["waypoint_id"],
                area_column: record[area_column],
                "fir_id": _clean(record.get("fir_id")),
                "name_descr": _clean(record.get("name_descr")),
                "lat": lat,
                "lon": lon,
            }
        )
    if skipped:
        print(f"  경고: 좌표 변환 실패로 {skipped}행 제외됨 ({path.name})")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sid", required=True, type=Path)
    parser.add_argument("--star", required=True, type=Path)
    parser.add_argument("--waypoint-enroute", required=True, type=Path)
    parser.add_argument("--waypoint-terminal", required=True, type=Path)
    args = parser.parse_args()

    jobs = (
        (reference_sid, _load_procedure_rows(args.sid, "sid_id")),
        (reference_star, _load_procedure_rows(args.star, "star_id")),
        (reference_waypoint_enroute, _load_waypoint_rows(args.waypoint_enroute, "icao_code")),
        (reference_waypoint_terminal, _load_waypoint_rows(args.waypoint_terminal, "region_code")),
    )

    engine = get_engine()
    with engine.begin() as conn:
        for table, rows in jobs:
            conn.execute(delete(table))
            if rows:
                conn.execute(insert(table), rows)
            print(f"{table.name}: {len(rows)}행 적재")


if __name__ == "__main__":
    main()
