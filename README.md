# flight-route-advisor

- 문서 버전: 1.2
- 작성일: 2026-07-22

항공 **비행경로추천 웹서비스**의 풀스택 개발 저장소다. 데이터 **생산(적재)**과 **소비(서비스)**의 설계 문서를 한곳에 모아, 문서만 읽고 바로 개발에 착수할 수 있게 한다. (현재 단계: **Stage 0→2 구현 완료, 완료검증 통과** — [result/review-2026-07-22.md](result/review-2026-07-22.md))

## 이 서비스가 하는 일 (한 줄)

전세계 항공로·공항·FIR 지도 위에서, 김포/인천 실운항 데이터 기반 **경로추천·공항 정시성·기상**을 보여주는 인터랙티브 웹서비스. 기존 정적 임베드(단일 HTML ~15MB) 방식을 **DB 기반 동적 서비스**로 전환한다.

---

## 두 백엔드, 하나의 DB

```
[생산] 데이터전처리기술이식/                    [소비] flight-route-advisor/
  data-ingestion-backend                        ├─ backend/ (FastAPI, 읽기 전용)
  (웹 업로드→스킬 subprocess→적재)                └─ frontend/ (Leaflet 지도)
        │ 쓰기                                          │ 읽기 전용 SELECT
        ▼                                               ▼
   ┌───────────────────────────────────────────────────────┐
   │        PostgreSQL 16 (Docker → Supabase)               │
   │   ingestion_runs · raw_* · processed_*                 │
   └───────────────────────────────────────────────────────┘
```

- **생산(ingestion)**: `데이터전처리기술이식/data-ingestion-backend`가 원본(비행자료·ACDM·FOIS·흐름관리)을 전처리해 `processed_*` 테이블에 적재. **코드·문서 진실원은 그 폴더**.
- **소비(advisor, 이번 저장소)**: `processed_*`를 **읽기 전용**으로 소비해 경로추천·통계 API + 지도 프론트를 제공.
- 이 저장소의 `data-ingestion-backend/docs/`는 생산 측 문서의 **미러(사본)** 다 → [data-ingestion-backend/_MIRROR.md](data-ingestion-backend/_MIRROR.md).

---

## 폴더 구성

```
flight-route-advisor/
├── README.md                       (이 문서 — 풀스택 진입점)
├── CLAUDE.md                       개발 원칙(하드코딩 금지·시큐어코딩·리뷰 게이트)
├── docs/                           경로추천 서비스(소비) 설계 문서
│   ├── 00-plan.md
│   ├── 01-architecture.md
│   ├── 02-db-integration.md      ★ 전처리 DB 연동
│   ├── 03-backend-api.md
│   ├── 04-frontend-migration.md
│   ├── 05-mvp-scope.md
│   ├── 06-conventions.md
│   ├── 07-checklist.md            Phase 체크박스(구현 추적)
│   ├── 08-setup-and-dev-order.md  env 루트·로컬 pgsql 기동·순차 순서
│   ├── 09-review-notes.md         문서 리뷰 로그
│   └── 10-ui-and-realtime.md      결정 중심 UI 방향 + 향후 실시간 아키텍처
├── data-ingestion-backend/         전처리 적재 백엔드(생산, Stage 0 — 구현 완료)
│   ├── _MIRROR.md
│   ├── docs/                      문서 미러(읽기 전용, README·작업계획서·스킬연동_레퍼런스·DB스키마·기술스택_결정·체크리스트)
│   ├── app/                        업로드→적재 API, 요청량 제한, 고착 run 자동 복구
│   ├── alembic/                     DB 마이그레이션(advisor_readonly role 포함)
│   └── docker/·start.sh
├── backend/                        Stage 1 advisor 백엔드(FastAPI, 읽기 전용) — 구현 완료
│   ├── app/                        config·routers·queries·reference·envelope(공통 에러 포맷)
│   ├── batch/, tests/
│   └── start.sh
├── frontend/                        Stage 2 프론트(vanilla ES module + Leaflet) — 구현 완료
│   ├── index.html, css/, js/
│   └── config.json                 (gitignore 대상, config.example.json 참고)
├── docker/                         docker-compose.yml(db+route-api+weather) · Dockerfile(route-api, frontend 동봉)
├── start.sh                        루트 통합 실행 스크립트(db+weather → Stage 0·1 API; 프론트는
│                                     별도 서버 없이 backend가 동일 오리진("/")으로 서빙)
├── .env.example, config.example.json  환경변수·프론트 런타임 config 예시
└── result/                          완료검증 리포트(review-2026-07-22.md 등)
```

---

## 읽는 순서

**개발 시작 전 반드시 [CLAUDE.md](CLAUDE.md)(개발 원칙)를 먼저 읽는다.** 순차 개발 순서: **Stage 0 전처리 적재 → Stage 1 advisor 백엔드 → Stage 2 프론트**.

