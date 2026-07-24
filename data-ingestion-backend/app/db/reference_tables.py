"""정적 참조 데이터(공역·항공로·지점·SID/STAR) DB 테이블 정의 — 단일 출처.

`processed_*`(운영 일자별 적재, run_id로 버전 구분)와는 성격이 다르다: 이 12개 테이블은
run_id/최신-run 윈도잉 없이 `scripts/migrate_static_reference_to_db.py`(기존 사전빌드_JSON
7개 파일 → 8개 테이블, firs.json+firlbl.json이 `reference_fir` 하나로 병합되고
acc_sectors.json이 `reference_acc_sector`+`reference_acc_boundary` 둘로 나뉨)와
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

# --- ACC 관제섹터(docs/13 STEP A4 선행 — 사전빌드 acc_sectors.json, 한국(인천/대구 ACC)만
# 커버하는 정적 데이터, docs/03 §3 acc-sectors). 원본 JSON은 {acc:{IN:[...],DG:[...]},
# sectors:[[sectorId,nameEn,acc,flatCoords],...]} 모양 — 섹터 배정(analyzeFIR 이식,
# point-in-polygon)에 실제로 쓰는 것은 sectors뿐이지만, 문서(03 §3)가 명시한 응답 스키마
# `{acc,sectors}`를 그대로 지키기 위해 acc 경계도 별도 테이블로 함께 이관한다.

reference_acc_sector = sa.Table(
    "reference_acc_sector",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("sector_id", sa.Text, nullable=False),  # 예: "GH","GL","DG" — ACCS.sectors[i][0]
    sa.Column("name_en", sa.Text),
    sa.Column("acc", sa.Text, nullable=False),  # "IN"(인천) | "DG"(대구)
    # 원본 순서 그대로(같은 다각형을 공유하는 GH/GL처럼 순서가 배정 결과에 영향 — analyzeFIR가
    # 배열 순서대로 첫 매치에서 break하는 것을 그대로 재현하려면 순서 보존이 필수).
    sa.Column("seq", sa.Integer, nullable=False),
    sa.Column("polygon", JSONB, nullable=False),  # [[lat, lon], ...]
)
sa.Index("ix_reference_acc_sector_seq", reference_acc_sector.c.seq)

reference_acc_boundary = sa.Table(
    "reference_acc_boundary",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("acc", sa.Text, nullable=False),  # "IN" | "DG"
    sa.Column("polygon", JSONB, nullable=False),  # [[lat, lon], ...] — ACC별 여러 폴리곤 중 하나
)
sa.Index("ix_reference_acc_boundary_acc", reference_acc_boundary.c.acc)

# SUAS/MOA(특수공역) — `사전빌드_JSON/{suas,suas_world}.json`(완성본 빌드 파이프라인이 DAFIF
# 원본(SUAS_PAR.TXT/SUAS.TXT, 세그먼트+SHAP 코드 6종)을 이미 폴리곤으로 풀어놓은 산출물, 원시
# DAFIF 지오메트리를 이 앱이 다시 파싱하지 않는다)을 이관. 두 파일은 ident 기준 완전히
# 겹치지 않는 별도 데이터(한국 240건 vs 세계 18,104건)라 `region`으로 태깅해 한 테이블에 합친다.
# EFF_TIMES(발효시간) 컬럼은 이 폴리곤 산출물에 없다 — docs/13-ai-reasoning-dev-plan.md STEP A7
# (AI 근거화, 별도 게이트) 소관이라 이번 이관 범위에서 제외.
reference_suas = sa.Table(
    "reference_suas",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("ident", sa.Text, nullable=False),
    sa.Column("name", sa.Text),
    sa.Column("type", sa.Text, nullable=False),  # 원본 코드 그대로(P/R/D/A/M/W/T 등), 임의 번역 안 함
    sa.Column("upper", sa.Text),  # 원본 그대로("FL150"/"SURFACE"/"04500AMSL" 등 혼재, 정규화 안 함)
    sa.Column("lower", sa.Text),
    sa.Column("polygon", JSONB, nullable=False),  # [[lat, lon], ...]
    sa.Column("region", sa.Text, nullable=False),  # 'kr' | 'world' — 원본 파일 출처
)
sa.Index("ix_reference_suas_region", reference_suas.c.region)

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
    "reference_acc_sector": reference_acc_sector,
    "reference_acc_boundary": reference_acc_boundary,
    "reference_suas": reference_suas,
}
