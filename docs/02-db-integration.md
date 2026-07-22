# 02. 전처리 DB 연동 설계 ★

- 문서 버전: 1.1
- 작성일: 2026-07-21
- 대상: 이 서비스의 백엔드를 구현할 개발자
- 관련 문서: [01-architecture](./01-architecture.md), [03-backend-api](./03-backend-api.md), [07-checklist](./07-checklist.md)
- 연동 상대편(원천, 미러): [../data-ingestion-backend/docs/DB스키마.md](../data-ingestion-backend/docs/DB스키마.md) (진실원: `데이터전처리기술이식/data-ingestion-backend/docs/`)

이 문서는 **`데이터전처리기술이식` 프로젝트가 DB화되었을 때 그 DB와 연동하는 방법**을 구체적으로 규정한다. 이 서비스는 그 DB의 **읽기 전용 소비자**다.

## 1. 연동 원칙

1. **읽기 전용.** 이 서비스는 DDL·INSERT·UPDATE를 하지 않는다. 스키마와 데이터의 소유·적재는 전처리 백엔드의 책임이다.
2. **스키마 공유, 소유 분리.** 같은 PostgreSQL의 같은 테이블을 보되, 이 서비스는 별도 **read-only DB role**로만 접근한다.
3. **append-only 인지.** `processed_*`는 덮어쓰지 않고 누적된다. "최신 유효 데이터"는 **조회 시점에** run/기간으로 결정한다(§3).
4. **컬럼명 단일 출처.** 물리 컬럼명은 [DB스키마 §9](../data-ingestion-backend/docs/DB스키마.md)로 **확정**됨. 논리명↔물리명 매핑을 어댑터 한 곳(`column_map.py`)에 두고 그것을 유일 출처로 쓴다(§5).
5. **시각은 KST 그대로.** 원자료가 KST이며 재변환(+9) 금지(전처리·원본 서비스 공통 규약).

## 2. 소비 대상 테이블 → 서비스 기능 매핑

전처리 `DB스키마.md` 4장의 `processed_*` 6개 테이블을 소비한다. (raw_* 는 소비하지 않음 — 추적성 전용)

| processed 테이블 | 담긴 내용 | 이 서비스에서의 용도 | 관련 API |
|---|---|---|---|
| `processed_flight_data` | 비행자료 전처리(편명·출도착·EOBT/ATD·TEET·RFL·A_TYPE·ENTRY/EXIT_FIR·확장루트·FULL_ROUTE·FIR_ENROUTE·ALT_DEST 등) | **경로추천(ODR2) 자체 집계의 유일 원천**, 교통량 통계 | `/api/routes`, `/api/routes/od-pairs`, `/api/stats/*` |
| `processed_acdm_departure` | 출발 ACDM(SOBT/TOBT/TTOT/CTOT/AOBT/ATOT·정시성·택시아웃·CTOT 준수 등) | 공항 출발 정시성·KPI 패널 | `/api/airports/{icao}/ops` |
| `processed_acdm_arrival` | 도착 ACDM(ELDT/ALDT/SIBT/AIBT·도착 정시성·택시인·FIR→APP 등) | 공항 도착 정시성·KPI 패널 | `/api/airports/{icao}/ops` |
| `processed_fois_departure` | 출발 비정상운항(사유·원인 대/소분류·공정·관여주체) | 출발 지연원인 분석 | `/api/fois/delays` |
| `processed_fois_arrival` | 도착 비정상운항(동일 구조) | 도착 지연원인 분석 | `/api/fois/delays` |
| `processed_flow_management` | 흐름관리(적용시각·대상 공항/FIR/항공로/지점·MINIT/MIT·고도속도제한·제한내용요약 등) | 흐름관리 조회(자체 전처리분) | `/api/flow-management` |

> **주의 — 통합데이터·영향상세 테이블은 존재하지 않는다.** 전처리 `DB스키마.md` 4.1에 따라 `processed_flight_route_integrated`(통합데이터 84,520×122)와 `processed_flow_management_impact_detail`(흐름관리 영향상세)은 **통합 스킬 부재로 1단계에서 제외**되었다. 따라서 흐름관리의 "비행편 영향" 결합 기능(원본 `문서/03` 흐름관리 탭)은 이 테이블들이 생기기 전까지 구현하지 않는다([05-mvp-scope](./05-mvp-scope.md) 3단계).

## 3. append-only 대응 — "최신본 뷰" 질의 규약

