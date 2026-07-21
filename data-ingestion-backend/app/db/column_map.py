"""논리 컬럼명(스킬 산출물 CSV 헤더) → DB 물리 컬럼명(snake_case) 단일 출처.

data-ingestion-backend/docs/DB스키마.md §9(물리 컬럼 매핑, 확정본)를 그대로 옮긴 것이다.
`models.py`(Table 정의)와, 다음 라운드의 `loaders.py`(CSV→DB 적재)가 반드시 이 모듈만 참조한다.
양쪽에 컬럼명 문자열을 중복 정의하지 않는다(§9 규칙).

각 값은 `(논리명, 물리명)` 튜플의 순서 있는 튜플이다 — 순서는 실제 산출물 헤더 순서와 동일하게 유지한다.
"""

from __future__ import annotations

# --- processed_* 6종 (DB스키마.md §9.1~9.6) ---

PROCESSED_FLIGHT_DATA: tuple[tuple[str, str], ...] = (
    ("DATE", "date"),
    ("CALLSIGN", "callsign"),
    ("SSR", "ssr"),
    ("DEPT", "dept"),
    ("DEST", "dest"),
    ("EOBT", "eobt"),
    ("F_TYPE", "f_type"),
    ("ATD", "atd"),
    ("TEET", "teet"),
    ("RFL", "rfl"),
    ("AFL", "afl"),
    ("XFL", "xfl"),
    ("CFL", "cfl"),
    ("A_TYPE", "a_type"),
    ("LINE", "line"),
    ("ENTRY_FIR", "entry_fir"),
    ("ENTRY_DATETIME", "entry_datetime"),
    ("EXIT_FIR", "exit_fir"),
    ("EXIT_DATETIME", "exit_datetime"),
    ("확장루트", "ext_route"),
    ("FULL_ROUTE", "full_route"),
    ("FIR_ENROUTE", "fir_enroute"),
    ("ALT_DEST", "alt_dest"),
    ("고유ID", "unique_id"),
    ("REG NO", "reg_no"),
    ("OTHER", "other"),
)

PROCESSED_ACDM_DEPARTURE: tuple[tuple[str, str], ...] = (
    ("operation_date", "operation_date"),
    ("airport_icao", "airport_icao"),
    ("flight_icao", "flight_icao"),
    ("airline_icao", "airline_icao"),
    ("counterpart_airport_icao", "counterpart_airport_icao"),
    ("aircraft_registration", "aircraft_registration"),
    ("aircraft_type", "aircraft_type"),
    ("domestic_international", "domestic_international"),
    ("stand", "stand"),
    ("gate", "gate"),
    ("runway", "runway"),
    ("flight_status", "flight_status"),
    ("exception_status", "exception_status"),
    ("linked_flight_icao", "linked_flight_icao"),
    ("flight_category", "flight_category"),
    ("service_type", "service_type"),
    ("route", "route"),
    ("deice_flag", "deice_flag"),
    ("deice_stand", "deice_stand"),
    ("SOBT", "sobt"),
    ("TOBT", "tobt"),
    ("TTOT", "ttot"),
    ("CTOT", "ctot"),
    ("AOBT", "aobt"),
    ("ATOT", "atot"),
    ("timeline_status", "timeline_status"),
    ("departure_punctuality_min", "departure_punctuality_min"),
    ("taxi_out_additional_min", "taxi_out_additional_min"),
    ("ctot_slot_adherence", "ctot_slot_adherence"),
    ("takeoff_prediction_error_min", "takeoff_prediction_error_min"),
    ("offblock_prediction_error_min", "offblock_prediction_error_min"),
)

PROCESSED_ACDM_ARRIVAL: tuple[tuple[str, str], ...] = (
    ("operation_date", "operation_date"),
    ("airport_icao", "airport_icao"),
    ("flight_icao", "flight_icao"),
    ("airline_icao", "airline_icao"),
    ("counterpart_airport_icao", "counterpart_airport_icao"),
    ("aircraft_registration", "aircraft_registration"),
    ("aircraft_type", "aircraft_type"),
    ("domestic_international", "domestic_international"),
    ("stand", "stand"),
    ("gate", "gate"),
    ("runway", "runway"),
    ("flight_status", "flight_status"),
    ("linked_flight_icao", "linked_flight_icao"),
    ("flight_category", "flight_category"),
    ("service_type", "service_type"),
    ("FIR", "fir"),
    ("APP", "app"),
    ("ELDT", "eldt"),
    ("ALDT", "aldt"),
    ("SIBT", "sibt"),
    ("AIBT", "aibt"),
    ("timeline_status", "timeline_status"),
    ("arrival_punctuality_min", "arrival_punctuality_min"),
    ("actual_taxi_in_min", "actual_taxi_in_min"),
    ("fir_to_app_min", "fir_to_app_min"),
    ("final_approach_min", "final_approach_min"),
    ("landing_prediction_abs_error_min", "landing_prediction_abs_error_min"),
)

