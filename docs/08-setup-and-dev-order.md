# 08. 개발 환경·자산 경로·순차 개발 순서

- 문서 버전: 1.0
- 작성일: 2026-07-21
- 대상: 로컬에서 순차 개발을 시작하는 개발자
- 관련 문서: [00-plan](./00-plan.md), [02-db-integration](./02-db-integration.md), [05-mvp-scope](./05-mvp-scope.md), [07-checklist](./07-checklist.md), [06-conventions](./06-conventions.md)

이 문서는 **`flight-route-advisor` 폴더만으로 Stage 0→2를 순차 개발**하기 위한 환경·경로·순서를 정의한다. 값은 모두 설정 주도(하드코딩 금지, [06 §1](./06-conventions.md)).

## 1. 외부 자산 경로 (env 루트)

코드/문서는 이 저장소에 있고, **데이터·스킬·참조자산은 외부**에 있다. 절대경로를 코드에 박지 말고 env로 받는다.

| env 변수 | 기본값 | 가리키는 것 |
|---|---|---|
| `SOURCE_PROJECT_ROOT` | `<PROJECT>/result/데이터전처리기술이식` | 스킬 `skills/`, 원본데이터(`ACDM/·FOIS/·비행자료/·흐름관리일지/·공간데이터/`), `outputs/`, `data-ingestion-backend/` |
| `PORTING_PACKAGE_ROOT` | `<PROJECT>/result/비행경로추천서비스_이식패키지` | 참조 지오메트리 `사전빌드_JSON/`, 기상서버 `기상서버/`, 집계 스크립트 `전처리스크립트/`, 원본 기능/알고리즘 문서 `문서/03·04·07·08` |
| `DATABASE_URL` | `postgresql://…@localhost:5432/aviation` | 로컬 PostgreSQL (advisor는 읽기 전용 role) |
| `ADVISOR_ARTIFACT_DATABASE_URL` | `postgresql://advisor_artifact_writer:…@localhost:5432/aviation` | odr2/flow 배치(`backend/batch/{build_odr2,build_flow}.py`) 전용 쓰기 접속(2026-07-23, [02 §4.3·§6](./02-db-integration.md)) — API 프로세스는 참조하지 않음, 배치 실행 시에만 필요 |
| `WEATHER_PROXY_URL` | `http://localhost:3000/proxy` | 기상서버 CORS 프록시 |

- `<PROJECT>` = 이 저장소들의 상위(예 `/Users/sein/Desktop/project`).
- **백데이터(입력 자산)의 정본 위치는 `<PROJECT>/result/`** 다.
- ⚠ **두 "result" 구분**: `<PROJECT>/result/` = 백데이터(입력, 읽기 전용) / `flight-route-advisor/result/` = 완료검증 산출(출력). 서로 다르다. 입력 result에는 쓰지 않는다.
- 이 외부 자산은 **읽기 전용**(수정·삭제 금지). 값이 다르면 env만 바꾼다.

## 2. 외부 자산 인벤토리 (용도 매핑)

| 자산 | 경로(루트 기준) | 쓰는 Stage | 용도 |
|---|---|---|---|
| 전처리 스킬 | `SOURCE_PROJECT_ROOT/skills/*/scripts` | Stage 0 | 업로드 파일 subprocess 전처리 |
| 원본데이터 폴더 | `SOURCE_PROJECT_ROOT/{ACDM,FOIS,비행자료,흐름관리일지,공간데이터}` | Stage 0 | 적재 입력·동일성 검증 기준선 |
| 적재 백엔드 문서(미러) | `flight-route-advisor/data-ingestion-backend/docs` | Stage 0 | DB스키마§9·스킬연동·작업계획서·체크리스트 |
| 참조 지오메트리 | `PORTING_PACKAGE_ROOT/사전빌드_JSON` | Stage 1·2 | `/api/reference/*` 소스 |
| ODR2 집계 로직 | `PORTING_PACKAGE_ROOT/전처리스크립트/{3_agg_csv,4_build_routes2}.py` | Stage 1 | 경로추천 배치 집계 이식 원천 |
| 기상서버 | `PORTING_PACKAGE_ROOT/기상서버` | Stage 2 | 공항 기상·CORS 프록시(재사용) |
| 원본 기능/알고리즘 문서 | `PORTING_PACKAGE_ROOT/문서/03·04·07·08` | Stage 2 | 지도 기능·렌더·스키마 근거 |
| 완성본 HTML(정답지) | `PORTING_PACKAGE_ROOT/완성본_전세계_항공로_지도.html` | Stage 2 검증 | 프론트 회귀 비교(직접 Read 금지, [06 §6]) |

### 2.1 코드 위치 (신규 개발물 — 외부 자산 아님)

