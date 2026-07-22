# 03. 백엔드 API 명세 (FastAPI, 읽기 전용)

- 문서 버전: 1.1
- 작성일: 2026-07-21
- 대상: 이 서비스의 백엔드를 구현할 개발자
- 관련 문서: [01-architecture](./01-architecture.md), [02-db-integration](./02-db-integration.md), [04-frontend-migration](./04-frontend-migration.md), [07-checklist](./07-checklist.md)
- 범위: **MVP 기준**. 향후 확장 엔드포인트는 [05-mvp-scope](./05-mvp-scope.md)에서 관리.
- 물리 컬럼명은 [DB스키마 §9](../data-ingestion-backend/docs/DB스키마.md) 확정본을 따르며, 쿼리는 `column_map.py`(논리↔물리 단일 출처)를 경유한다.

## 1. 설계 원칙

1. **읽기 전용.** 모든 엔드포인트는 GET. 쓰기 없음.
2. **데이터 출처 이원화.** 참조 지오메트리(정적 아티팩트/캐시)와 운항·분석(DB `processed_*`)을 경로 네임스페이스로 구분한다: `/api/reference/*` vs 나머지.
3. **키 기반 JSON.** 응답은 객체 키로 내보내 프론트가 배열 인덱스·물리 컬럼명에 의존하지 않게 한다([06-conventions](./06-conventions.md)). 원본 임베드 스키마(`08`)의 배열 형태는 프론트 어댑터에서만 다룬다.
4. **최신본 규약.** 운항 데이터는 최신 SUCCESS run 기준([02](./02-db-integration.md) §3). 응답 메타에 출처 run·데이터 기간·검증 경고를 포함.
5. **캐시 정책.** 참조 데이터는 장기 캐시(`Cache-Control: public, max-age`), 운항 데이터는 짧은 캐시 또는 no-store.
6. **좌표·시간.** 좌표는 `[lat, lon]`, 시간은 KST 문자열 그대로.

## 2. 공통 응답 봉투

```json
{
  "data": { /* 또는 [ ... ] */ },
  "meta": {
    "source": "reference-static | processed_flight_data | ...",
    "run_id": "uuid | null",
    "data_period": "20260101-20260131 | null",
    "warnings": [ "ACDM 검토필요 139건 제외" ]
  }
}
```
- 참조 데이터는 `run_id`/`data_period`가 `null`.
- 경로추천(ODR2, §4.1)은 `data_period`(배치가 실제로 집계한 날짜 범위, `batch/build_odr2.py`가 `odr2_meta.json`에 기록)를 채운다. `run_id`는 null로 둔다 — "일자별 최신 run 우선"(§3.2) 특성상 날짜별로 승자 run이 다를 수 있어 단일 run_id로 환원할 수 없기 때문.
- 에러 응답은 표준 봉투 `{"error": {"code": "BAD_REQUEST|NOT_FOUND|VALIDATION_ERROR|RATE_LIMITED|SERVICE_UNAVAILABLE|INTERNAL_ERROR", "message": "..."}}` 하나로 통일한다(`app/envelope.py:error_envelope`, `main.py`의 `HTTPException`/`RequestValidationError`/`Exception` 핸들러와 `middleware.py`의 429가 전부 이 함수를 거친다). 라우터가 FastAPI 기본값(`{"detail": ...}`)을 그대로 흘려보내지 않도록 개별 라우터가 아니라 앱 전역에서 재포장한다.

## 3. 참조 데이터 엔드포인트 (정적 아티팩트 · 장기 캐시)

원천: `비행경로추천서비스_이식패키지/사전빌드_JSON`(또는 재파싱본). DB 미경유.