`processed_*`는 실행(run)마다 누적되고 `run_id`로 태깅된다. 단순 `SELECT * FROM processed_flight_data`는 **여러 run의 데이터가 섞여** 잘못된 결과를 낸다. 다음 규약을 강제한다.

### 3.1 원리
- `ingestion_runs`에서 조건에 맞는 **최신 SUCCESS run**을 고른다: `status='SUCCESS'` + `run_type`(예 `flight_data`) + 기간.
- 그 `run_id`로 `processed_*`를 필터/조인한다.

### 3.2 표준 질의 형태 (개념 SQL)

> ⚠ **경고 — 아래 예시는 "run_type당 단일 회차 적재" 가정용이다. 다회차 누적 시 그대로 쓰지 말 것.**
> `processed_*`는 append-only라 매 업로드마다 새 run이 쌓인다. 아래 "최신 run 1개" CTE를 ODR2 다개월 집계(§4)에 그대로 쓰면 **최신 업로드분만 집계되어 과거 데이터가 조용히 누락**되고, 검증 기준치(OD 1,487·경로 3,083, [06 §7](./06-conventions.md))를 재현하지 못한다. 실제 정책은 **데이터 일자 기준 최신 run 우선(일자별 윈도우)**이며, 이는 Stage 1 착수 전 필수 확정 항목이다(§8 O2, [07](./07-checklist.md) Stage 1 게이트).

```sql
-- (단일 회차 가정) run_type별 "가장 최근 성공 run"을 고르는 공통 CTE
WITH latest_run AS (
  SELECT id AS run_id
  FROM ingestion_runs
  WHERE run_type = :run_type
    AND status = 'SUCCESS'
  ORDER BY finished_at DESC
  LIMIT 1
)
SELECT p.*
FROM processed_flight_data p
JOIN latest_run r ON p.run_id = r.run_id;
```
- 기간 스냅샷이 필요하면 `finished_at`/데이터 일자(`DATE`, `operation_date` 등) 범위를 추가한다.
- 여러 run에 걸친 기간(예: 여러 달을 각각 업로드)이라면 "run_type별 최신"이 아니라 **데이터 일자 기준 최신 run 우선**으로 골라야 하므로, 일자별로 가장 최근에 적재된 run을 뽑는 윈도우 질의를 쓴다.

**확정된 정책(2026-07-22)**: 각 `processed_*` 테이블의 날짜 컬럼(`date`/`operation_date`/`dep_date`/`arr_date`/`record_date`) 값별로, 그 값을 포함하는 SUCCESS run들 중 `finished_at`이 가장 늦은 run의 행만 채택한다.

```sql
-- 일자별 최신 run 우선 윈도우 (다회차 누적 대응)
WITH ranked AS (
  SELECT p.*,
         ROW_NUMBER() OVER (PARTITION BY p.<date_col> ORDER BY r.finished_at DESC) AS rn
  FROM processed_flight_data p
  JOIN ingestion_runs r ON p.run_id = r.id
  WHERE r.run_type = 'flight_data' AND r.status = 'SUCCESS'
)
SELECT * FROM ranked WHERE rn = 1;
```
- 겹치지 않는 날짜(예: 신규 월 추가)는 그대로 누적되고, 같은 날짜 정정 재업로드는 최신 run이 그 날짜만 통째로 대체한다.
- `queries/latest_run.py`가 이 윈도우 쿼리를 테이블별 날짜 컬럼(§5 표)에 맞춰 캡슐화하는 단일 출처가 된다(§3.3, DDL 금지 원칙상 DB 뷰 대신 앱 레벨 헬퍼로 처리).

### 3.3 캡슐화
- 이 규약을 매 쿼리에 반복하지 않도록, 서비스 측에서 **읽기 전용 뷰**(예: `v_flight_data_current`)로 감싸는 것을 권장한다.
  - 이 뷰를 전처리 DB에 만들지(전처리 팀 협의), 이 서비스가 접근 가능한 별도 스키마에 만들지는 권한 정책에 따라 결정. **읽기 전용 원칙상 이 서비스는 DDL을 하지 않으므로**, 뷰 생성이 필요하면 전처리 백엔드(소유자)에 요청하거나, 뷰 대신 애플리케이션 레벨 쿼리 헬퍼로 처리한다.
- `validation_summary`(제외된 `검토필요` 건수 등)를 함께 읽어, 데이터 신뢰도 경고를 API 응답 메타에 포함할 수 있다.

