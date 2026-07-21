# 05. MVP 범위 + 향후 확장 로드맵 (개발 착수용 상세)

- 문서 버전: 1.1
- 작성일: 2026-07-21
- 대상: 구현 계획을 세우는 개발자
- 관련 문서: [00-plan](./00-plan.md), [02-db-integration](./02-db-integration.md), [03-backend-api](./03-backend-api.md), [04-frontend-migration](./04-frontend-migration.md), [07-checklist](./07-checklist.md)

이 문서는 **개발자(또는 Claude)가 바로 착수할 수 있도록** MVP를 작업 단위로 쪼개고, 향후 확장을 선행조건과 함께 정리한다.

## 1. 제안 프로젝트 코드 구조 (구현 단계 목표)

> 이번 설계 단계에서는 아래 코드 폴더를 만들지 않는다. 구현 착수 시 목표 구조다. 모든 경로·값은 설정 주도(하드코딩 금지, [06](./06-conventions.md)).

```
flight-route-advisor/
├── docs/                      # (작성 완료)
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI 앱 · 라우터 등록 · CORS
│   │   ├── config.py          # 환경변수 → Settings (dataclass), 하드코딩 금지
│   │   ├── db/
│   │   │   ├── session.py     # 읽기전용 엔진/세션(로컬↔Supabase 분기)
│   │   │   ├── tables.py      # SQLAlchemy Core Table 리플렉션/정의(읽기 전용)
│   │   │   └── column_map.py  # 논리명↔물리명 어댑터 (02 §5)
│   │   ├── queries/
│   │   │   ├── latest_run.py  # "최신본 뷰" 규약 CTE (02 §3)
│   │   │   ├── routes.py      # ODR2 조회
│   │   │   ├── acdm.py        # 공항 KPI
│   │   │   ├── fois.py        # 지연원인
│   │   │   └── flow.py        # 흐름관리
│   │   ├── routers/
│   │   │   ├── reference.py   # /api/reference/*
│   │   │   ├── routes.py      # /api/routes*
│   │   │   ├── airports.py    # /api/airports/*
│   │   │   ├── fois.py
│   │   │   └── flow.py
│   │   └── reference/
│   │       ├── loader.py      # 사전빌드 JSON 로드 + bbox/zoom 필터
│   │       └── artifacts/     # 참조 지오메트리 아티팩트(빌드 산출, .gitignore 대상 검토)
│   ├── batch/
│   │   └── build_odr2.py      # processed_flight_data → ODR2 집계(3_agg/4_build 로직 이식)
│   └── tests/
├── frontend/
│   ├── index.html
│   └── js/                    # config·api·adapters·store·render·layers·weather (04 문서)
├── docker/
│   ├── docker-compose.yml     # db(postgres:16, 로컬 소유) + route-api + weather
│   └── Dockerfile
├── .env.example
└── config.example.json        # 프론트 런타임 config 예시
```

## 2. MVP (1단계) — 작업 분해

목표: **정적 지도와 동일한 화면이 fetch 기반으로 뜨고, OD 선택 시 DB 유래 경로추천이 표시된다.**

### 2.1 백엔드 (FastAPI, 읽기 전용)
| # | 작업 | 산출/검증 | 선행 |
|---|---|---|---|
| B1 | `config.py` — 환경변수 로딩(DATABASE_URL, 프록시 URL, 캐시 TTL, 참조 아티팩트 경로). 하드코딩 0 | `.env.example` 완비 | — |
| B2 | `db/session.py` — 읽기전용 엔진(로컬↔Supabase 분기, sslmode/pool). | 연결 스모크 테스트 | 전처리 DB 접근권 |
| B3 | `db/column_map.py` — 논리↔물리 컬럼 매핑([02](./02-db-integration.md) §5) | 매핑 단위테스트 | 컬럼 별칭(잠정) |
| B4 | `queries/latest_run.py` — 최신 SUCCESS run CTE 헬퍼([02](./02-db-integration.md) §3) | 최신본만 반환 검증 | B2 |
| B5 | `reference/loader.py` + `/api/reference/*` — 사전빌드 JSON 서빙 + bbox/zoom 필터, 장기 캐시 헤더 | 건수 대조(FIR 247·항로 89,555·픽스 58,812·공항 10,030) | 사전빌드 JSON |
| B6 | `batch/build_odr2.py` — `processed_flight_data`에서 ODR2 집계(3_agg/4_build 로직 이식) | OD 1,487·경로 3,083 근사 | B2,B4 |
| B7 | `/api/routes/od-pairs`, `/api/routes` — 집계 결과 서빙(키 기반) | 특정 OD 옵션 반환 | B6 |
| B8 | 공통 응답 봉투·에러·CORS·관측성 | 스키마 일치 | B1 |

