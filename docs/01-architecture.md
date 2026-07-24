# 01. 시스템 아키텍처

- 문서 버전: 1.1
- 작성일: 2026-07-21
- 대상: 이 서비스를 구현/검토할 개발자
- 관련 문서: [00-plan](./00-plan.md), [02-db-integration](./02-db-integration.md), [03-backend-api](./03-backend-api.md), [04-frontend-migration](./04-frontend-migration.md), [07-checklist](./07-checklist.md)

## 1. 큰 그림 — 2백엔드 토폴로지

이 서비스는 **하나의 PostgreSQL을 두 백엔드가 공유**하는 구조다. 쓰기(적재)와 읽기(서비스)를 분리한다.

```
┌───────────────────────────┐        ┌──────────────────────────────────────┐
│  (A) 전처리 ingestion 백엔드 │        │  (B) flight-route-advisor 백엔드 (이번)  │
│  데이터전처리기술이식/        │        │  flight-route-advisor/                  │
│  data-ingestion-backend    │        │                                        │
│                            │        │  FastAPI (읽기 전용 조회 API)            │
│  FastAPI + Jinja2          │        │    ├─ /api/reference/*  (참조 지오메트리)  │
│  업로드 폼 + 로그 조회       │        │    ├─ /api/routes       (경로추천 ODR2)   │
│  스킬 subprocess 실행       │        │    ├─ /api/airports/*   (ACDM KPI)       │
│  raw_* / processed_* 적재   │        │    └─ /api/fois,flow    (지연·흐름관리)   │
└───────────┬────────────────┘        └───────┬───────────────────┬────────────┘
            │ 쓰기(DDL/INSERT)                 │ 읽기 전용 SELECT     │ 서빙
            ▼                                  ▼                     ▼
     ┌─────────────────────────────────────────────┐      ┌──────────────────┐
     │       PostgreSQL 16 (Docker → Supabase)      │      │  Leaflet 지도 앱   │
     │  ingestion_runs · raw_* · processed_*         │◀─────│  (브라우저, fetch) │
     └─────────────────────────────────────────────┘      └───┬──────────────┘
                                                               │ 외부 API 직접/프록시
                              ┌────────────────────────────────┼───────────────────┐
                              ▼                                 ▼                   ▼
                   Node 기상 프록시(재사용)              NOAA AWC · RainViewer      ADS-B
                   /proxy · /mcp · /tts               Open-Meteo                (실시간 항공기)
```

**핵심 원칙**: (B)는 스키마를 **소유하지 않는다**. DDL·INSERT는 전적으로 (A)의 책임이고, (B)는 `processed_*`를 **읽기 전용 role**로만 SELECT한다. 두 백엔드는 별도 프로세스·별도 저장소로 독립 배포·운영된다.

## 2. 컴포넌트

### 2.1 FastAPI 조회 API (신규, 이번 프로젝트의 핵심)
- 전처리 DB의 `processed_*`를 읽어 운항·경로·통계 데이터를 JSON으로 서빙.
- 참조 지오메트리는 캐시된 벌크/타일 엔드포인트로 서빙(구분 서빙, §4).
- 전처리 백엔드와 동일 계열(FastAPI + SQLAlchemy 2.0 Core + psycopg2)로 맞춰 연결·설정 관례를 재사용한다.
- 상세: [03-backend-api](./03-backend-api.md).

### 2.2 Leaflet 지도 프론트 (기존 앱 전환)
- 기존 `전세계_항공로_지도.html`의 앱 로직·렌더링(04-A 사전투영 캔버스)을 보존하되, 데이터 공급원을 `const` 임베드 → `fetch`로 바꾼다.
- 인덱스 의존 배열을 어댑터로 흡수해 API 응답(키 기반 JSON)과 연결.
- 상세: [04-frontend-migration](./04-frontend-migration.md).

### 2.3 Node 기상 프록시 (그대로 재사용)
- `비행경로추천서비스_이식패키지/기상서버`의 `aviation-weather-mcp`를 변경 없이 운영.
- 역할: ① 공항 기상 MCP 도구 5종 ② 지도용 CORS 프록시(`/proxy`) ③ TTS.
- FastAPI가 기상 기능을 **중복 구현하지 않는다.** 프론트는 기존 폴백 체인(직접→localhost:3000/proxy→공개 프록시)을 유지.
- 계약: `비행경로추천서비스_이식패키지/문서/07_기상MCP서버.md`.

### 2.4 참조 지오메트리 스토어
- DAFIF 기반 항공로/공항/항행시설/FIR/픽스/TCA/SUAS/ACC섹터 + Jeppesen 기반 SID/STAR. **2026-07-23부터 `reference_*` DB 테이블**(전처리 DB와 같은 PostgreSQL, `data-ingestion-backend/scripts/migrate_static_reference_to_db.py`·`ingest_jepp_nav.py`가 1회 적재)이 원천 — 예전엔 `사전빌드_JSON` 정적 파일이었다.
- 갱신 주기가 길어(월·분기, AIRAC 주기) 여전히 요청마다 재계산하지 않고 **프로세스 메모리 캐시 + 장기 HTTP 캐시**로 서빙한다(§4) — DB 도입이 "매 요청 DB 왕복"을 뜻하지 않는다.