| 코드 | 위치(이 저장소) | 비고 |
|---|---|---|
| Stage 0 적재 백엔드 | `flight-route-advisor/data-ingestion-backend/`(현재 `docs/`만 → `app/·docker/` 신규) | 미러 `docs/작업계획서.md §8` 구조를 이 저장소 기준으로. 스킬·원본데이터는 `SOURCE_PROJECT_ROOT`(env) 참조 |
| Stage 1 advisor 백엔드 | `flight-route-advisor/backend/` | [05 §1](./05-mvp-scope.md) 구조 |
| Stage 2 프론트 | `flight-route-advisor/frontend/` | [04](./04-frontend-migration.md) |
| 로컬 DB | 이 저장소 `docker/docker-compose.yml`의 `db(postgres:16)` | **로컬 pgsql은 이 저장소 compose가 소유**(Stage 0가 여기 적재). Supabase 이전 시 `DATABASE_URL`만 교체 |

> `data-ingestion-backend/docs/`는 **미러(읽기 전용)**, 같은 폴더의 `app/·docker/`는 **신규 코드**다([../data-ingestion-backend/_MIRROR.md](../data-ingestion-backend/_MIRROR.md)).

## 3. 로컬 pgsql 기동·개발 순서

```
0) docker compose up db          # 로컬 PostgreSQL(16) 기동
1) Stage 0 — 전처리 적재 백엔드
     원본 업로드 → 스킬 subprocess → processed_* 적재
     (근거: data-ingestion-backend/docs/{작업계획서,DB스키마,스킬연동_레퍼런스,체크리스트})
     결과: 로컬 pgsql에 ingestion_runs·raw_*·processed_* 채워짐
2) Stage 1 — advisor 백엔드(FastAPI, 읽기 전용)
     같은 로컬 pgsql의 processed_* 소비 → /api/* 서빙 + ODR2 배치 집계
3) Stage 2 — 프론트(Leaflet)
     /api/* fetch + 기상서버(WEATHER_PROXY_URL) + 외부 API
```

### 3.1 통합 실행(개발 편의, 2026-07-22 추가)

각 Stage 코드가 갖춰진 뒤에는(위 순서로 개발 완료 후) 저장소 루트 `./start.sh` 하나로 db+weather(docker compose)·Stage 0(`data-ingestion-backend/start.sh`)·Stage 1(`backend/start.sh`)을 한 번에 띄울 수 있다. Stage 2 프론트는 별도 서버 없이 advisor가 같은 포트("/")에서 동일 오리진으로 서빙한다(완료검증 §D-4, `backend/app/config.py`의 `FRONTEND_DIR`). **프로세스를 하나로 합친 것이 아니라 실행 편의만 묶은 것**이다 — advisor(읽기전용)·ingestion(쓰기) 최소권한 분리는 그대로 유지된다(근거: [../result/backend-integration-review-2026-07-22.md](../result/backend-integration-review-2026-07-22.md)). 개별 Stage만 띄우려면 기존처럼 `data-ingestion-backend/start.sh`·`backend/start.sh`를 각자 실행하면 된다. 이미 실행 중인 포트가 있으면 중복 기동하지 않고, 무관한 프로세스가 포트를 점유 중이면(예: 다른 프로젝트) 크래시 대신 경고만 출력한다.

### Stage 간 핸드오프 (중요)
- Stage 1·2는 **Stage 0가 적재한 동일 로컬 pgsql**을 소비한다. Stage 0 적재가 없으면 advisor는 빈 결과다.
- 개발 초기 데이터가 필요하면 `SOURCE_PROJECT_ROOT/outputs/`의 기존 산출물 또는 원본데이터로 Stage 0를 1회 실행해 시드한다.
- `processed_*`는 append-only이므로 advisor는 최신 SUCCESS run 기준으로 읽는다([02 §3](./02-db-integration.md)).

## 4. 자기완결성 점검 (이 폴더만으로 개발 가능한가)

| Stage | 입력(문서·자산) | 산출 | 검증·게이트 |
|---|---|---|---|
| 0 적재 | data-ingestion-backend/docs 미러 + `SOURCE_PROJECT_ROOT`(스킬·원본) | 로컬 pgsql `processed_*` | 원본 동일성(작업계획서 §완료기준) + 리뷰에이전트·시큐어코딩([07](./07-checklist.md)) |
| 1 백엔드 | docs/02·03 + `PORTING_PACKAGE_ROOT/사전빌드_JSON·전처리스크립트` | `/api/*`, ODR2 집계 | 건수·규모 대조 + 리뷰에이전트·시큐어코딩 |
| 2 프론트 | docs/04 + `PORTING_PACKAGE_ROOT/문서·기상서버·완성본` | 지도 앱 | 완성본 회귀 비교 + 리뷰에이전트·시큐어코딩 |

→ 각 Stage의 "무엇을/어떻게/검증"이 이 폴더 문서 + env 자산으로 닫힌다.
