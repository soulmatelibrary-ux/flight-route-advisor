# DB 스키마 초안

- 문서 버전: 1.2
- 작성일: 2026-07-21
- 대상: PostgreSQL 16 (로컬 Docker → 향후 Supabase 이전 전제)
- 관련 문서: [작업계획서](./작업계획서.md), [스킬연동_레퍼런스](./스킬연동_레퍼런스.md), [기술스택_결정](./기술스택_결정.md), [체크리스트](./체크리스트.md)

## 1. 설계 원칙

1. **raw는 "계약 컬럼(TEXT) + 여분 컬럼(JSONB)" 하이브리드로 저장한다.** ACDM은 공항마다 원본 컬럼명이 조금씩 다르고, FOIS는 중복 헤더를 위치 기준으로 재부여하는 등, 소스 원본 스키마가 완전히 고정되어 있지 않다. 완전 자유 JSONB만 쓰면 조회가 어렵고, 완전 고정 컬럼만 쓰면 스키마 드리프트에 취약하므로 두 방식을 혼합한다.
2. **raw/processed 테이블은 모두 append-only이며 덮어쓰지 않는다.** 이는 `CLAUDE.md`의 "원본 폴더는 수정·삭제하지 않는다"는 원칙을 DB 레이어까지 연장한 것이다. "최신 유효 데이터"는 저장 시점에 갱신하지 않고, 조회 시 `run_id`/기간 기준으로 필터링해서 얻는다.
3. **모든 processed/raw 행은 `run_id`로 태깅**되어 어느 업로드·어느 스킬 실행에서 나왔는지 역추적할 수 있다.
4. **검증에서 제외된 행(`검토필요` 등)은 processed 테이블에 들어가지 않는다.** 대신 건수와 요약을 `ingestion_runs.validation_summary`에 남겨 UI에서 경고로 노출한다.

### 1.1 물리 컬럼명 규칙 (추가)

표에 적은 컬럼명은 "원본/산출물 논리 헤더"이며, 실제 DB 물리 컬럼은 다음 규칙으로 생성한다.

- 소문자 `snake_case`를 사용한다.
- 공백/특수문자/한글 컬럼은 영문 별칭으로 변환한다.
- 원본 헤더 문자열은 `raw_files` 또는 `ingestion_runs.validation_summary` 내 매핑 JSON으로 보존한다.

예시:

- `REG NO` -> `reg_no`
- `Level Capping & G/S` -> `level_capping_gs`
- `출발일자` -> `dep_date`

이 규칙을 적용하면 PostgreSQL에서 매번 이중인용부호를 강제하지 않아도 되고, Alembic/SQLAlchemy 코드 가독성이 높아진다.

## 2. 실행 추적 테이블

### 2.1 `ingestion_runs`

배치 실행(run) 1건 = 업로드 1건에 대한 "전처리 스킬 1회 실행"의 전체 이력.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | UUID PK | run 식별자. `raw_*_rows`/`processed_*`가 참조하는 `run_id`와 동일 |
| `run_type` | TEXT | `flight_data` \| `acdm` \| `fois` \| `flow_management` |
| `status` | TEXT | `QUEUED` \| `RUNNING` \| `SUCCESS` \| `VALIDATION_FAILED` \| `FAILED` |
| `idempotency_key` | TEXT NULL | 동일 요청 재시도 제어용 키 |
| `error_code` | TEXT NULL | 실패 분류 코드(`INPUT_VALIDATION`, `SKILL_EXIT_NONZERO` 등) |
| `triggered_by` | TEXT | 업로드한 사용자 식별자(1인 운영이라도 기록, 계정 확장 대비) |
| `workspace_path` | TEXT | 이번 run 전용 임시 workspace 절대경로(run마다 격리) |
| `skill_version` | TEXT | 실행한 스킬 스크립트의 버전/커밋 식별자(재현성 확보) |
| `cli_command` | TEXT | 실제 실행한 명령 전체(디버깅/재현용) |
| `started_at` | TIMESTAMPTZ | |
| `finished_at` | TIMESTAMPTZ | |
| `output_paths` | JSONB | 스킬이 만든 최종 CSV/검증 JSON 경로 목록 |
| `validation_summary` | JSONB | 검증 스크립트 결과 요약(행수, 검토필요 건수, 결측 통계 등) |
| `error_message` | TEXT | 실패 시 예외/오류 메시지 |

