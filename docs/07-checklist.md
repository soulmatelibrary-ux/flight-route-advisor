# 07. 구현 체크리스트 (순차 개발 진행 기준점)

- 문서 버전: 2.0
- 작성일: 2026-07-21
- 관련 문서: [00-plan](./00-plan.md), [02-db-integration](./02-db-integration.md), [03-backend-api](./03-backend-api.md), [04-frontend-migration](./04-frontend-migration.md), [05-mvp-scope](./05-mvp-scope.md), [06-conventions](./06-conventions.md), [08-setup-and-dev-order](./08-setup-and-dev-order.md)

> **이 문서가 진행 기준점이다.** 개발 중단 후 재개 시: ① 여기 체크 상태 확인 → ② 마지막 완료 Stage/항목의 관련 문서 재확인 → ③ **다음 미체크 항목부터** 이어서.
> 순서: **Stage 0 전처리 적재 → Stage 1 advisor 백엔드 → Stage 2 프론트**. 이전 Stage의 게이트를 통과해야 다음 Stage가 의미를 가진다.

## 공통 게이트 (모든 Stage·모든 항목에 적용)

- [ ] 하드코딩 없음: URL/포트/임계/색상/컬럼명/경로/자격증명이 env·config·`column_map`에만 존재([06 §1](./06-conventions.md))
- [ ] **시큐어코딩**([06 시큐어코딩 절](./06-conventions.md)): 입력검증·파라미터라이즈드 쿼리·경로주입 차단·비밀정보 비커밋·최소권한 role(테이블 명시 GRANT)·CORS·**요청량 제한(rate limit)**·의존성 고정·오류 비노출
- [ ] **리뷰에이전트 통과**: 항목 완료 전 `code-reviewer`/`senior-code-reviewer`로 ①기능 ②논리 ③예외처리 ④보안 취약점 점검 → 지적 수정 후 체크, 요약 보고

---

## Phase 0 — 문서화 (완료)

- [x] docs/00~08 + CLAUDE.md + result/ + data-ingestion-backend 미러 작성
- [x] docs/09-review-notes.md(문서 리뷰 로그)
- [x] 선행조건 확인: env 루트(`SOURCE_PROJECT_ROOT`/`PORTING_PACKAGE_ROOT`) 접근 가능, 로컬 pgsql 준비([08](./08-setup-and-dev-order.md))

## Phase 1 — 로컬 환경

- [x] `backend/app/config.py` — env→Settings(하드코딩 0), `.env.example`, `config.example.json`
- [x] `docker/docker-compose.yml` — `db(postgres:16)` + `route-api` + `weather`(기존 기상서버)
- [x] `.gitignore`(`.env`, 참조 아티팩트, 15MB HTML 등)
- [x] `docker compose up db` 후 접속 스모크 — `docker compose --env-file .env -f docker/docker-compose.yml up -d db` healthy 확인, `psql`로 `aviation` DB 접속·테이블 18종 조회·`advisor_readonly` role 존재 확인

---

## Stage 0 — 전처리 적재 백엔드 (로컬 pgsql)

> 근거: [data-ingestion-backend/docs](../data-ingestion-backend/docs/) (작업계획서·DB스키마§9·스킬연동_레퍼런스·체크리스트). 코드는 이 저장소에서 개발, 스킬·원본데이터는 `SOURCE_PROJECT_ROOT`(env) 참조.