## 4. 경로추천(ODR2) 산출 — `processed_flight_data`에서 자체 집계

원본 서비스의 경로추천 데이터 `ODR2`는 원래 비행자료 CSV에서 `3_agg_csv.py`+`4_build_routes2.py`가 생성했다. 통합데이터 테이블이 없으므로, **DB의 `processed_flight_data`를 원천으로 동일 집계를 재현**한다.

### 4.1 입력 컬럼 (모두 `processed_flight_data`에 존재 — 물리명 확정)
논리명 → 물리 컬럼([DB스키마 §9.1](../data-ingestion-backend/docs/DB스키마.md)):
`DATE→date, CALLSIGN→callsign, DEPT→dept, DEST→dest, EOBT→eobt, ATD→atd, TEET→teet, RFL→rfl, A_TYPE→a_type, LINE→line, ENTRY_FIR→entry_fir, ENTRY_DATETIME→entry_datetime, EXIT_FIR→exit_fir, EXIT_DATETIME→exit_datetime, 확장루트→ext_route, FULL_ROUTE→full_route, FIR_ENROUTE→fir_enroute, ALT_DEST→alt_dest, 고유ID→unique_id`
→ 원본 `01_데이터명세.md` B절 및 `02_전처리파이프라인.md` 6장의 집계 입력과 일치. `unique_id`는 동일성/정렬키.

### 4.2 산출 스키마 (원본 `08_임베드데이터_스키마.md` ODR2 그대로 유지)
```
{ "DEP|ARR": [ 총편수, [ 경로옵션, ... ] ] }
경로옵션 = [ 0:n, 1:avgMin, 2:delayCnt, 3:heavyCnt,
             4:[경유 FIR...], 5:[인천 트랙 픽스명...],
             6:[트랙 좌표 flat], 7:[FULL_ROUTE 실궤적 flat], 8:"O"|"E"|"" ]
```
- 집계 키·값: OD별 (FIR_ENROUTE 시퀀스 | 확장루트 시퀀스) 그룹, `n`/TEET평균/지연수(ATD−EOBT 15~600분)/HEAVY수/짝홀 카운트/대표 FULL_ROUTE. (원본 `02-6` 로직 이식)
- 좌표 해석(3단계)·인천 트랙 splice·짝홀 배정은 원본 `04-B/C/E` 알고리즘 그대로.

### 4.3 계산 위치 — 배치 사전집계 (요청 시 실시간 아님)
경로 좌표해석은 무거우므로 요청마다 계산하지 않는다. 두 방식 중 택1(구현 시 확정):

| 방식 | 설명 | 장단 |
|---|---|---|
| **materialized view** | `processed_flight_data` 최신본 위에 OD 집계 MV. 좌표해석까지 SQL로는 무리 → 집계까지만 MV, 좌표해석은 앱단 | DB 표준, 갱신은 REFRESH. 좌표해석 로직을 SQL로 옮기기 어려움 |
| **배치 집계 테이블/아티팩트 (권장)** | 새 run 적재 후 배치가 `3_agg_csv`/`4_build_routes2` 로직(파이썬)을 DB 입력으로 재실행해 `odr2` JSON 아티팩트(또는 별도 집계 테이블) 생성 → API가 그대로 서빙 | 기존 파이썬 로직 재사용, 좌표해석 그대로. 배치 트리거 필요 |

> **읽기 전용 원칙과의 정합**: 집계 결과를 전처리 DB에 쓰지 않는다. 이 서비스 소유의 산출물(집계 테이블은 이 서비스 전용 스키마/DB, 또는 파일 아티팩트)로 둔다. 배치 트리거는 **Stage 0의 새 SUCCESS run(단, `run_type='flight_data'`에 한정 — acdm/fois/flow_management run은 ODR2를 바꾸지 않음) 이후 로컬 pgsql `processed_flight_data`에서 집계**하는 것을 기준으로 한다(초기: 수동/CLI 실행, 이후: 폴링 또는 Stage 0 완료 훅으로 자동화 — [08](./08-setup-and-dev-order.md)).

## 5. 컬럼 어댑터 (물리 컬럼명 — 확정본 반영)

물리 컬럼명은 [DB스키마 §9](../data-ingestion-backend/docs/DB스키마.md)로 **확정**되었다(snake_case, 한글/약어→영문). `column_map.py`가 이 확정본을 **코드 단일 출처**로 담고, API·프론트는 논리명(도메인 개념)으로만 다룬다. 헤더가 바뀌면 이 매핑과 전처리 §9만 함께 갱신한다.