### 경로추천 서비스(이번 개발 대상)
| 순서 | 문서 | 내용 |
|---|---|---|
| 0 | [CLAUDE.md](CLAUDE.md) | **개발 원칙**(하드코딩 금지·시큐어코딩·리뷰에이전트·재개) |
| 1 | [docs/00-plan.md](docs/00-plan.md) | 마스터 기획서 — 배경·목표·범위·로드맵·리스크 |
| 2 | [docs/01-architecture.md](docs/01-architecture.md) | 아키텍처 — 2백엔드 토폴로지·데이터 흐름 |
| 3 | [docs/02-db-integration.md](docs/02-db-integration.md) | **전처리 DB 연동** (핵심) |
| 4 | [docs/03-backend-api.md](docs/03-backend-api.md) | FastAPI API 명세 |
| 5 | [docs/04-frontend-migration.md](docs/04-frontend-migration.md) | 지도 앱 전환(임베드→fetch) |
| 6 | [docs/05-mvp-scope.md](docs/05-mvp-scope.md) | MVP 범위 + 코드 구조 + 로드맵 |
| 7 | [docs/06-conventions.md](docs/06-conventions.md) | 규약·함정·하드코딩 금지·시큐어코딩 |
| 8 | [docs/07-checklist.md](docs/07-checklist.md) | **진행 기준점**(Stage 0→2 순차 체크리스트) |
| 9 | [docs/08-setup-and-dev-order.md](docs/08-setup-and-dev-order.md) | env 루트·로컬 pgsql 기동·순차 순서 |
| 10 | [docs/09-review-notes.md](docs/09-review-notes.md) | 문서 리뷰 문제점·개선점 로그 |
| 11 | [docs/10-ui-and-realtime.md](docs/10-ui-and-realtime.md) | **결정 중심 UI 방향** + 향후 실시간 의사결정 아키텍처 |
| — | [result/README.md](result/README.md) | 개발 완료 검증 절차(출력) |

### 데이터 적재 백엔드(생산, 미러 참조)
| 문서 | 내용 |
|---|---|
| [data-ingestion-backend/docs/README.md](data-ingestion-backend/docs/README.md) | 적재 백엔드 진입점 |
| [data-ingestion-backend/docs/DB스키마.md](data-ingestion-backend/docs/DB스키마.md) | **테이블 정의 + 물리 컬럼 매핑(§9)** — 이 서비스가 소비하는 계약 |
| [data-ingestion-backend/docs/작업계획서.md](data-ingestion-backend/docs/작업계획서.md) | 적재 파이프라인·완료기준 |
| 그 외 | 스킬연동_레퍼런스·기술스택_결정·체크리스트 |

---

## 반드시 지킬 불변 원칙

1. **읽기 전용 소비.** 이 서비스는 전처리 DB에 DDL/INSERT/UPDATE를 하지 않는다. 스키마·데이터 소유는 생산 측(`데이터전처리기술이식`)이다.
2. **원본 무변경.** `데이터전처리기술이식/**`(스킬·원본 폴더·ingestion 문서)는 수정·삭제하지 않는다. 여기의 `data-ingestion-backend/docs/`만 읽기용 미러다 — 같은 폴더의 `app/·docker/`는 **Stage 0 신규 코드**([_MIRROR.md](data-ingestion-backend/_MIRROR.md), [docs/08 §2.1](docs/08-setup-and-dev-order.md)).
3. **저하드코딩.** URL·임계·색상·컬럼명·자격증명은 코드에 박지 않고 설정(env/config)·단일 매핑으로 뺀다([docs/06-conventions.md](docs/06-conventions.md)).
4. **append-only 최신본 규약.** `processed_*`는 누적되므로 항상 최신 SUCCESS run/기간으로 조회한다([docs/02-db-integration.md](docs/02-db-integration.md) §3).
5. **좌표 [lat,lon] · 시간 KST 고정**(+9 재변환 금지).

---

## 현재 상태

- **Stage 0(적재)·Stage 1(advisor 백엔드)·Stage 2(프론트) 구현 완료.** 순서대로 개발되었고 각 단계 완료 시 리뷰에이전트 게이트(기능·논리·예외·보안)를 통과했다([docs/07-checklist.md](docs/07-checklist.md)).
- **개발 완료 검증 통과**: 초기 설계 문서(docs/02·03·04·05·07) 대비 구현 대조 리뷰를 완료했고, 발견된 불일치·미구현 항목은 사용자 확인을 거쳐 처리했다([result/review-2026-07-22.md](result/review-2026-07-22.md)). 기상 레이더·SIGMET/PIREP·경유 FIR 심각도 표시는 2단계 로드맵으로 이관([docs/05-mvp-scope.md](docs/05-mvp-scope.md) §3, [docs/10-ui-and-realtime.md](docs/10-ui-and-realtime.md) §2.5).
- **로컬 실행**: 루트 `.env`를 채운 뒤 `./start.sh` 하나로 db+weather(docker compose)·Stage 0·Stage 1이 뜨고, 프론트는 Stage 1(advisor)이 동일 오리진("/")으로 정적 서빙한다. 개별 Stage만 띄우려면 `data-ingestion-backend/start.sh`·`backend/start.sh`를 각자 실행한다. 상세 순서는 [docs/08-setup-and-dev-order.md](docs/08-setup-and-dev-order.md).
- 3단계(경로영향 상세) 기능을 위한 전처리 측 **통합데이터/영향상세 테이블**은 아직 선행조건 — 물리 컬럼 매핑은 [DB스키마 §9](data-ingestion-backend/docs/DB스키마.md)로 확정돼 있다.