### 2.2 프론트 (지도 앱 전환)
| # | 작업 | 산출/검증 | 선행 |
|---|---|---|---|
| F1 | 모듈 분리 + `config.js`(설정 주도) | 리터럴 하드코딩 제거 | — |
| F2 | `api.js` fetch 래퍼(캐시/에러/재시도) | 오프라인 폴백 처리 | B5 |
| F3 | `adapters.js` — API 키기반 → 08 배열 복원([04](./04-frontend-migration.md) §4) | 어댑터 왕복 테스트 | B5 |
| F4 | `store.js` — 파생 상수 재계산(APIDX/FIRB/firByIcao 등) | 원본과 동일 파생 | F3 |
| F5 | 참조 레이어 6종 렌더 전환(FIR/항로/공항/픽스/항행/TCA), **결정 포커스 기본 + 전세계 온디맨드**([04](./04-frontend-migration.md) §3.1·§6, [10](./10-ui-and-realtime.md) §2) | 완성본(전세계 모드)과 시각 회귀 일치 | F4, 04-A 보존 |
| F6 | ROUTE 패널 — OD select→`/api/routes` 표시 | 옵션·경유FIR·트랙 표시 | B7,F3 |
| F7 | 공항 기상 팝업 — 기존 Node 프록시 폴백 체인 유지 | METAR/TAF 표시 | 기상서버 |
| F8 | 실시간 ADS-B — 외부 API 직접(기존 로직) | 기체 표시·12초 갱신 | — |
| F9 | 뷰모드 토글 3종(결정 포커스/지역 컨텍스트/전세계, [10](./10-ui-and-realtime.md) §2.1) — 모드 전환 시 `/api/reference/*` 온디맨드 로드 범위 전환 | 모드별 로딩 범위·fit-bounds 동작 확인 | F5, B5 |
| F10 | 미니맵(전세계 상 현재 포커스 위치 표시, [10](./10-ui-and-realtime.md) §2.3) | 포커스 이동 시 미니맵 마커 갱신 | F9 |

### 2.3 인프라
| # | 작업 |
|---|---|
| I1 | `docker-compose.yml`(db(postgres:16, 로컬 소유) + route-api + weather). Stage 0 적재 → Stage 1·2 소비 |
| I2 | `.env.example`, `config.example.json` 정비 |

### 2.4 MVP 완료(DoD)
- 기본 화면(결정 포커스)이 선택 OD·후보 루트의 FIR·항공로만 그리고, **전세계 모드 전환 시** 참조 지도 6종이 완성본 HTML과 시각 회귀 일치([10](./10-ui-and-realtime.md) §2.1).
- 3뷰 모드(결정 포커스/지역 컨텍스트/전세계) 토글이 동작하고 모드별 온디맨드 로딩 범위가 다름을 확인.
- OD 선택 시 DB 유래(배치 집계) 경로추천 표시.
- 공항 클릭 시 기상 팝업 동작(Node 프록시 경유).
- 코드 내 URL·임계·색상 리터럴 없음(모두 config).

## 3. 향후 확장 로드맵

### 2단계 — 경로추천 심화
| 기능 | 원본 근거 | 선행조건 | 난이도 |
|---|---|---|---|
| 경로 기하 동적 재계산(FIR 경유 면·게이트) | 04-D buildGeo | 참조 FIR 지오메트리 | 상 |
| 상층풍·시어 오버레이(FL별 색) | 04-E, Open-Meteo | 외부 API, 세그먼트 표본 | 중 |
| 공항 운항 KPI 패널 | ACDM | `/api/airports/{icao}/ops`(B), `processed_acdm_*` | 중 |
| FOIS 지연원인 패널 | FOIS | `processed_fois_*` | 하 |
| 흐름관리 조회(자체 전처리분, 비행편 영향 미결합) | `03 §4.4` | `/api/flow-management`(B), `processed_flow_management` | 하 |
| 참조 지오메트리 타일화(뷰포트 스트리밍) | 01 §4 | 프론트 렌더 일부 재작성 | 상 |

### 3단계 — 실시간·분석
| 기능 | 원본 근거 | 선행조건 | 난이도 |
|---|---|---|---|
| 실시간 ADS-B STCA/CPA 충돌예측 | 03, 04-G | ADS-B 스트림, 예측 로직 | 상 |
| 흐름관리 탭(비행편 영향 결합) | 03 | **통합데이터·영향상세 테이블**(전처리 통합 스킬) | 상 |
| FIR 분석 패널(섹터 수요예측·기상%) | 03, 04-G | ACC섹터·RainViewer·ADS-B | 상 |
| 사후분석 연계 | 원본 02-7 post_stats | 전처리 사후집계 | 중 |

> **3단계 강한 의존성**: 흐름관리 영향·통합데이터 기능은 전처리 측 `processed_flight_route_integrated`·`processed_flow_management_impact_detail` 테이블이 생겨야 착수 가능([02](./02-db-integration.md) §2). 그 전까지 흐름관리는 조치 목록 조회(자체 전처리분)까지만.

## 4. 명시적 비범위 (이번 프로젝트 전체)
- **전처리 스킬 로직 자체**(수정 없이 재사용) — 별도 `데이터전처리기술이식` 소관. ⚠ 그 로직을 호출하는 **Stage 0 적재 백엔드 앱**(`data-ingestion-backend/app·docker`)은 이 비범위에 포함되지 않는다 — 이 저장소에서 신규 개발한다([00 §3](./00-plan.md), [08 §2.1](./08-setup-and-dev-order.md)).
- 기상서버 재구현 (기존 Node 그대로)
- 사용자 인증/권한 세분화 (초기 단일 운영 가정, 필요 시 후속)
- CI/CD 구축 (구조만 Git 친화적으로)