권장 제약조건:

- `CHECK (status IN ('QUEUED','RUNNING','SUCCESS','VALIDATION_FAILED','FAILED'))`
- `CHECK (run_type IN ('flight_data','acdm','fois','flow_management'))`
- 부분 unique 인덱스: `UNIQUE (idempotency_key) WHERE idempotency_key IS NOT NULL`

### 2.2 `ingestion_run_files`

run과 입력 원본파일(`raw_files`)의 다대다 연결. ACDM처럼 한 run이 여러 파일을 소비하는 경우를 표현한다.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `run_id` | FK → `ingestion_runs.id` | |
| `raw_file_id` | FK → `raw_files.id` | |
| `role` | TEXT | `input` (향후 재처리 시 `reprocess_of` 등으로 확장 가능) |

### 2.3 `ingestion_logs`

run의 상세 로그 라인(로그 조회 페이지에서 "펼쳐보기" 용도).

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `run_id` | FK → `ingestion_runs.id` | |
| `ts` | TIMESTAMPTZ | |
| `level` | TEXT | `INFO` \| `WARN` \| `ERROR` |
| `source` | TEXT | `stdout` \| `stderr` \| `validation` |
| `message` | TEXT | |

## 3. Raw 계층 (원본 그대로 보존)

### 3.1 `raw_files` — 공통 파일 메타 (모든 파일유형 공유)

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | UUID PK | |
| `file_type` | TEXT | `flight_analysis` \| `flight_search` \| `acdm_departure` \| `acdm_arrival` \| `fois_departure` \| `fois_arrival` \| `flow_management` |
| `original_filename` | TEXT | 사용자가 올린 원본 파일명 |
| `stored_relpath` | TEXT | 저장 볼륨 내 경로(원본 아카이브) |
| `sha256` | TEXT | 무결성 확인 및 중복 업로드 탐지 |
| `sheet_name` | TEXT | XLSX인 경우의 시트명(CSV는 NULL) |
| `row_count` | INT | pandas로 읽은 원본 행 수 |
| `uploaded_at` | TIMESTAMPTZ | |

권장 제약조건:

- `CHECK (row_count >= 0)`
- `CHECK (char_length(sha256) = 64)`
- 중복 탐지용 unique 인덱스: `UNIQUE (sha256, file_type, coalesce(sheet_name, ''))`

### 3.2 파일유형별 raw 행 테이블

공통 컬럼: `id BIGSERIAL PK`, `raw_file_id FK → raw_files.id`, `run_id FK → ingestion_runs.id`(비정규화, 조회 편의), `source_row_number INT`, `extra_columns JSONB`, `ingested_at TIMESTAMPTZ`

| 테이블 | 계약 컬럼(TEXT로 저장, 원본 그대로) |
|---|---|
| `raw_flight_analysis_rows` | `DATE, CALLSIGN, SSR, DEPT, DEST, D_EOBT, EOBT, D_ATD, ATD, ENTRY_DATE, ENTRY_TIME, EXIT_DATE, EXIT_TIME, RFL, AFL, XFL, CFL, FIR_ENROUTE` |
| `raw_flight_search_rows` | `DATE, CALLSIGN, SSR, "REG NO", OTHER` |
| `raw_acdm_departure_rows` | 공항마다 원본 컬럼명이 달라 핵심 식별자(`source_file, source_date, source_row_number`, 편명, 등록부호 등 최소 컬럼)만 typed 컬럼으로 두고 나머지는 `extra_columns`로 흡수 |
| `raw_acdm_arrival_rows` | 위와 동일한 방식 |
| `raw_fois_departure_rows` | `번호, 구분, 출발일자, 편명, 기종, 등록부호, 출발공항, STD, ATD, 지연시간, 도착공항, 도착일자, STA, ATA, 지연시간2, 구분2, 사유` (17열, 중복 헤더는 위치 기준 별칭 부여) |
| `raw_fois_arrival_rows` | 위와 동일한 방식 |
| `raw_flow_management_rows` | `Seq, Date, RTime, Sender, Receiver, Reasons, Start, End, Run, MINIT, MIT, "Level Capping & G/S", Destination, Route, Fix, Remarks, Dir, "CTOT/Note", "CTOT Pub"` |