PROCESSED_FOIS_DEPARTURE: tuple[tuple[str, str], ...] = (
    ("출발일자", "dep_date"),
    ("출발공항", "dep_airport"),
    ("편명", "flight_no"),
    ("등록부호", "reg_no"),
    ("STD", "std"),
    ("사유", "reason"),
    ("원인대분류", "cause_major"),
    ("원인소분류", "cause_minor"),
    ("원인공정", "cause_process"),
    ("관여주체", "involved_party"),
)

PROCESSED_FOIS_ARRIVAL: tuple[tuple[str, str], ...] = (
    ("도착일자", "arr_date"),
    ("도착공항", "arr_airport"),
    ("편명", "flight_no"),
    ("등록부호", "reg_no"),
    ("STA", "sta"),
    ("사유", "reason"),
    ("원인대분류", "cause_major"),
    ("원인소분류", "cause_minor"),
    ("원인공정", "cause_process"),
    ("관여주체", "involved_party"),
)

PROCESSED_FLOW_MANAGEMENT: tuple[tuple[str, str], ...] = (
    # 실제 산출 CSV 헤더 기준(2026-07-21 실측) — DB스키마.md §9.6은 "기상세부분류"로 적었으나
    # 실제 헤더는 "기상대분류"이고, "원본파일"/"원본시트" 2개 컬럼이 문서에서 누락되어 있었다
    # (코드/실제 산출물이 기준, 스킬연동_레퍼런스.md §0).
    ("흐름관리ID", "flow_id"),
    ("원본파일", "source_file"),
    ("원본시트", "source_sheet"),
    ("원본순번", "source_seq"),
    ("기록일자", "record_date"),
    ("통보시각", "notify_time"),
    ("적용시작일시", "apply_start_dt"),
    ("적용종료일시", "apply_end_dt"),
    ("적용분", "apply_minutes"),
    ("익일시작보정", "next_day_adjusted"),
    ("발신기관", "sender"),
    ("수신기관", "receiver"),
    ("사유코드", "reason_code"),
    ("기상대분류", "wx_category"),
    ("MINIT", "minit"),
    ("MIT", "mit"),
    ("고도속도제한", "alt_speed_limit"),
    ("원본대상", "raw_destination"),
    ("원본항공로", "raw_route"),
    ("원본지점", "raw_fix"),
    ("대상공항", "target_airport"),
    ("대상FIR", "target_fir"),
    ("대상항공로", "target_route"),
    ("대상지점", "target_fix"),
    ("제외공항", "excluded_airport"),
    ("특수범위", "special_scope"),
    ("공간범위유형", "scope_type"),
    ("방향", "direction"),
    ("비고", "remarks"),
    ("CTOT비고", "ctot_note"),
    ("제한내용요약", "restriction_summary"),
    ("품질상태", "quality_status"),
)

PROCESSED_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "processed_flight_data": PROCESSED_FLIGHT_DATA,
    "processed_acdm_departure": PROCESSED_ACDM_DEPARTURE,
    "processed_acdm_arrival": PROCESSED_ACDM_ARRIVAL,
    "processed_fois_departure": PROCESSED_FOIS_DEPARTURE,
    "processed_fois_arrival": PROCESSED_FOIS_ARRIVAL,
    "processed_flow_management": PROCESSED_FLOW_MANAGEMENT,
}

# --- raw_*_rows 7종 계약 컬럼 (DB스키마.md §3.2, §9.7 규칙 적용) ---
# ACDM은 공항마다 원본 컬럼명이 달라 최소 식별 컬럼만 typed로 두고 나머지는 extra_columns로 흡수한다(§3.2).