## 3. 데이터 흐름 (구분 서빙)

```
[잘 안 변함: 참조 지오메트리]                    [자주 바뀜: 운항·분석]
DAFIF/Jeppesen → reference_* (DB, 1회 적재)      전처리 DB processed_*
   │ 프로세스 캐시(bbox 필터는 요청마다)             │ 요청 시 최신 run 질의
   ▼                                              ▼
FastAPI 조회 (+ HTTP 장기 캐시)                   FastAPI 집계·조회
   │ GET /api/reference/*  (장기 캐시)              │ GET /api/routes, /airports/*, ...
   └──────────────┬───────────────────────────────┘
                  ▼
          Leaflet 지도 (fetch, 04-A 사전투영 렌더)
                  │
                  └─ 기상/레이더/상층풍/ADS-B → 외부 API(브라우저 직접, CORS는 Node 프록시)
```

- **참조 데이터**: 응답에 장기 캐시 헤더. 갱신 주기가 길어(월·분기) 프리페치·CDN 친화적.
- **운항 데이터**: `processed_*`에서 최신 SUCCESS run 기준 조회(append-only 대응, [02](./02-db-integration.md) §3).
- **외부 실시간**: AWC/RainViewer/Open-Meteo/ADS-B는 프론트가 직접 호출, CORS 차단분만 Node `/proxy` 경유.

## 4. 참조 지오메트리 "구분 서빙" 전략

15MB 규모 지오메트리를 매 요청 DB에서 뽑으면 비용이 크다. 두 축으로 최적화한다.

1. **1회 적재 + 프로세스 캐시**: 참조 데이터는 `reference_*` DB 테이블에 1회 적재해 두고, 백엔드 프로세스가 첫 조회 시 메모리에 캐시해 이후 요청은 DB round-trip 없이 서빙한다(예전 "빌드 시 1회 생성한 벌크 JSON"과 캐싱 특성은 동일, 저장소만 파일→DB).
2. **bbox/zoom 필터**: 전 세계를 한 번에 주지 않고 뷰포트·줌 레벨별로 필요한 것만 반환(예: 저배율은 민간/공용 공항만, 항로 픽스 상한 800). 원본 앱의 줌별 표시 규칙(`문서/03`)을 서버 필터로 옮긴다.

> 초기 MVP는 "벌크 프리페치 + 04-A 클라이언트 사전투영"을 우선하고, 필요 시 타일화(2단계)로 발전시킨다. 전면 PostGIS + 뷰포트 스트리밍은 프론트 렌더링 재작성 비용이 커서 채택하지 않는다.

## 5. 배포

| 환경 | 구성 |
|---|---|
| 로컬 개발 | Docker Compose: `db`(postgres:16, **이 저장소 소유**) + `route-api`(FastAPI) + `weather`(Node 기상서버). Stage 0가 이 로컬 `db`에 `processed_*`를 적재하고 Stage 1·2가 읽는다([08 §2.1](./08-setup-and-dev-order.md)) |
| 운영(초기) | 동일 구성, 전처리 백엔드와 같은 호스트/네트워크 |
| 운영(이전) | DB를 Supabase로 이전 시 `DATABASE_URL`만 교체(sslmode·pooler 분기), API/프론트는 무변경 |

## 6. 기술 스택

| 영역 | 선택 | 비고 |
|---|---|---|
| 조회 백엔드 | FastAPI + uvicorn | 전처리 백엔드와 동일 계열 |
| DB 접근 | SQLAlchemy 2.0 Core + psycopg2 (읽기 전용) | 전처리 `기술스택_결정.md`와 일치, DDL 없음 |
| DB | PostgreSQL 16 → Supabase | 전처리 프로젝트가 소유 |
| 프론트 | Leaflet 1.9.4 (preferCanvas) + 04-A 사전투영 캔버스 | 기존 앱 보존 |
| 기상 | Node `aviation-weather-mcp` (`@modelcontextprotocol/sdk`, express, zod) | 재사용, 무변경 |
| 외부 API | AWC · RainViewer · Open-Meteo · ADS-B | 무료·키 불필요, 브라우저 직접 |

## 7. 상충 방지 메모

전처리 `기술스택_결정.md`는 **"React 기각, Jinja2 서버렌더링"**을 명시하지만, 이는 **ingestion 관리 UI(업로드 폼·로그 조회)** 한정 결정이다. 이 프로젝트의 지도 앱은 본래 리치 클라이언트(Leaflet + 대용량 JS)이며 성격이 다르다 — 두 결정은 서로 다른 화면을 다루므로 상충하지 않는다. 지도 프론트는 SPA 프레임워크 없이 기존 바닐라 JS + Leaflet 구조를 유지한다.