ACDM은 raw 단계에서 완벽한 원본 충실도를 추구하지 않는다 — 표준화는 이미 processed 단계(스킬)가 담당하므로, raw는 "이 run이 어떤 원본 파일·행에서 시작됐는지"를 증빙하는 목적에 집중한다.

## 4. Processed 계층 (스킬 최종 산출물과 1:1 매핑)

공통 컬럼: `id BIGSERIAL PK`, `run_id FK → ingestion_runs.id`, `source_csv_path TEXT`, `ingested_at TIMESTAMPTZ`

| 테이블 | 컬럼(핵심, 실제 산출물 헤더 순서 그대로) |
|---|---|
| `processed_flight_data` | `DATE, CALLSIGN, SSR, DEPT, DEST, EOBT, F_TYPE, ATD, TEET, RFL, AFL, XFL, CFL, A_TYPE, LINE, ENTRY_FIR, ENTRY_DATETIME, EXIT_FIR, EXIT_DATETIME, 확장루트, FULL_ROUTE, FIR_ENROUTE, ALT_DEST, 고유ID, "REG NO", OTHER` |
| `processed_acdm_departure` | `operation_date, airport_icao, flight_icao, airline_icao, counterpart_airport_icao, aircraft_registration, aircraft_type, domestic_international, stand, gate, runway, flight_status, exception_status, linked_flight_icao, flight_category, service_type, route, deice_flag, deice_stand, SOBT, TOBT, TTOT, CTOT, AOBT, ATOT, timeline_status, departure_punctuality_min, taxi_out_additional_min, ctot_slot_adherence, takeoff_prediction_error_min, offblock_prediction_error_min` |
| `processed_acdm_arrival` | `operation_date, airport_icao, flight_icao, airline_icao, counterpart_airport_icao, aircraft_registration, aircraft_type, domestic_international, stand, gate, runway, flight_status, linked_flight_icao, flight_category, service_type, FIR, APP, ELDT, ALDT, SIBT, AIBT, timeline_status, arrival_punctuality_min, actual_taxi_in_min, fir_to_app_min, final_approach_min, landing_prediction_abs_error_min` |
| `processed_fois_departure` | `출발일자, 출발공항, 편명, 등록부호, STD, 사유, 원인대분류, 원인소분류, 원인공정, 관여주체` |
| `processed_fois_arrival` | `도착일자, 도착공항, 편명, 등록부호, STA, 사유, 원인대분류, 원인소분류, 원인공정, 관여주체` |
| `processed_flow_management` | `흐름관리ID, 원본파일, 원본시트, 원본순번, 기록일자, 통보시각, 적용시작일시, 적용종료일시, 적용분, 익일시작보정, 발신기관, 수신기관, 사유코드, 기상대분류, MINIT, MIT, 고도속도제한, 원본대상, 원본항공로, 원본지점, 대상공항, 대상FIR, 대상항공로, 대상지점, 제외공항, 특수범위, 공간범위유형, 방향, 비고, CTOT비고, 제한내용요약, 품질상태` |

> `timeline_status='검토필요'`처럼 스킬이 최종 CSV에서 이미 제외한 행은 processed 테이블에 존재하지 않는다. 제외 건수는 `ingestion_runs.validation_summary`에 기록해 웹 UI에 노출한다.