- [x] Alembic 마이그레이션: `ingestion_runs`·`ingestion_run_files`·`ingestion_logs` (raw_files 포함 — FK 의존 순서상 이 리비전에 통합, `data-ingestion-backend/alembic/versions/82f408ef63f3_*`)
- [x] `raw_files` + `raw_*_rows` 7종 (`68b1cff4780c_*`, `app/db/column_map.py` 단일출처)
- [x] `processed_*` 6종 (물리 컬럼 = [DB스키마 §9](../data-ingestion-backend/docs/DB스키마.md), `ac001a0ab3d9_*`) + 최소권한 role `advisor_readonly`(`360c8b394406_*`)
- [x] 스킬 연동: `registry`(SkillDescriptor)·`workspace_builder`·`skill_runner`(subprocess) — 스킬 코드 무수정(sha256 대조 확인), `flow-management`는 `--no-integrate`. 4종 스킬 모두 실제 원본 샘플로 subprocess 호출 성공 확인(ACDM·FOIS는 출발/도착 양방향 파일이 동시에 있어야 하는 실제 제약을 발견해 반영)
- [x] raw/processed 적재 로더(run_id 태깅, 트랜잭션 분리) — `app/ingestion/loaders.py`(`create_run`/`finish_run`/`load_raw`/`load_processed`), run 단위 트랜잭션(raw/processed 별도), 원본은 서버생성 UUID 파일명으로 `UPLOAD_DIR` 아카이브. 4종 스킬 전체 데이터셋으로 raw+processed 적재 후 (a) **원본 파일 재읽기 값 ↔ raw_*_rows(typed+extra_columns) 완전 일치**, (b) **processed DB 값 ↔ 스킬 산출 CSV 값 완전 일치** 둘 다 pandas로 확인(리포트: [result/phase8-baseline-verification-2026-07-21.md](../result/phase8-baseline-verification-2026-07-21.md) §3)
- [x] 업로드 API/폼 + 로그 조회 페이지(상태 뱃지·검증 경고) — `app/main.py` + `app/routers/{upload,runs}.py` + `app/templates/{upload,runs,run_detail}.html`. `app/ingestion/pipeline.py`(run_ingestion, QUEUED→RUNNING→SUCCESS|VALIDATION_FAILED|FAILED, 프로세스 전역 락으로 순차 실행), idempotency_key 재시도 방지, XLSX 압축폭탄·업로드 용량(개별+합산) 검증. uvicorn 실제 기동 후 curl로 4종 스킬 전부(성공/400 검증실패 2종/스킬 런타임 실패/idempotency 중복방지/CSV 다운로드) HTTP 종단 확인
- [x] **완료 기준**: 원본 폴더 처리 결과가 스킬 직접 실행 기준선과 동일(작업계획서 완료기준, §10.2). 4종 원본 **전체 데이터셋**(부분집합 아님)을 ① 스킬 직접 CLI 재실행(ACDM은 기존 outputs/acdm_timeline_fixed 사용 금지 원칙대로 새로 생성)한 독립 기준선과, ② 백엔드로 처리한 결과(DB 값·백엔드 CSV) 사이에서 processed_* 6개 테이블 전부 행수·전체 컬럼 값 완전 일치 확인(불일치 0건). 리포트: [result/phase8-baseline-verification-2026-07-21.md](../result/phase8-baseline-verification-2026-07-21.md). 과정에서 macOS 파일명 유니코드 정규화(NFD/NFC) 이슈를 발견했으며 백엔드 자체에는 영향 없음(리포트 §1 참고)
- [x] 공통 게이트(하드코딩·시큐어코딩·리뷰에이전트) 통과 — 이번 라운드까지의 전체 산출물(registry/workspace_builder/skill_runner/db스키마/loaders/업로드API/pipeline) 리뷰 3회 통과·지적사항 전부 수정 완료(idempotency 경합, XLSX 압축폭탄 메타데이터 신뢰 문제, 업로드 용량 검증 시점 등 포함)
- [x] **(체크리스트 외 추가) 업로드 포맷 확장**: xlsx 외 xls/csv도 4종 모두 허용 — 스킬 코드는 무수정 원칙이라, 스킬이 직접 못 읽는 확장자(flight_data/fois/flow_management의 xls/csv, ACDM의 xls)는 `workspace_builder._convert_to_xlsx`가 헤더 해석 없이 셀 그리드 그대로 xlsx 컨테이너로 옮겨 담아 배치하고(스킬은 그 결과만 읽음), raw 계층(`loaders._read_raw_dataframe`)은 항상 사용자가 올린 원본 그대로를 읽어 원본 충실도를 유지한다. `xlrd` 의존성 추가(.xls 읽기). 실측 샘플을 csv로 변환해 raw 재읽기 값 일치 확인 + flow_management 1건은 csv 업로드로, `.xls` 픽스처는 실제 `POST /uploads` HTTP 종단으로 전체 파이프라인(workspace 변환→스킬 실행→검증→적재) 실행해 SUCCESS·값 일치 확인(CSV는 시트 개념이 없어 `원본시트` 메타 컬럼만 파일명 기반 값으로 대체됨 — 데이터 손실 아님). 리뷰에이전트 지적사항 수정: 변환 실패(인코딩 등) 시 처리되지 않은 500 대신 `WorkspaceBuildError`로 통일, 배치 파일명 확장자 소문자 정규화(대문자 확장자가 케이스 센시티브 파일시스템에서 스킬 glob에 안 걸리는 문제)
- [x] **(체크리스트 외 추가) run 삭제·재입력 루틴**: 기존에는 삭제 경로가 없어 같은 날짜를 재업로드하면 append-only 특성상 중복이 쌓였고, 완전동일 파일 재업로드는 처리되지 않은 예외(500)로 이어지는 버그도 있었다. `7c1e4a9b2f6d_*` 마이그레이션으로 `ingestion_runs.status`에 `DELETED` 추가 + `deleted_at`/`deleted_by` 컬럼 추가, `loaders.delete_run`(terminal 상태만 삭제 가능, raw_*/processed_*/링크/아카이브 파일 삭제, run 메타데이터 자체는 감사 기록으로 보존 — 사용자 확정 정책), `POST /runs/{run_id}/delete` + `run_detail.html` 삭제 폼. 함께 `load_raw`의 미처리 IntegrityError(중복 파일 재업로드 시 500)를 명확한 400 메시지로 수정. delete_run 가드(이미 DELETED/QUEUED/존재하지 않는 run 거부, 다른 run 데이터 비영향) HTTP 종단(curl) 확인. 리뷰에이전트 지적사항 수정: 이 앱 전체에 인증이 없어 삭제처럼 되돌릴 수 없는 작업만 별도 게이트가 필요하다는 지적에 따라 `INGESTION_DELETE_TOKEN`(미설정 시 기능 자체 비활성화, fail-closed) + `hmac.compare_digest` 검증 추가
- [x] **(체크리스트 외 추가) 적재 데이터 조회 웹페이지 + CSV 다운로드 + 실행 스크립트**: DataGrip 등 외부 DB 클라이언트 없이 이 앱만으로 적재 결과를 확인할 수 있도록 `GET /runs/{run_id}/data/{table_name}`(페이지네이션, run_type별 화이트리스트로 테이블 접근 제한) + `GET /runs/{run_id}/data/{table_name}/download.csv`(청크 스트리밍, BOM 포함) 추가. `data-ingestion-backend/start.sh`(루트 `.env`의 `INGESTION_PORT` 사용, 하드코딩 없음)로 로컬 실행 표준화. uvicorn 실제 기동 후 curl로 페이지네이션·테이블 화이트리스트(다른 run_type 테이블 접근 시 404)·CSV 다운로드(processed/raw 둘 다, extra_columns 포함)·삭제 플로우(토큰 누락/오류/정상 3가지) 전부 HTTP 종단 확인
- [x] **(2026-07-21 후속 리뷰 2차 — 데이터 조회 페이지·CSV export 리뷰)** `senior-code-reviewer`가 47번 항목(조회/다운로드)을 리뷰. 지적사항 2건 수정: ① `download_data_csv`의 `extra_columns`가 `str(dict)`(파이썬 repr, 유효한 JSON 아님)로 나가던 것을 `json.dumps(..., ensure_ascii=False)`로 수정. ② 청크마다 새 커넥션을 열어 내보내는 도중 그 run이 삭제되면 CSV가 조용히 잘리는 문제 — `REPEATABLE READ` 트랜잭션 하나로 전체 export를 묶어(스냅샷 고정) 해결, 실제로 "export 시작 → 다른 트랜잭션에서 delete_run 커밋 → export 계속" 순서로 재현해 잘리지 않음을 확인. 화이트리스트(다른 run_type 테이블 접근 차단)·`INGESTION_DELETE_TOKEN` 로직·start.sh의 `.env` 소싱 안전성은 문제없음으로 확인됨(리뷰 보고서)
- [x] **(2026-07-21 후속 리뷰 잔여 3건 처리)** 48번(1차 후속 리뷰)의 나머지 지적사항: hmac TypeError(비ASCII 토큰 입력 시 500) → `admin_token.encode()`/`delete_token.encode()`로 bytes 비교하도록 수정, 실제로 한글 토큰 입력 시 500이 아니라 403 반환 확인. OFFSET 성능 지적 → `download_data_csv`(전체 export, 실제로 비용이 문제되는 경로)만 커서 기반(`id > last_id`)으로 전환, 인터랙티브 조회(`run_data`)는 임의 페이지 이동이 필요해 OFFSET 유지(의도적 — 코드 주석에 근거 남김). FOIS CSV `skiprows=1` 가정(49번)은 실제 독립 FOIS CSV 샘플이 없어 검증 불가 — 코드 주석으로 명시적 한계 문서화만 하고 미해결로 남김(추후 실제 샘플 확보 시 처리)
- [x] **(체크리스트 외 추가) 테이블 전체 조회 페이지 + 웹 UI 스타일 정리**: run 하나에 매이지 않고 raw_*_rows/processed_* 13종 전체를 훑어볼 수 있는 `GET /tables`(테이블별 총 행수) + `GET /tables/{table_name}`(페이지네이션, 선택적 `run_id` 필터) + `GET /tables/{table_name}/download.csv`(REPEATABLE READ+커서, run_data와 동일 패턴) 추가(`app/routers/tables.py`). 모든 페이지에 공통 상단 탭 네비게이션(`_nav.html`, 현재 위치 강조) 적용, `style.css` 전면 개편(카드 레이아웃·sticky 헤더·줄무늬 테이블·뱃지/버튼 톤 정리). uvicorn 기동 후 curl로 `/tables` 목록·개별 테이블 조회·알 수 없는 테이블 404·`run_id` 필터·CSV(run_id 컬럼 포함) 전부 HTTP 종단 확인, 기존 업로드/처리로그/run상세 페이지도 신규 스타일 적용 후 정상 동작 재확인
- [x] **(회귀 발견·수정 확인) `column_map.py`의 PROCESSED_FLOW_MANAGEMENT 일시적 회귀**: 이번 CSV/CP949 종단 검증 중 flow_management 업로드가 매번 `CSV에 없는 필수 컬럼: ['기상세부분류']`로 실패하는 것을 발견 — 실제 스킬 산출 CSV 헤더를 다시 덤프해 대조한 결과 "원본파일"/"원본시트"/"기상대분류"가 맞고(DB 실제 물리 컬럼 `source_file`/`source_sheet`/`wx_category`와도 일치), "기상세부분류"·누락된 원본파일/원본시트는 잘못된 회귀였음을 재확인. 수정 후 CP949 CSV 업로드 HTTP 종단 재실행(SUCCESS·378행) + 기존 baseline run(6c0183d3-2ad7-4ecc-8d90-da2d550c0f57) 조회로 스키마 일관성 재확인
- [x] **(사용자 요청) `data-ingestion-backend` ↔ `project/result/데이터전처리기술이식` 데이터 동일성 비교 리뷰**: "DB/백엔드 CSV가 원본 스킬 산출물과 데이터가 동일해야 하고, 자료 누적 시 성능·예외처리도 검증해달라"는 요청으로 `app/db/column_map.py`(PROCESSED_COLUMNS 6종) 논리컬럼을 실제 스킬 산출 CSV 헤더와 전수 대조.
  - flight_data/acdm 출발·도착/fois 출발·도착 5종은 컬럼명·순서까지 완전 일치(정적 `outputs/` 샘플 기준).
  - **processed_flow_management만 최초 불일치로 보였으나 오탐이었음**: `SOURCE_PROJECT_ROOT/outputs/흐름관리일지_전처리_*.csv`(정적 샘플, 7/19일자)엔 `원본파일`/`원본시트`가 없고 `기상세부분류`였는데, 이 샘플이 오래된 스킬 실행분이었다. 스킬(`run_flow_management_preprocessing.py`)을 스크래치 디렉터리에 직접 재실행해 만든 진짜 최신 기준선은 32열(원본파일·원본시트·기상대분류 포함)로 `column_map.py`(수정 전 원본)와 정확히 일치 + 기존 [result/phase8-baseline-verification-2026-07-21.md](../result/phase8-baseline-verification-2026-07-21.md)의 "완전 일치" 판정과도 일치. 사용자 지시로 한 차례 `column_map.py`를 정적 샘플 기준으로 고쳤다가, 이 재검증으로 즉시 원상복구함(코드 값 변경 없음).
  - **실제 남아있던 문제는 `docs/DB스키마.md` §4·§9.6 쪽**: 이 문서가 위 스키마 갱신(원본파일/원본시트 추가, 기상세부분류→기상대분류/`wx_detail`→`wx_category`)을 반영하지 못해 코드보다 뒤처져 있었음 — 실제 코드/DB/기준선에 맞게 갱신.
  - **교훈**: `project/result/…/outputs/`의 정적 샘플 CSV는 스킬 재실행 없이 비교 근거로 쓰면 안 됨(ACDM `outputs/acdm_timeline_fixed`가 이미 같은 이유로 금지된 전례를 이번엔 flow_management에도 적용해야 했음). 데이터 누적 성능·예외처리는 지난 라운드(48·49번) 검토·수정 내용 그대로이며 이번 비교에서 새로 발견된 성능 이슈는 없음.
