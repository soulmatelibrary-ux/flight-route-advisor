"""물리 컬럼명 화이트리스트 + 최신본 윈도우(§3.2)용 메타데이터.

물리 컬럼명은 data-ingestion-backend/docs/DB스키마.md §9(확정본)와 동일 소스이며,
data-ingestion-backend/app/db/column_map.py의 PROCESSED_COLUMNS와 물리명 기준으로
일치한다(실측 `\\d <table>` 대조 완료, 2026-07-22). 이 앱은 별도 프로세스/배포이므로
그 모듈을 임포트하지 않고 물리명만 이 파일에 다시 옮겨 담는다 — 이 파일이 이 서비스의
단일 출처다(docs/02-db-integration.md §5).

`db/tables.py`가 실제 DB에서 리플렉션한 Table 중 여기 없는 컬럼/테이블은 절대
참조하지 않는다(동적 SQL에 화이트리스트 밖 이름을 쓰지 않는다 — docs/06-conventions.md
§8 "테이블/컬럼명은 column_map 화이트리스트에서만").
"""

from __future__ import annotations

# --- processed_* 6종 물리 컬럼 (공통 부가 컬럼 id/run_id/source_csv_path/ingested_at 포함) ---

PROCESSED_FLIGHT_DATA: tuple[str, ...] = (
    "id", "run_id", "source_csv_path",
    "date", "callsign", "ssr", "dept", "dest", "eobt", "f_type", "atd", "teet",
    "rfl", "afl", "xfl", "cfl", "a_type", "line", "entry_fir", "entry_datetime",
    "exit_fir", "exit_datetime", "ext_route", "full_route", "fir_enroute",
    "alt_dest", "unique_id", "reg_no", "other",
    "ingested_at",
)

PROCESSED_ACDM_DEPARTURE: tuple[str, ...] = (
    "id", "run_id", "source_csv_path",
    "operation_date", "airport_icao", "flight_icao", "airline_icao",
    "counterpart_airport_icao", "aircraft_registration", "aircraft_type",
    "domestic_international", "stand", "gate", "runway", "flight_status",
    "exception_status", "linked_flight_icao", "flight_category", "service_type",
    "route", "deice_flag", "deice_stand", "sobt", "tobt", "ttot", "ctot", "aobt",
    "atot", "timeline_status", "departure_punctuality_min",
    "taxi_out_additional_min", "ctot_slot_adherence",
    "takeoff_prediction_error_min", "offblock_prediction_error_min",
    "ingested_at",
)

PROCESSED_ACDM_ARRIVAL: tuple[str, ...] = (
    "id", "run_id", "source_csv_path",
    "operation_date", "airport_icao", "flight_icao", "airline_icao",
    "counterpart_airport_icao", "aircraft_registration", "aircraft_type",
    "domestic_international", "stand", "gate", "runway", "flight_status",
    "linked_flight_icao", "flight_category", "service_type", "fir", "app",
    "eldt", "aldt", "sibt", "aibt", "timeline_status",
    "arrival_punctuality_min", "actual_taxi_in_min", "fir_to_app_min",
    "final_approach_min", "landing_prediction_abs_error_min",
    "ingested_at",
)

PROCESSED_FOIS_DEPARTURE: tuple[str, ...] = (
    "id", "run_id", "source_csv_path",
    "dep_date", "dep_airport", "flight_no", "reg_no", "std", "reason",
    "cause_major", "cause_minor", "cause_process", "involved_party",
    "ingested_at",
)

PROCESSED_FOIS_ARRIVAL: tuple[str, ...] = (
    "id", "run_id", "source_csv_path",
    "arr_date", "arr_airport", "flight_no", "reg_no", "sta", "reason",
    "cause_major", "cause_minor", "cause_process", "involved_party",
    "ingested_at",
)

PROCESSED_FLOW_MANAGEMENT: tuple[str, ...] = (
    "id", "run_id", "source_csv_path",
    "flow_id", "source_file", "source_sheet", "source_seq", "record_date",
    "notify_time", "apply_start_dt", "apply_end_dt", "apply_minutes",
    "next_day_adjusted", "sender", "receiver", "reason_code", "wx_category",
    "minit", "mit", "alt_speed_limit", "raw_destination", "raw_route",
    "raw_fix", "target_airport", "target_fir", "target_route", "target_fix",
    "excluded_airport", "special_scope", "scope_type", "direction", "remarks",
    "ctot_note", "restriction_summary", "quality_status",
    "ingested_at",
)

