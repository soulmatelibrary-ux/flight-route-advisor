"""스킬 계약 매직값 집중 모듈 (작업계획서.md §4.3).

원본 폴더명·공항 매핑·날짜 정규식 등 "스킬이 강제하는 계약값"은 스킬 코드가 원본(진실의
소스)이므로 여기 복제하되 한 곳에 모은다. 값이 스킬과 어긋나면 통합테스트(다음 라운드)에서
즉시 드러나야 한다. 근거: data-ingestion-backend/docs/스킬연동_레퍼런스.md §1·§3·§5.
"""

from __future__ import annotations

import re

# 공항 한글 ↔ ICAO (스킬연동_레퍼런스 §3.2 — ACDM 폴더명 접두사 판별 기준)
AIRPORT_KO_TO_ICAO: dict[str, str] = {
    "인천": "RKSI",
    "김포": "RKSS",
    "제주": "RKPC",
    "김해": "RKPK",
}

# ACDM 방향 토큰(폴더명 부분일치 — §3.2)
ACDM_DIRECTION_KO = {
    "departure": "출발",
    "arrival": "도착",
}

# 원본 폴더명(SOURCE_PROJECT_ROOT 기준 상대경로, §5 배치 규칙 표)
SOURCE_SUBDIR = {
    "acdm": "ACDM",
    "fois_departure": "FOIS/비정상운항출발",
    "fois_arrival": "FOIS/비정상운항도착",
    "flight_analysis": "비행자료/비행자료분석",
    "flight_search": "비행자료/비행자료검색",
    "flow_management": "흐름관리일지",
    "spatial": "공간데이터",
}

# 허용 업로드 확장자(스킬별 계약, config.Settings.allowed_extensions와 별개로 스킬 입력 자체의 제약)
ALLOWED_UPLOAD_EXTENSIONS = (".csv", ".xlsx", ".xls")

# Excel 임시파일 접두사(스킬연동_레퍼런스 §3.1) — workspace 배치 시 제외
EXCEL_TEMP_PREFIX = "~$"

# run_type별로 "스킬 스크립트가 직접(변환 없이) 읽을 수 있는" 확장자(스킬 코드의 실제
# glob/suffix 필터 그대로 — preprocess_flight_data.py/run_fois_preprocessing.py/
# run_flow_management_preprocessing.py는 `*.xlsx`만 훑고, merge_acdm_data.py만 `.csv`/`.xlsx`
# 둘 다 훑는다). 이 목록에 없는 업로드 확장자(.xls, 그리고 flight_data/fois/flow_management의
# .csv)는 workspace 배치 시 CONVERT_TARGET_EXTENSION으로 변환한 뒤 배치한다 — 스킬 코드는
# 무수정 원칙이라 스킬이 이해하는 확장자로 파일 쪽을 맞춘다(workspace_builder._convert_to_xlsx).
SKILL_NATIVE_EXTENSIONS: dict[str, tuple[str, ...]] = {
    "flight_data": (".xlsx",),
    "acdm": (".csv", ".xlsx"),
    "fois": (".xlsx",),
    "flow_management": (".xlsx",),
}
CONVERT_TARGET_EXTENSION = ".xlsx"

# 파일명 날짜 정규식 (언더스코어 구분자, 비행자료 전용 — §3.1). 확장자는 업로드 허용 포맷
# 전부(xlsx/xls/csv) 매칭한다 — 실제 워크스페이스 배치 파일명은 스킬 정규식(§3.1, `.xlsx`
# 고정)에 맞춰 항상 재구성되므로(workspace_builder._resolve_filename) 여기서는 날짜만 추출한다.
FLIGHT_ANALYSIS_FILENAME_RE = re.compile(r"^비행자료분석_(\d{8})\.(?:xlsx|xls|csv)$", re.IGNORECASE)
FLIGHT_SEARCH_FILENAME_RE = re.compile(r"^비행자료검색_(\d{8})\.(?:xlsx|xls|csv)$", re.IGNORECASE)

# ACDM 파일 stem 끝 8자리 날짜(§3.2)
ACDM_DATE_SUFFIX_RE = re.compile(r"(\d{8})$")

# 폼에서 받는 날짜 메타(YYYYMMDD) 형식 검증 — workspace_builder 파일명 재구성에 사용
DATE_YYYYMMDD_RE = re.compile(r"^\d{8}$")

# 경로 주입 방지: 파일명에 이 문자가 있으면 즉시 거부(docs/06 §8)
PATH_INJECTION_RE = re.compile(r"(\.\.|[/\\])")

# 날짜 구분자(스킬연동_레퍼런스 §1.3): flight_data만 언더스코어, 나머지는 하이픈
DATE_SEPARATOR = {
    "flight_data": "_",
    "acdm": "-",
    "fois": "-",
    "flow_management": "-",
}

# 실행 환경변수(스킬연동_레퍼런스 §1.6)
SKILL_SUBPROCESS_ENV_EXTRA = {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}

# FOIS 원본 시트 위치기준 표준 컬럼(run_fois_preprocessing.py SOURCE_COLUMNS 그대로 —
# 원본 헤더는 "지연시간"이 두 번 등장해 pandas가 자동으로 다르게 바꾸므로, 스킬처럼 헤더
# 텍스트를 무시하고 위치로 강제 부여한다). raw 적재(loaders.py)가 이 순서로 읽는다.
FOIS_SOURCE_COLUMNS = (
    "번호", "운항구분", "출발일자", "편명", "기종", "등록부호", "출발공항",
    "STD", "ATD", "출발지연시간원본", "도착공항", "도착일자", "STA", "ATA",
    "도착지연시간원본", "지연기준구분", "사유",
)

# 흐름관리일지 헤더 자동탐지 토큰(run_flow_management_preprocessing.py locate_header 그대로) —
# 상위 20행 내 이 4개 컬럼명이 모두 있는 행을 헤더로 삼는다.
FLOW_MANAGEMENT_HEADER_TOKENS = frozenset({"Seq", "Date", "Start", "End"})
FLOW_MANAGEMENT_HEADER_SCAN_ROWS = 20