- [x] **(사용자 요청) 스킬 제외 행수 run 로그 기록**: raw/processed 행수가 다른 이유(ACDM `검토필요`, 흐름관리일지 `Seq` 비숫자)를 매번 두 테이블을 비교해 알아내지 않아도 되도록 `pipeline._log_exclusions()` 추가 — ACDM은 스킬 stdout 리포트가 이미 계산해 주는 `{direction}_excluded_review_rows`를 그대로 로그에 옮기고(스킬을 블랙박스로 다루는 원칙상 재계산하지 않음), 흐름관리일지는 스킬 리포트에 제외 전 행수가 없어 우리가 이미 적재해 둔 raw_flow_management_rows 행수와 스킬이 보고한 이벤트 행수의 차로 역산한다. 제외 0건이면 INFO, 1건 이상이면 WARN으로 `ingestion_logs`에 남아 run 상세 페이지에서 바로 보인다. flow_management는 실제 `POST /uploads` HTTP 업로드로 종단 검증(WARN 로그 "Seq가 숫자가 아닌 3행 제외 (원본 381 → 이벤트 378)" 확인), ACDM은 실제 데이터셋이 이미 전량 적재돼 있어 동일 파일 재업로드가 중복 방지 제약에 막히므로 스킬의 실제 stdout 리포트 형태를 그대로 흉내낸 값으로 로그 포맷팅 로직만 별도 검증
- [x] **(체크리스트 외 추가) `/tables` 탭 UI를 fetch 기반 단일 페이지로 전환**: 테이블 이름을 눌러도 페이지 이동 없이 `#table-content`에 바로 표시되도록 `tables.js` + `_table_data_content.html`(본문 조각, `table_data.html`과 공유) + `GET /tables/{table}?partial=1`(조각만 반환) 추가. 라우터가 `partial` 파라미터를 받고도 항상 전체 페이지를 반환하던 미완성 상태를 발견해 `partial=1`일 때 `_table_data_content.html`만 렌더링하도록 수정 — 실제로 fetch 응답에 `<html>` 태그가 없는 순수 조각인지, 일반 요청은 여전히 전체 페이지인지 curl로 확인