| 엔드포인트 | 반환 | 원본 스키마(08) | 필터 |
|---|---|---|---|
| `GET /api/reference/airways` | 항공로 구간 | AW `[ident,seqId,lat1,lon1,lat2,lon2,upper,lower]` | `bbox`, `zoom` |
| `GET /api/reference/airports` | 공항 | AP `[ICAO,name,lat,lon,elevFt,type]` | `bbox`, `zoom`, `type` |
| `GET /api/reference/navaids` | 항행시설 | NV `[ident,name,type,lat,lon,freq]` | `bbox`, `zoom` |
| `GET /api/reference/firs` | FIR 폴리곤 | FR `[icao,engName,[flat폴리곤...]]` + LBL 라벨점 | `icao`(콤마목록, 결정 포커스 모드에서 경유 FIR만 조회), `bbox` |
| `GET /api/reference/waypoints` | 항로 픽스 | WP `[ident,lat,lon,ctry]` | `bbox`, `zoom`, `limit`(상한 800) |
| `GET /api/reference/tca` | 접근관제구역 | TCA + TCALBL | `bbox` |
| `GET /api/reference/acc-sectors` | ACC 관제섹터 | ACCS `{acc:{IN,DG}, sectors:[...]}` | — |
| `GET /api/reference/firko` | FIR 한국어명 | FIRKO `{ICAO:한글명}` | — |
| `GET /api/reference/sidstar` | (2단계) SID/STAR | SS | `airport` |
| `GET /api/reference/suas` | (2단계) 특수사용공역 | SU/SUW | `bbox`,`scope` |

- `bbox=minLat,minLon,maxLat,maxLon`, `zoom=<int>` — 서버가 줌별 표시 규칙(원본 `03`)을 적용해 반환량을 줄인다.
- 응답 형태는 키 기반 객체 배열(예 airways: `{ident, seq, a:[lat,lon], b:[lat,lon], upper, lower}`) — 프론트 어댑터가 04-A 사전투영 입력으로 변환.

> **구현 범위(2026-07-22)**: MVP DoD([05](./05-mvp-scope.md) §2.4 "참조 지도 6종")에 필요한 firs·tca·airways·airports·navaids·waypoints만 우선 구현했다.
> - `acc-sectors`·`sidstar`·`suas`는 FIR 분석 패널·2단계 기능 전용이라 이번 라운드 대상이 아니다.
> - `firko`는 **소스 자체가 없다**: `사전빌드_JSON/`에 `firko.json`이 존재하지 않고(원본 HTML에만 내장돼 있을 가능성), 임의로 한글 FIR명을 만들어 넣지 않는다(허위 정보 생성 금지 원칙). 필요해지면 원본 HTML에서 `FIRKO` const 블록만 스크립트로 추출(전체 Read 금지, §6)해 아티팩트로 남길 것.
> - `zoom`은 파라미터로는 받되(airways/airports/navaids/waypoints), 원본 `문서/03`이 airports "저배율은 민간/공용만" 외에는 구체적 수치 임계값을 규정하지 않아 실제 씨닝 로직은 아직 붙이지 않았다 — 프론트(F5/F9) 연동 시 실사용 줌 레벨을 보고 확정.
> - **확정(2026-07-22, Stage 2 F5/F9 연동)**: 공항 저배율(민간/공용만) 임계는 `frontend/js/config.js`의 `display.airportFullTypeZoom=5`로 **프론트 클라이언트 측**에서 적용한다(전세계/지역 컨텍스트 모드에서 공항 전량을 한 번 받아 zoom에 따라 표시 그룹만 토글 — 서버 재요청 없음). 서버 쿼리 파라미터 `zoom`은 이번 라운드에서도 씨닝을 적용하지 않은 채로 남겨둔다(요청 파라미터 자체는 받아 검증만 하고 무시) — 항공로/픽스/항행시설의 줌별 반환량 축소(타일화)는 [05-mvp-scope](./05-mvp-scope.md) §3 2단계("참조 지오메트리 타일화")로 이관.

## 4. 운항·분석 엔드포인트 (DB `processed_*` · 최신본 규약)