PROCESSED_COLUMNS: dict[str, tuple[str, ...]] = {
    "processed_flight_data": PROCESSED_FLIGHT_DATA,
    "processed_acdm_departure": PROCESSED_ACDM_DEPARTURE,
    "processed_acdm_arrival": PROCESSED_ACDM_ARRIVAL,
    "processed_fois_departure": PROCESSED_FOIS_DEPARTURE,
    "processed_fois_arrival": PROCESSED_FOIS_ARRIVAL,
    "processed_flow_management": PROCESSED_FLOW_MANAGEMENT,
}

# "일자별 최신 run 우선"(docs/02-db-integration.md §3.2) 윈도우 계산에 쓰는 날짜 컬럼.
# processed_flight_data.date는 전체 타임스탬프 문자열("YYYY-MM-DD HH:MM:SS")이라 앞 10자를
# 잘라 달력 날짜로 정규화해야 한다. 나머지는 이미 순수 날짜 문자열("YYYY-MM-DD")이다
# (실측 확인, 2026-07-22).
DATE_COLUMNS: dict[str, str] = {
    "processed_flight_data": "date",
    "processed_acdm_departure": "operation_date",
    "processed_acdm_arrival": "operation_date",
    "processed_fois_departure": "dep_date",
    "processed_fois_arrival": "arr_date",
    "processed_flow_management": "record_date",
}

TABLES_NEEDING_DAY_TRUNCATION: frozenset[str] = frozenset({"processed_flight_data"})

# processed_* 테이블 → ingestion_runs.run_type (체크 제약과 동일 값). latest_run 윈도우의
# 조인 필터(WHERE r.run_type = ...)에 쓴다.
TABLE_RUN_TYPE: dict[str, str] = {
    "processed_flight_data": "flight_data",
    "processed_acdm_departure": "acdm",
    "processed_acdm_arrival": "acdm",
    "processed_fois_departure": "fois",
    "processed_fois_arrival": "fois",
    "processed_flow_management": "flow_management",
}

# --- ingestion_runs (advisor_readonly에는 컬럼 단위 GRANT만 있음, 마이그레이션
# 9e2a5d7c1b4f) — "최신본 뷰" 규약(§3)에 필요한 최소 컬럼만 ---
INGESTION_RUNS_COLUMNS: tuple[str, ...] = (
    "id", "run_type", "status", "finished_at", "validation_summary",
)

# --- reference_* 10종 (참조 데이터 정적 JSON→DB 전환, data-ingestion-backend
# app/db/reference_tables.py가 스키마 단일 출처 — 물리명 기준 여기 그대로 옮김).
# processed_*와 달리 run_id/최신-run 윈도잉이 없는 정적 마스터 데이터라 DATE_COLUMNS/
# TABLE_RUN_TYPE에는 들어가지 않는다.
REFERENCE_COLUMNS: dict[str, tuple[str, ...]] = {
    "reference_fir": ("id", "icao", "name_en", "polygons", "label_lat", "label_lon"),
    "reference_tca": ("id", "name", "name_ko", "polygon"),
    "reference_airway": ("id", "ident", "seq", "lat_a", "lon_a", "lat_b", "lon_b", "upper", "lower"),
    "reference_airport": ("id", "icao", "name", "lat", "lon", "elev_ft", "type"),
    "reference_navaid": ("id", "ident", "name", "type", "lat", "lon", "freq"),
    "reference_waypoint": ("id", "ident", "lat", "lon", "country"),
    "reference_sid": (
        "id", "airport_icao", "sid_id", "route_type", "transition_id", "sequence_number",
        "fix_id", "fix_icao_code", "path_and_termination", "recommended_navaid_id",
        "center_fix_id", "cycle_date_year", "cycle_number",
    ),
    "reference_star": (
        "id", "airport_icao", "star_id", "route_type", "transition_id", "sequence_number",
        "fix_id", "fix_icao_code", "path_and_termination", "recommended_navaid_id",
        "center_fix_id", "cycle_date_year", "cycle_number",
    ),
    "reference_waypoint_enroute": ("id", "waypoint_id", "icao_code", "fir_id", "name_descr", "lat", "lon"),
    "reference_waypoint_terminal": ("id", "waypoint_id", "region_code", "fir_id", "name_descr", "lat", "lon"),
    "reference_acc_sector": ("id", "sector_id", "name_en", "acc", "seq", "polygon"),
    "reference_acc_boundary": ("id", "acc", "polygon"),
    "reference_suas": ("id", "ident", "name", "type", "upper", "lower", "polygon", "region"),
}