이 서비스가 소비하는 주요 물리 컬럼(확정):

| 테이블 | 핵심 물리 컬럼 (정렬키 굵게) |
|---|---|
| `processed_flight_data` | `date, callsign, ssr, dept, dest, eobt, atd, teet, rfl, a_type, line, entry_fir, entry_datetime, exit_fir, exit_datetime, ext_route, full_route, fir_enroute, alt_dest, `**`unique_id`** |
| `processed_acdm_departure` | `operation_date, airport_icao, flight_icao, sobt, tobt, ttot, ctot, aobt, atot, timeline_status, departure_punctuality_min, taxi_out_additional_min, ctot_slot_adherence` (정렬키 **`operation_date+airport_icao+flight_icao`**) |
| `processed_acdm_arrival` | `operation_date, airport_icao, flight_icao, fir, app, eldt, aldt, sibt, aibt, arrival_punctuality_min, actual_taxi_in_min, fir_to_app_min, final_approach_min` |
| `processed_fois_departure` | `dep_date, dep_airport, flight_no, reg_no, std, reason, cause_major, cause_minor, cause_process, involved_party` (정렬키 **`flight_no+dep_date`**) |
| `processed_fois_arrival` | `arr_date, arr_airport, flight_no, reg_no, sta, reason, cause_major, cause_minor, cause_process, involved_party` (정렬키 **`flight_no+arr_date`**) |
| `processed_flow_management` | `flow_id, record_date, notify_time, apply_start_dt, apply_end_dt, apply_minutes, reason_code, minit, mit, alt_speed_limit, target_airport, target_fir, target_route, target_fix, restriction_summary, quality_status` (정렬키 **`flow_id`**) |

- 공통 부가 컬럼(모든 processed 테이블): `id, run_id, source_csv_path, ingested_at`.
- 응답 JSON은 **키 기반**으로 내보내 프론트가 컬럼 순서/물리명에 의존하지 않게 한다(인덱스 의존과 결별 — [06-conventions](./06-conventions.md)).

## 6. 연결·환경 (로컬 Docker → Supabase)

전처리 `기술스택_결정.md`·`작업계획서.md` 7장과 동일한 이전 전제를 따른다.

| 항목 | 로컬 Docker | Supabase |
|---|---|---|
| `ADVISOR_DATABASE_URL` | `postgresql://advisor_readonly:***@db:5432/aviation` | `postgresql://advisor_readonly:***@<proj>.supabase.co:5432/postgres` |
| SSL | 불필요 | `sslmode=require` |
| 연결 종류 | direct | 조회 트래픽은 **pooler(pgbouncer)** 권장, 단 prepared statement 제약 유의 |
| 커넥션 풀 | 여유 | 저가 티어 동시 커넥션 한도 → SQLAlchemy pool 크기 작게 |
| Role | 읽기 전용 role (`GRANT SELECT`) | 동일. RLS 미사용(전처리 1단계 정책과 일치) |

> **env 변수명(확정, 2026-07-22)**: `ADVISOR_DATABASE_URL`(이 서비스, `advisor_readonly` role)과 data-ingestion-backend의 `DATABASE_URL`(쓰기 role)은 **서로 다른 값이어야 한다**. 같은 값을 공유하면 Stage 0가 재적재를 위해 쓰기 계정을 쓰는 동안 이 서비스도 같은 쓰기 권한을 갖게 되어 최소권한 원칙(§1.2, [06 §3](./06-conventions.md))이 무너진다. `backend/app/config.py`가 `ADVISOR_DATABASE_URL`을 읽는다.

> **Supabase 프로젝트 준비됨(2026-07-22, 미사용 — 기록만)**: 실제 프로젝트 "flight-route-advisor"(`https://aouaqoimieabflyqopvx.supabase.co`) 생성 완료. **Direct connection(IPv6 전용)은 접속 확인 실패**(IPv6 라우팅 안 되는 환경에서 `getaddrinfo` 실패) — **Session pooler(IPv4)로 접속 성공 확인**(`PostgreSQL 17.6`, `aws-0-ap-southeast-1.pooler.supabase.com:5432`, user는 `postgres.<project-ref>` 형식). 저장소 루트 `.env`에 `SUPABASE_PROJECT_URL`/`SUPABASE_PUBLISHABLE_KEY`/`SUPABASE_DB_PASSWORD`/`SUPABASE_POOLER_DATABASE_URL` 4개 값 이미 준비됨(어떤 코드도 아직 참조하지 않음) — 실제 전환 시 이 값을 `session.py`가 읽을 `ADVISOR_DATABASE_URL`/`DATABASE_URL`로 그대로 옮기면 된다. **이후 전환 시 direct connection 대신 pooler를 기본으로 쓸 것**(위 표의 "pooler 권장" 방침과도 일치).