> **MVP 범위는 4.1(경로추천)만.** 4.2~4.4(ACDM·FOIS·흐름관리)는 **2단계**([05-mvp-scope](./05-mvp-scope.md) §3)로 이관됨 — Stage 1 산출물 아님. 명세는 2단계 착수 시 참조하도록 미리 남겨둔다.
>
> **2026-07-22 2단계 착수**: 4.3(FOIS 지연원인)을 난이도·선행조건이 가장 낮은 항목으로 먼저 구현([05](./05-mvp-scope.md) §3, [07-checklist](./07-checklist.md) "2단계 — FOIS 지연원인 패널"). 4.2·4.4는 여전히 미착수.

### 4.1 경로추천
| 엔드포인트 | 설명 | 출처 |
|---|---|---|
| `GET /api/routes/od-pairs` | 출발/도착 OD 쌍 목록(편수순) — ROUTE 패널 select 채움 | 집계(ODR2) |
| `GET /api/routes?dep={ICAO}&arr={ICAO}` | 특정 OD의 경로옵션 목록 | 집계(ODR2) |

`/api/routes` 응답 `data`(키 기반, ODR2 배열을 객체로 매핑):
```json
{
  "dep": "VHHH", "arr": "RKSI", "total_flights": 743,
  "options": [
    {
      "flights": 740, "avg_min": 463, "delay_count": 375, "heavy_count": 179,
      "enroute_firs": ["VHHK","RCAA","RJJJ","RKRR"],
      "incheon_track_fixes": ["ATOTI","TESIM"],
      "track_coords": [[lat,lon], ...],
      "full_route_coords": [[lat,lon], ...],
      "cruise_parity": "O"
    }
  ]
}
```
- 집계 산출·좌표해석은 [02](./02-db-integration.md) §4 (배치). 이 API는 사전집계 결과를 서빙.

### 4.2 공항 운항(ACDM KPI) — (2단계)
| 엔드포인트 | 설명 | 출처 | 정렬키 |
|---|---|---|---|
| `GET /api/airports/{icao}/ops?date_from=&date_to=` | 출발·도착 정시성/택시/CTOT 준수 KPI 요약 | `processed_acdm_departure`, `processed_acdm_arrival` | `operation_date+airport_icao+flight_icao` |

집계에 쓰는 물리 컬럼(확정): 출발 `departure_punctuality_min, taxi_out_additional_min, ctot_slot_adherence, ttot, ctot`; 도착 `arrival_punctuality_min, actual_taxi_in_min, fir_to_app_min, final_approach_min, eldt, aldt`. 필터: `operation_date`, `airport_icao`.

응답 예(키 기반, 물리 컬럼은 어댑터로 매핑):
```json
{
  "icao": "RKPC",
  "departure": { "flights": 1234, "on_time_rate": 0.87, "avg_taxi_out_min": 14.2, "ctot_adherence": 0.91 },
  "arrival":   { "flights": 1201, "on_time_rate": 0.90, "avg_taxi_in_min": 7.8, "avg_fir_to_app_min": 22.1 }
}
```

### 4.3 지연원인(FOIS) — 구현됨(2단계 착수, 2026-07-22)
| 엔드포인트 | 설명 | 출처 | 정렬키 |
|---|---|---|---|
| `GET /api/fois/delays?direction=dep\|arr&airport=&date_from=&date_to=` | 지연 사유 원인 대/소분류별 집계 | `processed_fois_departure`, `processed_fois_arrival` | `flight_no+dep_date`(출발) / `flight_no+arr_date`(도착) |

집계 물리 컬럼: `cause_major, cause_minor, cause_process, involved_party, reason`(이 5개 조합으로 group by). 필터: `direction`(필수, dep\|arr) · `airport`(선택, ICAO 4자리 — direction별로 `dep_airport`/`arr_airport`에 매칭) · `date_from`/`date_to`(선택, `YYYY-MM-DD` — direction별로 `dep_date`/`arr_date`에 매칭). `date_from > date_to`는 400.