## Stage 1 — advisor 백엔드 (FastAPI, 읽기 전용)

> Stage 0가 채운 동일 로컬 pgsql `processed_*` 소비. 근거: [02](./02-db-integration.md)·[03](./03-backend-api.md).

- [x] **[착수 전 필수 확정 — H2/O2]** append-only 다회차 적재 시 "어느 run을 집계·조회 대상으로 삼는가" 정책 확정 — **일자별 최신 run 우선**(각 테이블 날짜 컬럼 값별로 그 값을 포함하는 SUCCESS run 중 `finished_at` 최신 run의 행만 채택, `ROW_NUMBER() OVER (PARTITION BY 날짜컬럼 ORDER BY finished_at DESC)`). 사용자 확정(2026-07-22), 상세 [02 §3.2](./02-db-integration.md). 실제 적재 상태 확인: 현재 4개 run_type 모두 SUCCESS run 1개뿐(flight_data는 2026-01 전체 84,520행) — 다회차 상황은 아직 없으나 향후 재업로드·월별 추가 대비 규칙 확정
- [x] `db/session.py`(읽기전용 엔진, 로컬↔Supabase 분기), `db/tables.py`, `db/column_map.py`([DB스키마 §9] 단일출처) — `ADVISOR_DATABASE_URL`(신규 env, `advisor_readonly` role 전용)로 분리(기존 `DATABASE_URL`은 Stage 0 쓰기 role과 공유돼 있어 최소권한 위반 소지 발견·수정, 마이그레이션 `9e2a5d7c1b4f`로 `ingestion_runs` 컬럼단위 GRANT 보강). `db/tables.py`는 `include_columns`+`resolve_fks=False`로 리플렉션을 화이트리스트에 강제(FK 자동 리플렉션이 `include_columns`를 무시하는 함정 실측 발견·수정). 실제 DB로 리플렉션 성공 + `ingestion_runs` 5컬럼만 노출 확인
- [x] `queries/latest_run.py` — 최신 SUCCESS run 규약(단순 SELECT 금지, [02 §3](./02-db-integration.md)). "일자별 최신 run 우선" 2단계 윈도우(날짜·run_id distinct → 날짜별 승자 run_id → 원 테이블 재조인)로 구현 — 원본 행에 바로 ROW_NUMBER를 걸면 하루 여러 행이 1행으로 뭉개지는 함정을 실측으로 발견해 회피. 현재 단일 run 상태에서 6개 테이블 전부 `latest_view()` 건수 = raw 전체 건수 일치 확인 + 롤백 트랜잭션으로 합성 다회차(겹치는 날짜 대체·안 겹치는 날짜 누적) 시나리오 실제 검증(커밋 없음)
- [x] `reference/loader.py` + `/api/reference/*`(bbox·zoom, 장기 캐시) — `PORTING_PACKAGE_ROOT/사전빌드_JSON`. F5(MVP DoD)에 필요한 6종(firs/tca/airways/airports/navaids/waypoints)만 구현 — sidstar/suas/acc-sectors/firko는 2단계(`05` §3) 또는 원본 소스 부재(firko: 사전빌드_JSON에 파일 자체가 없음, 조작 금지 원칙상 임의 생성하지 않고 갭으로 남김). `main.py`(reference 라우터만 우선 등록, CORS·routes·공통에러는 다음 항목) + uvicorn 기동 후 curl로 6개 엔드포인트 전부 HTTP 종단 확인: 전체건수 대조(FIR 247·항로 89,555·공항 10,030·TCA 63, 전부 baseline 일치), bbox 필터(한반도 bbox→FIR 6개로 축소 확인), icao 필터, 잘못된 bbox→400, waypoints limit 초과→422(FastAPI Query 검증), Cache-Control 헤더, 404. **미완성으로 남긴 부분**: `zoom` 파라미터는 원본 `문서/03`이 구체적 수치 임계값을 규정하지 않아(라벨 표시 임계값만 있고 데이터 씨닝 규칙은 airports "저배율은 민간/공용만"뿐) 현재는 파라미터만 받고 airways/navaids/airports/waypoints 응답에는 아직 적용하지 않음 — 프론트(F5/F9) 실제 연동 시 확정
- [x] `batch/build_odr2.py` — `processed_flight_data`에서 ODR2 집계(집계 로직: `PORTING_PACKAGE_ROOT/전처리스크립트/{3_agg_csv,4_build_routes2}.py` 이식, 원본 무수정). 산출물은 advisor 소유(전처리 DB에 쓰지 않음, `app/reference/artifacts/odr2.json`). **초강력 검증**: `사전빌드_JSON/odr2.json`(원본 CSV 파이프라인이 만든 실제 기준선, 2026-01 데이터)과 필드 단위 diff — OD 1,487·경로 그룹 3,083 둘 다 정확히 일치 + 문서화된 9필드(n/avgMin/delayCnt/heavyCnt/firs/pixes/track/frc/parity) 전부 3,083개 그룹에서 완전 일치(불일치 0건). 과정에서 비결정성 버그 발견·수정: DB fetch에 `ORDER BY`가 없어 편수 동률 그룹의 대표/순위가 실행마다 달라질 수 있었음 → `id` 순 정렬로 원본 CSV 파일 순서 재현(수정 전 3건 불일치 → 수정 후 0건). 참고: 원본 `사전빌드_JSON/odr2.json`에는 상층풍/ACDM 유래로 보이는 추가 필드(9번째 이후, OD별 3번째 원소)가 있으나 04-E(상층풍) 등 2단계 소관이라 이번 포팅 범위에서 제외(문서화된 9필드/2원소 스키마만 재현)
- [x] `/api/routes*`(MVP). `/api/airports/{icao}/ops`·`/api/fois/delays`·`/api/flow-management`은 **2단계로 이관**([05](./05-mvp-scope.md) §3, [03](./03-backend-api.md) §4.2~4.4) — Stage 1 산출물 아님. `queries/routes.py`(odr2.json 아티팩트 로드+캐시, 키 기반 재구성) + `routers/routes.py`(`/api/routes/od-pairs`, `/api/routes?dep=&arr=`, ICAO 4자리 정규식 검증). uvicorn 종단 확인: od-pairs 1,487건·편수 내림차순, VHHH→RKSI 4옵션 정상 반환(track_coords가 [[lat,lon],...] 쌍으로 정상 변환), 잘못된 ICAO→422(FastAPI Query 길이 제약), 없는 OD→404
- [x] 공통 응답 봉투·에러·CORS·관측성 — `app/envelope.py`({data,meta}, docs/03 §2), `app/middleware.py`(레이트리밋: 프로세스 메모리 슬라이딩윈도우, 단일 인스턴스 전제 — 수평확장 시 공유스토어로 교체 필요 명시; 요청 로깅), `main.py`에 CORS(`CORS_ALLOWED_ORIGINS` 화이트리스트, GET만 허용)+전역 예외 핸들러(스택/내부 구현 비노출, 서버 로그에만 상세 기록). 종단 확인: 허용 오리진만 `Access-Control-Allow-Origin` 응답, `RATE_LIMIT_PER_MINUTE=3`로 4번째 요청부터 429 확인
- [x] 규모 대조(FIR 247·항로 89,555·픽스 58,812·공항 10,030·OD 1,487) — 전부 실측 일치(reference/loader.py, batch/build_odr2.py 검증 시 확인)
- [x] 공통 게이트 통과 — `senior-code-reviewer`가 이번 라운드 전체 산출물(db 레이어·latest_run·reference loader/router·batch/build_odr2·routes·envelope·middleware·main·신규 alembic 마이그레이션) 리뷰. 지적사항 5건 전부 수정 확인: ① `load_airways`의 seq가 bbox 필터 후에 매겨져 요청마다 값이 달라짐 → 필터 전 전체 데이터에서 한 번만 계산하도록 수정(필터 전/후 seq 일치 재확인) ② `latest_run.py` 날짜별 승자 선정에 `finished_at` 동률 시 타이브레이커 없음 → `run_id` 2차 정렬 추가 ③ bbox `minLon>maxLon`(날짜변경선 역전 범위)이 조용히 빈 배열을 반환 → 명확한 400 에러로 수정(단, firs 데이터 자체의 ±360 연속좌표는 그대로 허용) ④ reference 라우터가 자산 손상/누락 시 처리되지 않은 500 → routes.py와 동일하게 503으로 통일 ⑤ `build_odr2.py`의 `if tm:`이 TEET=0을 falsy로 오판해 집계 누락 → `is not None`으로 수정. 수정 후 ODR2 기준선 재검증(불일치 여전히 0건) + uvicorn 종단 재확인(전부 정상) 완료. `include_columns`/`resolve_fks=False` 리플렉션 방어, `latest_run.py`의 3단계 윈도우 로직, 미들웨어 동시성은 리뷰에서 문제없음으로 확인됨(리포트 참고)