RAW_FLIGHT_ANALYSIS_ROWS: tuple[tuple[str, str], ...] = (
    ("DATE", "date"),
    ("CALLSIGN", "callsign"),
    ("SSR", "ssr"),
    ("DEPT", "dept"),
    ("DEST", "dest"),
    ("D_EOBT", "d_eobt"),
    ("EOBT", "eobt"),
    ("D_ATD", "d_atd"),
    ("ATD", "atd"),
    ("ENTRY_DATE", "entry_date"),
    ("ENTRY_TIME", "entry_time"),
    ("EXIT_DATE", "exit_date"),
    ("EXIT_TIME", "exit_time"),
    ("RFL", "rfl"),
    ("AFL", "afl"),
    ("XFL", "xfl"),
    ("CFL", "cfl"),
    ("FIR_ENROUTE", "fir_enroute"),
)

RAW_FLIGHT_SEARCH_ROWS: tuple[tuple[str, str], ...] = (
    ("DATE", "date"),
    ("CALLSIGN", "callsign"),
    ("SSR", "ssr"),
    ("REG NO", "reg_no"),
    ("OTHER", "other"),
)

RAW_ACDM_DEPARTURE_ROWS: tuple[tuple[str, str], ...] = (
    ("source_file", "source_file"),
    ("source_date", "source_date"),
    # flight_no/reg_no: 컬럼은 만들어 두되 현재 loaders.py(_build_acdm_raw_records)는 채우지
    # 않는다(공항마다 원본 헤더가 달라 이번 라운드는 시도하지 않음, DB스키마.md §3.2) — 값은
    # 항상 NULL이고 원본 전체는 extra_columns에 그대로 들어간다. 공항별 별칭 매핑을 추가하면
    # 스키마 변경 없이 loaders.py만 고치면 된다.
    ("편명", "flight_no"),
    ("등록부호", "reg_no"),
)

RAW_ACDM_ARRIVAL_ROWS: tuple[tuple[str, str], ...] = RAW_ACDM_DEPARTURE_ROWS

RAW_FOIS_DEPARTURE_ROWS: tuple[tuple[str, str], ...] = (
    # 논리명은 스킬 실제 코드(run_fois_preprocessing.py SOURCE_COLUMNS)의 원본 헤더 그대로 —
    # DB스키마.md §3.2의 "구분/지연시간" 표기는 요약이며 실제 헤더와 다르다(코드가 기준,
    # 스킬연동_레퍼런스.md §0).
    ("번호", "no"),
    ("운항구분", "category"),
    ("출발일자", "dep_date"),
    ("편명", "flight_no"),
    ("기종", "aircraft_type"),
    ("등록부호", "reg_no"),
    ("출발공항", "dep_airport"),
    ("STD", "std"),
    ("ATD", "atd"),
    ("출발지연시간원본", "delay_raw"),
    ("도착공항", "arr_airport"),
    ("도착일자", "arr_date"),
    ("STA", "sta"),
    ("ATA", "ata"),
    ("도착지연시간원본", "delay_raw2"),
    ("지연기준구분", "delay_basis_category"),
    ("사유", "reason"),
)

RAW_FOIS_ARRIVAL_ROWS: tuple[tuple[str, str], ...] = RAW_FOIS_DEPARTURE_ROWS

RAW_FLOW_MANAGEMENT_ROWS: tuple[tuple[str, str], ...] = (
    ("Seq", "seq"),
    ("Date", "date"),
    ("RTime", "rtime"),
    ("Sender", "sender"),
    ("Receiver", "receiver"),
    ("Reasons", "reasons"),
    ("Start", "start_dt"),
    ("End", "end_dt"),
    ("Run", "run"),
    ("MINIT", "minit"),
    ("MIT", "mit"),
    ("Level Capping & G/S", "level_capping_gs"),
    ("Destination", "destination"),
    ("Route", "route"),
    ("Fix", "fix"),
    ("Remarks", "remarks"),
    ("Dir", "dir"),
    ("CTOT/Note", "ctot_note"),
    ("CTOT Pub", "ctot_pub"),
)

RAW_TABLE_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "raw_flight_analysis_rows": RAW_FLIGHT_ANALYSIS_ROWS,
    "raw_flight_search_rows": RAW_FLIGHT_SEARCH_ROWS,
    "raw_acdm_departure_rows": RAW_ACDM_DEPARTURE_ROWS,
    "raw_acdm_arrival_rows": RAW_ACDM_ARRIVAL_ROWS,
    "raw_fois_departure_rows": RAW_FOIS_DEPARTURE_ROWS,
    "raw_fois_arrival_rows": RAW_FOIS_ARRIVAL_ROWS,
    "raw_flow_management_rows": RAW_FLOW_MANAGEMENT_ROWS,
}