### 4.1 범위 제외 — 흐름관리 영향상세(통합데이터 결합) 테이블

`흐름관리영향상세_*.csv`(비행자료+ACDM+FOIS 통합데이터에 흐름관리 영향을 결합한 결과)를 담을 `processed_flow_management_impact_detail` 테이블은 **이번 1단계 스키마에 포함하지 않는다.** 이 결합의 입력인 `비행경로추천통합데이터.csv`를 만드는 "통합 스킬"이 아직 존재하지 않기 때문이다(`00_시작안내/README.md`에 명시된 알려진 갭). 통합 스킬이 만들어지는 단계에서 이 테이블과 `processed_flight_route_integrated`(통합데이터 테이블)를 함께 추가한다.

## 5. 관계 및 추적 경로

```text
ingestion_runs (1) ──< ingestion_run_files >── (N) raw_files
      │                                              │
      │ run_id                                       │ raw_file_id
      ▼                                              ▼
processed_*  (run_id로 연결)              raw_*_rows (raw_file_id로 연결)
      │
      └── source_csv_path로 어느 스킬 산출물에서 적재됐는지 확인 가능
```

예시 역추적: `processed_acdm_departure` 행 하나 → `run_id`로 `ingestion_runs` 조회 → `ingestion_run_files`로 해당 run이 소비한 `raw_files` 목록 확인 → 각 `raw_file_id`로 `raw_acdm_departure_rows`에서 원본 행까지 확인. 즉 "이 processed 행이 어느 업로드 파일의 몇 번째 원본 행에서 나왔는지"를 항상 역추적할 수 있다.

## 6. 인덱스 권장

- 모든 `processed_*`, `raw_*_rows` 테이블: `run_id`에 인덱스 (run별 조회/삭제 대비)
- `ingestion_runs`: `status`, `run_type`, `started_at`에 인덱스 (로그 목록 페이지 필터링용)
- `processed_flight_data`: `DATE`, `CALLSIGN`, `SSR`에 인덱스 (기간/편명 조회용)
- `processed_acdm_departure`/`arrival`: `operation_date`, `airport_icao`에 인덱스
- `processed_fois_departure`/`arrival`: `출발일자`/`도착일자`, `출발공항`/`도착공항`에 인덱스
- `raw_files`: `sha256`에 unique 인덱스 후보 (중복 업로드 탐지 정책 확정 시 적용, 체크리스트 Phase 4 참고)

## 7. Supabase 이전 시 고려사항 (요약)

상세는 [작업계획서](./작업계획서.md) 7장 리스크 참고. 스키마 관점에서는:

- Alembic 마이그레이션은 Supabase의 **direct connection**(pooler 아님)으로 실행해야 DDL이 안전하다.
- 이번 스키마는 RLS(Row Level Security)를 전제하지 않는다 — 서버 사이드에서 service role로만 접근하는 구조이므로 1단계에서는 RLS 비활성 상태를 유지한다.
- JSONB(`extra_columns`) 컬럼은 표준 PostgreSQL 기능이라 Supabase 이전 시 별도 변환이 필요 없다.

## 8. 상태 전이/트랜잭션 규칙 (추가)

구현 시 아래를 스키마 정책으로 본다.

1. 상태 전이 허용: `QUEUED -> RUNNING -> SUCCESS|VALIDATION_FAILED|FAILED`
2. 종료 상태에서 역전이 금지(애플리케이션 레벨 검증)
3. `raw` 적재와 `processed` 적재는 별도 트랜잭션으로 처리
4. `processed_*` 적재는 반드시 `ingestion_runs.status='RUNNING'`에서만 수행

## 9. 물리 컬럼 매핑 (models.py·loaders.py 공용 단일 출처)