- [x] **(2026-07-22 3차 리뷰 — 신규 세션 독립 리뷰, 2건 수정)** 이전 리뷰(항목 위 5건)에서 안 걸린 이슈 2건을 새로 발견·수정. ① **에러 응답 포맷이 [03](./03-backend-api.md) §7 "표준 {error:{code,message}}" 계약과 불일치** — 실제로는 라우터 `HTTPException(detail=...)` 전부가 FastAPI 기본값 `{"detail": ...}`로, `main.py` 500 핸들러와 `middleware.py` 429가 각각 `{"error": "<string>"}`로 나가 세 가지 서로 다른 모양이 섞여 있었음. `app/envelope.py`에 `error_envelope(status_code, message)` 추가 + `main.py`에 `StarletteHTTPException`/`RequestValidationError`/`Exception` 3종 전역 핸들러를 새로 등록해 전부 이 함수를 거치도록 통일(라우터 코드는 무수정 — 여전히 `HTTPException(detail=...)`만 던지면 됨). ② **`/api/routes*`(ODR2) 응답의 `data_period`가 항상 null** — §2가 "참조 데이터만 null" 예외를 뒀는데 DB 유래 데이터인 ODR2도 항상 null이었음(배치 산출물 `odr2.json`에 자신이 집계한 날짜 범위를 기록하지 않아 애초에 채울 수 없었음). `batch/build_odr2.py`에 `_data_period()` 추가해 집계에 쓴 실제 날짜 범위를 계산하고, 핵심 아티팩트(`odr2.json`, 원본 파이프라인과 필드 단위로 완전 일치해야 하는 산출물)는 그대로 두고 별도 사이드카 `odr2_meta.json`에만 기록 → `queries/routes.py.data_period()`가 읽어 `routers/routes.py`의 두 엔드포인트 모두 `envelope(..., data_period=...)`로 전달. `run_id`는 "일자별 최신 run 우선" 특성상 날짜별 승자 run이 다를 수 있어 여전히 null(§2에 명시). 수정 후: odr2.json 재생성 결과가 수정 전과 바이트 단위로 동일함을 diff로 확인(집계 로직 자체는 안 건드림, date 컬럼만 추가로 SELECT), uvicorn 종단 확인 — 400(ICAO 형식)·404(OD 없음)·422(FastAPI Query 검증)·429(레이트리밋, 실제로 60회 버스트해 61번째부터 429 재현)·503(아티팩트 임시 제거) 전부 `{error:{code,message}}` 단일 포맷 확인 + `/api/routes`·`/api/routes/od-pairs`는 `data_period="20260101-20260131"`, `/api/reference/*`는 여전히 `data_period=null` 확인.

