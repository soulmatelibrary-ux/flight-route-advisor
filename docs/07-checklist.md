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

- [ ] `backend/app/config.py` — env→Settings(하드코딩 0), `.env.example`, `config.example.json`
- [ ] `docker/docker-compose.yml` — `db(postgres:16)` + `route-api` + `weather`(기존 기상서버)
- [ ] `.gitignore`(`.env`, 참조 아티팩트, 15MB HTML 등)
- [ ] `docker compose up db` 후 접속 스모크

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

## Stage 1 — advisor 백엔드 (FastAPI, 읽기 전용)

> Stage 0가 채운 동일 로컬 pgsql `processed_*` 소비. 근거: [02](./02-db-integration.md)·[03](./03-backend-api.md).

- [ ] **[착수 전 필수 확정 — H2/O2]** append-only 다회차 적재 시 "어느 run을 집계·조회 대상으로 삼는가" 정책 확정. [02 §3.2](./02-db-integration.md) "최신 run 1개" 예시는 **다회차 누적에 사용 금지** — 데이터 일자 기준 최신 run 우선(윈도우) 규칙을 먼저 확정해야 ODR2 검증 기준치(OD 1,487·경로 3,083)를 재현할 수 있다
- [ ] `db/session.py`(읽기전용 엔진, 로컬↔Supabase 분기), `db/tables.py`, `db/column_map.py`([DB스키마 §9] 단일출처)
- [ ] `queries/latest_run.py` — 최신 SUCCESS run 규약(단순 SELECT 금지, [02 §3](./02-db-integration.md))
- [ ] `reference/loader.py` + `/api/reference/*`(bbox·zoom, 장기 캐시) — `PORTING_PACKAGE_ROOT/사전빌드_JSON`
- [ ] `batch/build_odr2.py` — `processed_flight_data`에서 ODR2 집계(집계 로직: `PORTING_PACKAGE_ROOT/전처리스크립트/{3_agg_csv,4_build_routes2}.py` 이식). 산출물은 advisor 소유(전처리 DB에 쓰지 않음)
- [ ] `/api/routes*`(MVP). `/api/airports/{icao}/ops`·`/api/fois/delays`·`/api/flow-management`은 **2단계로 이관**([05](./05-mvp-scope.md) §3, [03](./03-backend-api.md) §4.2~4.4) — Stage 1 산출물 아님
- [ ] 공통 응답 봉투·에러·CORS·관측성
- [ ] 규모 대조(FIR 247·항로 89,555·픽스 58,812·공항 10,030·OD 1,487)
- [ ] 공통 게이트 통과

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