아래 표는 **스킬이 만든 CSV 헤더(논리명) → DB 물리 컬럼(snake_case)** 매핑의 확정본이다. `models.py`의 `Table` 정의와 `loaders.py`의 CSV→DB 적재는 반드시 이 매핑을 공유한다(양쪽에 문자열을 중복 정의하지 않는다). 논리명은 원본 헤더 그대로이며, 순서도 산출물 헤더 순서와 동일하다. 별도 지정이 없으면 모든 컬럼 타입은 `TEXT`로 적재하고(원본 충실도 우선), 숫자/일시 파생은 분석 단계에서 뷰/캐스팅으로 처리한다.

> 공통 부가 컬럼(모든 processed 테이블): `id BIGSERIAL PK`, `run_id UUID FK`, `source_csv_path TEXT`, `ingested_at TIMESTAMPTZ`. 아래 표에는 데이터 컬럼만 나열한다.

### 9.1 `processed_flight_data` (논리 26열)

| 논리명(CSV 헤더) | 물리 컬럼 | 논리명 | 물리 컬럼 |
|---|---|---|---|
| DATE | `date` | ENTRY_FIR | `entry_fir` |
| CALLSIGN | `callsign` | ENTRY_DATETIME | `entry_datetime` |
| SSR | `ssr` | EXIT_FIR | `exit_fir` |
| DEPT | `dept` | EXIT_DATETIME | `exit_datetime` |
| DEST | `dest` | 확장루트 | `ext_route` |
| EOBT | `eobt` | FULL_ROUTE | `full_route` |
| F_TYPE | `f_type` | FIR_ENROUTE | `fir_enroute` |
| ATD | `atd` | ALT_DEST | `alt_dest` |
| TEET | `teet` | 고유ID | `unique_id` |
| RFL | `rfl` | REG NO | `reg_no` |
| AFL | `afl` | OTHER | `other` |
| XFL | `xfl` | | |
| CFL | `cfl` | | |
| A_TYPE | `a_type` | | |
| LINE | `line` | | |

- `unique_id`(고유ID)에 인덱스. 동일성 검증 정렬키로 사용.

### 9.2 `processed_acdm_departure` (논리 31열)

논리명이 이미 대부분 영문이다. 규칙: 그대로 소문자화, 약어 대문자(`SOBT` 등)는 소문자.

`operation_date, airport_icao, flight_icao, airline_icao, counterpart_airport_icao, aircraft_registration, aircraft_type, domestic_international, stand, gate, runway, flight_status, exception_status, linked_flight_icao, flight_category, service_type, route, deice_flag, deice_stand` → 동일(소문자 유지).

시각/지표 컬럼: `SOBT→sobt, TOBT→tobt, TTOT→ttot, CTOT→ctot, AOBT→aobt, ATOT→atot, timeline_status→timeline_status, departure_punctuality_min, taxi_out_additional_min, ctot_slot_adherence, takeoff_prediction_error_min, offblock_prediction_error_min`.

- 인덱스: `operation_date`, `airport_icao`, `flight_icao`(정렬키).

### 9.3 `processed_acdm_arrival` (논리 27열)

`operation_date, airport_icao, flight_icao, airline_icao, counterpart_airport_icao, aircraft_registration, aircraft_type, domestic_international, stand, gate, runway, flight_status, linked_flight_icao, flight_category, service_type` → 동일(소문자 유지).

시각/지표: `FIR→fir, APP→app, ELDT→eldt, ALDT→aldt, SIBT→sibt, AIBT→aibt, timeline_status, arrival_punctuality_min, actual_taxi_in_min, fir_to_app_min, final_approach_min, landing_prediction_abs_error_min`.

- 인덱스: `operation_date`, `airport_icao`, `flight_icao`.

### 9.4 `processed_fois_departure` (논리 10열)

| 논리명 | 물리 컬럼 | 논리명 | 물리 컬럼 |
|---|---|---|---|
| 출발일자 | `dep_date` | 원인대분류 | `cause_major` |
| 출발공항 | `dep_airport` | 원인소분류 | `cause_minor` |
| 편명 | `flight_no` | 원인공정 | `cause_process` |
| 등록부호 | `reg_no` | 관여주체 | `involved_party` |
| STD | `std` | | |
| 사유 | `reason` | | |