**Stage 1 완료** — 위 항목 전부 체크+ 공통 게이트 통과.

## Stage 2 — 프론트 (Leaflet, fetch)

> 근거: [04](./04-frontend-migration.md). 원본 기능/알고리즘·기상서버·완성본은 `PORTING_PACKAGE_ROOT`(env).

- [ ] F1 모듈 분리 + `js/config.js`(설정 주도)
- [ ] F2 `js/api.js`, F3 `js/adapters.js`(키↔08 배열), F4 `js/store.js`(파생 상수)
- [ ] F5 참조 레이어 6종 fetch 렌더(04-A 사전투영 보존), **결정 포커스 기본 + 전세계 온디맨드**([04 §3.1](./04-frontend-migration.md), [10 §2](./10-ui-and-realtime.md))
- [ ] F6 ROUTE 패널(`/api/routes`), F7 공항 기상(기존 프록시 폴백), F8 실시간 ADS-B
- [ ] F9 뷰모드 토글 3종(결정 포커스/지역 컨텍스트/전세계), F10 미니맵([10 §2.1·§2.3](./10-ui-and-realtime.md))
- [ ] 완성본 HTML 정답지와 **전세계 모드**에서 시각 회귀 비교(직접 Read 금지)
- [ ] 공통 게이트 통과

---

## 완료 — result/ 검증

- [ ] `flight-route-advisor/result/`에 초기 문서 대비 구현 대조 리뷰 작성([result/README.md](../result/README.md))
- [ ] docs/03·04·05·07·02 기능/범위 전부 구현·일치 + 리뷰에이전트 최종 통과(기능·논리·예외·보안)
- [ ] **불일치 시 사용자에게 설명·처리 질문**(임의 수정 금지)

## 향후 확장 (범위 밖 — 착수 시 별도 체크리스트)
- [ ] 2단계: 경로 기하 동적(04-D)·상층풍/시어(04-E)·참조 타일화·공항 운항 KPI(ACDM, `/api/airports/{icao}/ops`)·지연원인(FOIS, `/api/fois/delays`)·흐름관리 조회(자체 전처리분, `/api/flow-management`)
- [ ] 3단계: 실시간 STCA/CPA·흐름관리 탭(**통합데이터·영향상세 테이블 선행**, 비행편 영향 결합)·FIR 분석 패널
