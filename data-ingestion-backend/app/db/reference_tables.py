"""정적 참조 데이터(공역·항공로·지점·SID/STAR) DB 테이블 정의 — 단일 출처.

`processed_*`(운영 일자별 적재, run_id로 버전 구분)와는 성격이 다르다: 이 10개 테이블은
run_id/최신-run 윈도잉 없이 `scripts/migrate_static_reference_to_db.py`(기존 사전빌드_JSON
7개 파일 → 6개 테이블, firs.json+firlbl.json이 `reference_fir` 하나로 병합됨)와
`scripts/ingest_jepp_nav.py`(Jeppesen SID/STAR/지점 CSV 4종 → 4개 테이블)가
truncate-and-reload로 채우는 정적 마스터 데이터라 별도 프리픽스(`reference_*`)를 쓴다.
컬럼은 모두 최종 조회에
필요한 값만 담고(원본 그리드 전체가 아님) 좌표는 항상 십진(double precision) [lat, lon] 쌍으로
저장한다(CLAUDE.md §7 좌표 규약).

이 모듈이 스키마의 단일 출처다 — Alembic 마이그레이션(`alembic/versions/*_reference_tables.py`)은
여기서 Table을 가져와 컬럼을 복사(`column.copy()`)해 `op.create_table`을 호출하고, 적재
스크립트는 이 Table 객체로 직접 INSERT한다.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

metadata = sa.MetaData()

reference_fir = sa.Table(
    "reference_fir",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("icao", sa.Text, nullable=False),
    sa.Column("name_en", sa.Text),
    sa.Column("polygons", JSONB, nullable=False),  # [[[lat, lon], ...], ...] (여러 폴리곤 가능)
    sa.Column("label_lat", sa.Float),
    sa.Column("label_lon", sa.Float),
)
sa.Index("ix_reference_fir_icao", reference_fir.c.icao, unique=True)

reference_tca = sa.Table(
    "reference_tca",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("name_ko", sa.Text),
    sa.Column("polygon", JSONB, nullable=False),  # [[lat, lon], ...]
)

reference_airway = sa.Table(
    "reference_airway",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("ident", sa.Text, nullable=False),
    # 원본 사전빌드 JSON 배열 순서 그대로의 구간 순번(같은 ident 안에서 1부터) — 필터링 전
    # 전체 데이터 기준으로 한 번만 부여해야 하므로(과거 실측 버그, loader.py 주석 참조)
    # 적재 스크립트가 로드 시점에 미리 계산해 저장한다(매 조회마다 재계산하지 않음).
    sa.Column("seq", sa.Integer, nullable=False),
    sa.Column("lat_a", sa.Float, nullable=False),
    sa.Column("lon_a", sa.Float, nullable=False),
    sa.Column("lat_b", sa.Float, nullable=False),
    sa.Column("lon_b", sa.Float, nullable=False),
    sa.Column("upper", sa.Text),
    sa.Column("lower", sa.Text),
)
sa.Index("ix_reference_airway_ident", reference_airway.c.ident)

reference_airport = sa.Table(
    "reference_airport",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("icao", sa.Text, nullable=False),
    sa.Column("name", sa.Text),
    sa.Column("lat", sa.Float, nullable=False),
    sa.Column("lon", sa.Float, nullable=False),
    sa.Column("elev_ft", sa.Float),
    sa.Column("type", sa.Text),  # A/B/C/D
)
sa.Index("ix_reference_airport_icao", reference_airport.c.icao)

reference_navaid = sa.Table(
    "reference_navaid",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("ident", sa.Text, nullable=False),
    sa.Column("name", sa.Text),
    sa.Column("type", sa.Text),
    sa.Column("lat", sa.Float, nullable=False),
    sa.Column("lon", sa.Float, nullable=False),
    sa.Column("freq", sa.Text),
)
sa.Index("ix_reference_navaid_ident", reference_navaid.c.ident)

reference_waypoint = sa.Table(
    "reference_waypoint",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("ident", sa.Text, nullable=False),
    sa.Column("lat", sa.Float, nullable=False),
    sa.Column("lon", sa.Float, nullable=False),
    sa.Column("country", sa.Text),
)
sa.Index("ix_reference_waypoint_ident", reference_waypoint.c.ident)

# --- Jeppesen(ARINC 424 계열) SID/STAR/지점 — 원본 CSV 컬럼 중 절차 형상 재구성에 실제로
# 쓰는 것만 남긴다(원본 43/27개 컬럼 전체가 아님 — processed_*가 raw 대비 좁히는 것과 동일한
# 원칙). 지점 2종은 DMS 원본 대신 적재 시점에 계산한 십진 lat/lon만 저장한다.

reference_sid = sa.Table(
    "reference_sid",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("airport_icao", sa.Text, nullable=False),
    sa.Column("sid_id", sa.Text, nullable=False),
    sa.Column("route_type", sa.Text),
    sa.Column("transition_id", sa.Text),
    sa.Column("sequence_number", sa.Integer, nullable=False),
    sa.Column("fix_id", sa.Text, nullable=False),
    sa.Column("fix_icao_code", sa.Text),
    sa.Column("path_and_termination", sa.Text),
    sa.Column("recommended_navaid_id", sa.Text),
    sa.Column("center_fix_id", sa.Text),
    sa.Column("cycle_date_year", sa.Text),
    sa.Column("cycle_number", sa.Text),
)
sa.Index("ix_reference_sid_airport", reference_sid.c.airport_icao)

reference_star = sa.Table(
    "reference_star",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("airport_icao", sa.Text, nullable=False),
    sa.Column("star_id", sa.Text, nullable=False),
    sa.Column("route_type", sa.Text),
    sa.Column("transition_id", sa.Text),
    sa.Column("sequence_number", sa.Integer, nullable=False),
    sa.Column("fix_id", sa.Text, nullable=False),
    sa.Column("fix_icao_code", sa.Text),
    sa.Column("path_and_termination", sa.Text),
    sa.Column("recommended_navaid_id", sa.Text),
    sa.Column("center_fix_id", sa.Text),
    sa.Column("cycle_date_year", sa.Text),
    sa.Column("cycle_number", sa.Text),
)
sa.Index("ix_reference_star_airport", reference_star.c.airport_icao)

reference_waypoint_enroute = sa.Table(
    "reference_waypoint_enroute",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("waypoint_id", sa.Text, nullable=False),
    sa.Column("icao_code", sa.Text),  # 리전 코드(한국 'RK') — ICAO 접두사 아님
    sa.Column("fir_id", sa.Text),
    sa.Column("name_descr", sa.Text),
    sa.Column("lat", sa.Float, nullable=False),
    sa.Column("lon", sa.Float, nullable=False),
)
sa.Index("ix_reference_waypoint_enroute_id_code", reference_waypoint_enroute.c.waypoint_id, reference_waypoint_enroute.c.icao_code)

reference_waypoint_terminal = sa.Table(
    "reference_waypoint_terminal",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("waypoint_id", sa.Text, nullable=False),
    sa.Column("region_code", sa.Text, nullable=False),  # 소속 공항 ICAO
    sa.Column("fir_id", sa.Text),
    sa.Column("name_descr", sa.Text),
    sa.Column("lat", sa.Float, nullable=False),
    sa.Column("lon", sa.Float, nullable=False),
)
sa.Index("ix_reference_waypoint_terminal_id_region", reference_waypoint_terminal.c.waypoint_id, reference_waypoint_terminal.c.region_code)

REFERENCE_TABLES: dict[str, sa.Table] = {
    "reference_fir": reference_fir,
    "reference_tca": reference_tca,
    "reference_airway": reference_airway,
    "reference_airport": reference_airport,
    "reference_navaid": reference_navaid,
    "reference_waypoint": reference_waypoint,
    "reference_sid": reference_sid,
    "reference_star": reference_star,
    "reference_waypoint_enroute": reference_waypoint_enroute,
    "reference_waypoint_terminal": reference_waypoint_terminal,
}