- 인덱스: `dep_date`, `dep_airport`. 정렬키: `flight_no + dep_date`.

### 9.5 `processed_fois_arrival` (논리 10열)

`processed_fois_departure`와 동일 구조에서 출발→도착만 다르다.

| 논리명 | 물리 컬럼 |
|---|---|
| 도착일자 | `arr_date` |
| 도착공항 | `arr_airport` |
| 편명 | `flight_no` |
| 등록부호 | `reg_no` |
| STA | `sta` |
| 사유 | `reason` |
| 원인대분류 | `cause_major` |
| 원인소분류 | `cause_minor` |
| 원인공정 | `cause_process` |
| 관여주체 | `involved_party` |

- 인덱스: `arr_date`, `arr_airport`. 정렬키: `flight_no + arr_date`.

### 9.6 `processed_flow_management` (논리 32열)

> 2026-07-21 재검증: 스킬(`run_flow_management_preprocessing.py`)을 직접 재실행한 독립 기준선과
> 대조해 `원본파일`/`원본시트` 2개 컬럼과 `기상대분류`(과거 이 표는 `기상세부분류`로 적었으나
> 실제 산출물 명칭이 다름)로 갱신함 — 코드(`app/db/column_map.py`)가 이미 이 갱신 상태이고
> 이 문서가 뒤처져 있었다(`app.db.column_map`이 단일 출처, §9 총론 규칙).

| 논리명 | 물리 컬럼 | 논리명 | 물리 컬럼 |
|---|---|---|---|
| 흐름관리ID | `flow_id` | 원본대상 | `raw_destination` |
| 원본파일 | `source_file` | 원본항공로 | `raw_route` |
| 원본시트 | `source_sheet` | 원본지점 | `raw_fix` |
| 원본순번 | `source_seq` | 대상공항 | `target_airport` |
| 기록일자 | `record_date` | 대상FIR | `target_fir` |
| 통보시각 | `notify_time` | 대상항공로 | `target_route` |
| 적용시작일시 | `apply_start_dt` | 대상지점 | `target_fix` |
| 적용종료일시 | `apply_end_dt` | 제외공항 | `excluded_airport` |
| 적용분 | `apply_minutes` | 특수범위 | `special_scope` |
| 익일시작보정 | `next_day_adjusted` | 공간범위유형 | `scope_type` |
| 발신기관 | `sender` | 방향 | `direction` |
| 수신기관 | `receiver` | 비고 | `remarks` |
| 사유코드 | `reason_code` | CTOT비고 | `ctot_note` |
| 기상대분류 | `wx_category` | 제한내용요약 | `restriction_summary` |
| MINIT | `minit` | 품질상태 | `quality_status` |
| MIT | `mit` | | |
| 고도속도제한 | `alt_speed_limit` | | |

- 인덱스: `flow_id`(정렬키), `record_date`, `apply_start_dt`.

### 9.7 raw 테이블 물리 컬럼 규칙

raw 테이블은 원본 충실도가 목적이므로, 계약 컬럼도 §1.1 규칙(snake_case, 예: `REG NO→reg_no`, `Level Capping & G/S→level_capping_gs`, `CTOT/Note→ctot_note`, `CTOT Pub→ctot_pub`)으로 물리명을 만들되, **원본 헤더 문자열 원문은 `raw_files`에 매핑 JSON으로 함께 저장**해 추적성을 남긴다. 계약 외 여분 컬럼은 전부 `extra_columns JSONB`로 흡수한다.

> 이 매핑은 확정 결정이다. 스킬 산출물 헤더가 바뀌면 이 표와 `models.py`를 함께 갱신하고, 통합테스트(작업계획서 §10)에서 헤더 불일치가 즉시 드러나게 한다.