조회는 [02](./02-db-integration.md) §3 "최신본 뷰"(`latest_run.latest_view`)로 일자별 최신 run만 대상. ODR2(§4.1)와 동일한 이유로 `run_id`는 항상 null(날짜별 승자 run이 다를 수 있어 단일 값으로 환원 불가) — 대신 `data_period`는 이번 조회에서 실제로 걸린 날짜의 min/max(결과 0건이면 null).

응답 예:
```json
{
  "data": {
    "airport": "RKSI",
    "direction": "dep",
    "total": 42,
    "causes": [
      { "cause_major": "기상", "cause_minor": "강풍", "cause_process": "지상활주", "involved_party": "공항", "reason": "TAILWIND", "count": 12 }
    ]
  },
  "meta": { "source": "processed_fois", "run_id": null, "data_period": "20260101-20260131", "warnings": [] }
}
```

프론트: `frontend/js/fois-panel.js`(F6 ROUTE 패널과 독립된 조회 도구, `panel-right`에 배치) + `js/api.js:foisDelays`. store.js 전역 상태에 얹지 않음(뷰모드·OD 선택과 무관).

### 4.4 흐름관리 (자체 전처리분만) — (2단계)
| 엔드포인트 | 설명 | 출처 | 정렬키 |
|---|---|---|---|
| `GET /api/flow-management?date_from=&date_to=&fir=&airway=` | 적용 흐름관리 조치 목록 | `processed_flow_management` | `flow_id` |

응답/필터 물리 컬럼: `apply_start_dt, apply_end_dt, apply_minutes, minit, mit, alt_speed_limit, target_airport, target_fir, target_route, target_fix, restriction_summary, quality_status`. 필터: `record_date`/`apply_start_dt`, `target_fir`, `target_route`.

> **비행편 영향 결합은 제외.** 원본 `03`의 "흐름관리 탭(비행편 영향)"은 통합데이터·영향상세 테이블에 의존하며, 그 테이블은 전처리 1단계에서 제외됨([02](./02-db-integration.md) §2). 3단계로 보류.

## 5. 기상 — 신규 구현 없음

공항 기상(METAR/TAF)·CORS 프록시·TTS는 기존 Node `aviation-weather-mcp`가 담당한다. FastAPI는 이를 **재구현하지 않는다.** 프론트는 기존 폴백 체인(직접 → `localhost:3000/proxy` → 공개 프록시)을 그대로 사용한다. 계약은 `비행경로추천서비스_이식패키지/문서/07_기상MCP서버.md`.

RainViewer·Open-Meteo·ADS-B도 브라우저가 직접 호출(CORS 차단분만 Node 프록시). FastAPI 경유 없음.

## 6. 데이터 출처 요약표

| 데이터 | 출처 | 갱신 | 캐시 |
|---|---|---|---|
| 항공로/공항/항행시설/FIR/픽스/TCA/ACC섹터 | 정적 아티팩트(참조 지오메트리) | 월·분기 | 장기 |
| 경로추천(ODR2) | 배치 집계(`processed_flight_data` 유래) | 새 run | 중간 |
| ACDM 정시성/KPI | `processed_acdm_*` (최신 run) | 새 run | 짧음 |
| FOIS 지연원인 | `processed_fois_*` (최신 run) | 새 run | 짧음 |
| 흐름관리 | `processed_flow_management` (최신 run) | 새 run | 짧음 |
| 기상/레이더/상층풍/ADS-B | 외부 API(브라우저 직접, Node 프록시) | 실시간 | 없음 |

## 7. 비기능 요건 (MVP)
- 페이지네이션: 대량 목록(픽스, 흐름관리)에 `limit`/`offset` 또는 커서.
- CORS: 프론트 도메인 허용.
- 에러: 표준 `{error:{code,message}}`. DB 미가용 시 503, 잘못된 ICAO 400.
- 관측성: 요청/쿼리 시간 로깅, 조회한 `run_id` 기록.