# --- advisor 소유 배치 아티팩트(odr2/flow, 파일→DB 통합) 12종. `backend/batch/
# {build_odr2,build_flow}.py`가 별도 쓰기 role(advisor_artifact_writer)로 적재하고, 이
# 화이트리스트는 조회 경로(queries/routes.py·flow_reasoning.py, advisor_readonly로 SELECT)가
# 쓴다. 스키마 단일 출처: data-ingestion-backend alembic `d4f7a91c3e26_*`.
ADVISOR_ODR2_COLUMNS: dict[str, tuple[str, ...]] = {
    "advisor_odr2_od": ("dep", "arr", "total_flights", "data_period", "generated_at"),
    "advisor_odr2_route": (
        "dep", "arr", "rank", "flights", "avg_min", "delay_count", "heavy_count", "cruise_parity",
        # 터미널 신호 스칼라 2종(A6, docs/13 STEP A6 — 완성본 odInfo/ext 이식) — 마이그레이션
        # c3e7a1f6b0d4. 리스트(출발 활주로 분포)는 이 저장소의 완전 정규화 원칙에 따라
        # advisor_odr2_route_runway 자식 테이블로 별도(route_fir/route_fix와 동일 패턴).
        "gate_in", "gate_out",
    ),
    "advisor_odr2_route_fir": ("dep", "arr", "rank", "seq", "fir_icao"),
    "advisor_odr2_route_fix": ("dep", "arr", "rank", "seq", "fix_name"),
    "advisor_odr2_route_runway": ("dep", "arr", "rank", "seq", "runway", "pct"),
    "advisor_odr2_track_point": ("dep", "arr", "rank", "seq", "lat", "lon"),
    "advisor_odr2_full_route_point": ("dep", "arr", "rank", "seq", "lat", "lon"),
}

ADVISOR_FLOW_COLUMNS: dict[str, tuple[str, ...]] = {
    "advisor_flow_od": (
        "dep", "arr", "impact_pct", "affected_flights", "total_flights",
        "on_time_affected", "on_time_normal", "delay_affected_min", "delay_normal_min",
        "data_period", "generated_at",
    ),
    "advisor_flow_od_reason": ("dep", "arr", "seq", "reason_code", "pct"),
    "advisor_flow_od_limit": ("dep", "arr", "seq", "limit_text"),
    "advisor_flow_od_measure": ("dep", "arr", "seq", "measure_id"),
    "advisor_flow_od_hour": ("dep", "arr", "hour", "impact_pct"),
    "advisor_flow_route_group": ("dep", "arr", "route_key", "pct"),
}

# SUAS/MOA 발효시간 파생(A7, docs/13 STEP A7 — 신규 파생이라 reference_*가 아니라 advisor_*
# 네임스페이스, `backend/batch/build_suas.py` 소유, 스키마 단일 출처는 data-ingestion-backend
# alembic `d9f2b4a8c1e6_*`). `ident`로 `reference_suas.ident`와 애플리케이션 레벨 조인.
ADVISOR_SUAS_COLUMNS: dict[str, tuple[str, ...]] = {
    "advisor_suas_schedule": ("ident", "eff_times_raw", "status", "segments", "generated_at"),
}

TABLE_WHITELIST: dict[str, tuple[str, ...]] = {
    **PROCESSED_COLUMNS,
    **REFERENCE_COLUMNS,
    **ADVISOR_ODR2_COLUMNS,
    **ADVISOR_FLOW_COLUMNS,
    **ADVISOR_SUAS_COLUMNS,
    "ingestion_runs": INGESTION_RUNS_COLUMNS,
}