- 연결 로직은 `session.py` 한 곳에 캡슐화해 로컬↔Supabase 전환이 환경변수만으로 되게 한다(전처리 백엔드와 동일 관례).
- 이 서비스는 마이그레이션을 실행하지 않는다(Alembic은 전처리 백엔드 소유).
- **최소권한 GRANT (필수, 테이블 명시, 구현 완료)**: role명 `advisor_readonly`(data-ingestion-backend alembic `360c8b394406_*`). `processed_*` 6종은 테이블 전체 SELECT, `ingestion_runs`는 **컬럼 단위** SELECT(`id, run_type, status, finished_at, validation_summary`만 — `9e2a5d7c1b4f_*`, workspace_path/cli_command/error_message 등 서버 내부 정보는 제외). `raw_*`·`ingestion_logs`에는 GRANT 없음. `ALL TABLES` 일괄 GRANT 금지.
  ```sql
  -- 360c8b394406_advisor_readonly_role_grants.py
  CREATE ROLE advisor_readonly LOGIN PASSWORD :pw;
  GRANT USAGE ON SCHEMA public TO advisor_readonly;
  GRANT SELECT ON processed_flight_data, processed_acdm_departure, processed_acdm_arrival,
                  processed_fois_departure, processed_fois_arrival, processed_flow_management
    TO advisor_readonly;
  -- 9e2a5d7c1b4f_advisor_readonly_ingestion_runs_grant.py
  GRANT SELECT (id, run_type, status, finished_at, validation_summary)
    ON ingestion_runs TO advisor_readonly;
  -- raw_*, ingestion_logs 등에는 GRANT 하지 않는다.
  ```
  실측 확인(2026-07-22): `advisor_readonly`로 `raw_files` SELECT는 permission denied, `ingestion_runs`의 GRANT 밖 컬럼(`workspace_path` 등) SELECT도 permission denied. `backend/app/db/tables.py`는 SQLAlchemy 리플렉션이 `pg_catalog`를 직접 읽어 GRANT와 무관하게 전체 컬럼명을 반환하는 특성이 있어(실측 확인), `include_columns`로 화이트리스트만 리플렉션하도록 앱 레벨에서 한 번 더 제한한다.

## 7. 데이터 신선도·정합성

- **신선도**: 참조 지오메트리는 월·분기 단위, 운항 데이터는 새 업로드(run) 단위로 갱신된다. 경로추천 배치는 새 SUCCESS run 이후 재생성.
- **검증 제외 행 노출**: `ingestion_runs.validation_summary`의 제외 건수(예 ACDM `검토필요`)를 API 메타로 전달해 프론트에서 신뢰도 경고를 띄울 수 있게 한다.
- **역추적**: 필요 시 `run_id`로 `ingestion_runs`→`raw_*`까지 추적 가능(전처리 `DB스키마.md` 5장). 이 서비스는 읽기만 하지만, 특정 통계의 출처 run을 응답에 포함해 감사성을 높인다.

## 8. 열린 이슈 (개발 착수 전 확정 필요)
1. ~~물리 컬럼 별칭~~ → **확정됨**([DB스키마 §9](../data-ingestion-backend/docs/DB스키마.md), §5 반영 완료). 헤더 변경 시에만 재동기화.
2. 경로추천 집계 방식 확정(MV vs 배치 아티팩트) 및 배치 트리거 방법.
3. 최신본 뷰를 전처리 DB에 둘지, 앱단 쿼리로 처리할지(권한 정책).
4. ~~여러 달 데이터가 각각 다른 run으로 적재될 때 "기간 스냅샷" 선택 규칙~~ → **확정됨**(§3.2: 일자별 최신 run 우선 윈도우, 2026-07-22).
5. 통합데이터/영향상세 테이블 완성 시점 → 흐름관리 영향 기능(3단계) 착수 신호.
