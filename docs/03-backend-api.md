# 03. 백엔드 API 명세 (FastAPI, 읽기 전용)

- 문서 버전: 1.1
- 작성일: 2026-07-21
- 대상: 이 서비스의 백엔드를 구현할 개발자
- 관련 문서: [01-architecture](./01-architecture.md), [02-db-integration](./02-db-integration.md), [04-frontend-migration](./04-frontend-migration.md), [07-checklist](./07-checklist.md)
- 범위: **MVP 기준**. 향후 확장 엔드포인트는 [05-mvp-scope](./05-mvp-scope.md)에서 관리.
- 물리 컬럼명은 [DB스키마 §9](../data-ingestion-backend/docs/DB스키마.md) 확정본을 따르며, 쿼리는 `column_map.py`(논리↔물리 단일 출처)를 경유한다.

## 1. 설계 원칙

1. **읽기 전용.** 모든 엔드포인트는 GET. 쓰기 없음.
2. **데이터 출처 이원화.** 참조 지오메트리(DB `reference_*`, 장기 캐시)와 운항·분석(DB `processed_*`)을 경로 네임스페이스로 구분한다: `/api/reference/*` vs 나머지. 2026-07-23 이전에는 참조 데이터가 정적 JSON 파일이었으나(§3 이전 버전), 전부 `reference_*` DB 테이블로 이관됐다 — 여전히 논리적으로는 "정적/장기 캐시 데이터"라 캐시 정책·응답 봉투 규약(§2, §5)은 그대로다.
3. **키 기반 JSON.** 응답은 객체 키로 내보내 프론트가 배열 인덱스·물리 컬럼명에 의존하지 않게 한다([06-conventions](./06-conventions.md)). 원본 임베드 스키마(`08`)의 배열 형태는 프론트 어댑터에서만 다룬다.
4. **최신본 규약.** 운항 데이터는 최신 SUCCESS run 기준([02](./02-db-integration.md) §3). 응답 메타에 출처 run·데이터 기간·검증 경고를 포함.
5. **캐시 정책.** 참조 데이터는 장기 캐시(`Cache-Control: public, max-age`), 운항 데이터는 짧은 캐시 또는 no-store.
6. **좌표·시간.** 좌표는 `[lat, lon]`, 시간은 KST 문자열 그대로.

## 2. 공통 응답 봉투

```json
{
  "data": { /* 또는 [ ... ] */ },
  "meta": {
    "source": "reference-db | processed_flight_data | ...",
    "run_id": "uuid | null",
    "data_period": "20260101-20260131 | null",
    "warnings": [ "ACDM 검토필요 139건 제외" ]
  }
}
```
- 참조 데이터는 `run_id`/`data_period`가 `null`.
- 경로추천(ODR2, §4.1)은 `data_period`(배치가 실제로 집계한 날짜 범위, `batch/build_odr2.py`가 `odr2_meta.json`에 기록)를 채운다. `run_id`는 null로 둔다 — "일자별 최신 run 우선"(§3.2) 특성상 날짜별로 승자 run이 다를 수 있어 단일 run_id로 환원할 수 없기 때문.
- 에러 응답은 표준 봉투 `{"error": {"code": "BAD_REQUEST|NOT_FOUND|VALIDATION_ERROR|RATE_LIMITED|SERVICE_UNAVAILABLE|INTERNAL_ERROR", "message": "..."}}` 하나로 통일한다(`app/envelope.py:error_envelope`, `main.py`의 `HTTPException`/`RequestValidationError`/`Exception` 핸들러와 `middleware.py`의 429가 전부 이 함수를 거친다). 라우터가 FastAPI 기본값(`{"detail": ...}`)을 그대로 흘려보내지 않도록 개별 라우터가 아니라 앱 전역에서 재포장한다.

## 3. 참조 데이터 엔드포인트 (`reference_*` DB · 장기 캐시)

원천(2026-07-23 DB 전환): FIR/TCA/항공로/공항/항행시설/픽스 6종은 `비행경로추천서비스_이식패키지/사전빌드_JSON`을 `data-ingestion-backend/scripts/migrate_static_reference_to_db.py`로 1회 이관한 `reference_*` 테이블. `sidstar`는 Jeppesen(ARINC 424 계열) 항행DB 원본 CSV 4종을 `data-ingestion-backend/scripts/ingest_jepp_nav.py`로 적재한 `reference_sid`/`reference_star`/`reference_waypoint_enroute`/`reference_waypoint_terminal`에서 fix_id→좌표 해석(터미널→엔루트→navaid 우선순위 조인, `backend/app/queries/reference.py:_resolve_fix`)으로 조립한다. `processed_*`(운항 데이터)와 달리 run_id/최신-run 윈도잉이 없는 정적 마스터 데이터.

| 엔드포인트 | 반환 | 원본 스키마(08) | 필터 |
|---|---|---|---|
| `GET /api/reference/airways` | 항공로 구간 | AW `[ident,seqId,lat1,lon1,lat2,lon2,upper,lower]` | `bbox`, `zoom` |
| `GET /api/reference/airports` | 공항 | AP `[ICAO,name,lat,lon,elevFt,type]` | `bbox`, `zoom`, `type`, `icao`(콤마목록, 있으면 bbox/type 완전히 무시 — 부트 시 A/B만 받은 목록에 없는 타입의 dep/arr 공항을 focus 모드에서 보강 조회할 때 사용, 2026-07-23) |
| `GET /api/reference/navaids` | 항행시설 | NV `[ident,name,type,lat,lon,freq]` | `bbox`, `zoom` |
| `GET /api/reference/firs` | FIR 폴리곤 | FR `[icao,engName,[flat폴리곤...]]` + LBL 라벨점 | `icao`(콤마목록, 결정 포커스 모드에서 경유 FIR만 조회), `bbox` |
| `GET /api/reference/waypoints` | 항로 픽스 | WP `[ident,lat,lon,ctry]` | `bbox`, `zoom`, `limit`(상한 800) |
| `GET /api/reference/tca` | 접근관제구역 | TCA + TCALBL | `bbox` |
| `GET /api/reference/acc-sectors` | ACC 관제섹터 | ACCS `{acc:{IN,DG}, sectors:[...]}` | — |
| `GET /api/reference/firko` | FIR 한국어명 | FIRKO `{ICAO:한글명}` | — |
| `GET /api/reference/sidstar` | SID/STAR(한국만, Jeppesen 항행DB 이관) | `{proc,name,airport,coords}` (좌표는 fix 해석으로 조립, 원본 CSV엔 좌표 없음) | `airport`(없으면 전체 반환) |
| `GET /api/reference/suas` | 특수사용공역(SUAS/MOA) | SU/SUW | `bbox`,`region`(`kr`\|`world`) |

- `bbox=minLat,minLon,maxLat,maxLon`, `zoom=<int>` — 서버가 줌별 표시 규칙(원본 `03`)을 적용해 반환량을 줄인다.
- 응답 형태는 키 기반 객체 배열(예 airways: `{ident, seq, a:[lat,lon], b:[lat,lon], upper, lower}`) — 프론트 어댑터가 04-A 사전투영 입력으로 변환.

> **구현 범위(2026-07-22)**: MVP DoD([05](./05-mvp-scope.md) §2.4 "참조 지도 6종")에 필요한 firs·tca·airways·airports·navaids·waypoints만 우선 구현했다.
> - `acc-sectors`는 [13-ai-reasoning-dev-plan](./13-ai-reasoning-dev-plan.md) STEP A4(실시간 섹터 교통·수요예측) 선행으로 **2026-07-24 구현 완료** — `reference_acc_sector`/`reference_acc_boundary` 2개 테이블(`data-ingestion-backend/scripts/migrate_static_reference_to_db.py`가 `acc_sectors.json`에서 이관), bbox 필터 없이 14개 섹터 전체 반환. 한국(인천/대구 ACC)만 커버하는 원본 데이터 한계 그대로(허위로 다른 지역 섹터를 만들지 않음) — `frontend/js/analyze-sectors.js`가 소비.
> - `suas`는 2026-07-24 구현 완료(사용자 요청으로 공역 좌표 DB 편입) — `reference_suas`(지오메트리, `ident/name/type/upper/lower/polygon/region`)를 응답한다. **발효시간(A7, [13](./13-ai-reasoning-dev-plan.md) STEP A7, 2026-07-24 구현 완료)**: `eff_times_raw`/`schedule_status`(`structured`\|`confirm_required`\|`null`=배치 미실행)/`schedule_segments`(`structured`일 때만 `[{days,utc_start,utc_end}, ...]`)를 `ident`로 애플리케이션 레벨 조인해 덧붙인다 — DAFIF `SUAS_PAR.TXT`의 `EFF_TIMES`는 완성본조차 버린 필드라 `backend/batch/build_suas.py`(advisor 소유, 별도 테이블 `advisor_suas_schedule`)가 원본에서 직접 파싱한다. 비정형(`SR-SS`/`BY NOTAM`/공휴일 예외 등)은 발효 여부를 단정하지 않고 `confirm_required`로만 표시(안전 우선, 창작·억측 금지). `frontend/js/route-bottlenecks.js`(A5)가 경로-폴리곤 교차 + 통과 예상시각으로 판정해 병목 후보(`kind:"airspace"`)에 반영.
> - **`sidstar`는 2026-07-23 사용자 요청으로 추가 구현**(원래 2단계 예정이었으나 범위 변경), 같은 날 **Jeppesen 항행DB CSV 이관으로 데이터 갭 해소**: 기존 사전빌드 `sidstar.json`(SID 14·STAR 103, 한국 17개 공항 부분 커버, 인천 SID·김포 전체 결측)은 이식 패키지 자체의 데이터 한계였다 — Jeppesen 원본 CSV 4종(SID/STAR/엔루트·터미널 지점) 적재로 인천·김포 포함 전 공항 SID+STAR 온전히 커버. `proc`(1=SID,2=STAR) 그대로 반환, bbox 없이 `airport` 단일 필터만. 프론트는 경로 선택 시 출발 공항의 SID·도착 공항의 STAR만 걸러 표시([04](./04-frontend-migration.md), `layers/route.js` `renderSidStar`) — 이 프론트 동작 자체는 무변경.
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
      "cruise_parity": "O",
      "gate_in": "ATOTI", "gate_out": "OLMEN",
      "runway_dist": [["33L", 80], ["15R", 13], ["34R", 7]]
    }
  ]
}
```
- 집계 산출·좌표해석은 [02](./02-db-integration.md) §4 (배치). 이 API는 사전집계 결과를 서빙.
- **터미널 신호(A6, [13](./13-ai-reasoning-dev-plan.md) STEP A6, 2026-07-24 구현 완료)**: `gate_in`/`gate_out`은 이 경로그룹의 최빈 진출입 게이트(`processed_flight_data.entry_fir`/`exit_fir`에서 — 컬럼명과 달리 실측상 FIR 코드가 아니라 5자 픽스명, 예: `KARBU`), 결측이면 `null`. `runway_dist`는 출발 활주로 분포(`[[활주로, pct], ...]`, `processed_acdm_departure.runway`를 callsign=flight_icao·date=operation_date로 조인 — 실측 매칭률 99.9%), 매칭 없으면 `[]`. 완성본은 이 정보를 OD 단위 `odInfo`에 뒀지만 D20 확정([14](./14-improvement-request.md) §8 C-2)에 따라 advisor는 경로그룹 단위로 노출한다(경로옵션마다 실제 진출입 게이트/활주로가 다를 수 있어 OD 전체로 뭉치면 정보 손실). 이건 **표시·근거용**이며 터미널 *최적화*(활주로 혼잡 등)는 후속.

### 4.2 공항 운항(ACDM KPI) — 구현됨(2단계, 2026-07-23)
| 엔드포인트 | 설명 | 출처 | 정렬키 |
|---|---|---|---|
| `GET /api/airports/{icao}/ops?date_from=&date_to=` | 출발·도착 정시성/택시/CTOT 준수 KPI 요약 | `processed_acdm_departure`, `processed_acdm_arrival` | 없음(전체 집계, `airport_ops.py`) |

집계에 쓰는 물리 컬럼(구현 기준 — ACDM 스킬이 이미 계산해 둔 파생 KPI 컬럼만 쓴다.
원시 마일스톤(`ttot/ctot/eldt/aldt` 등)에서 직접 다시 계산하지 않는다, 스킬을 블랙박스로
다루는 원칙): 출발 `departure_punctuality_min, taxi_out_additional_min,
ctot_slot_adherence`; 도착 `arrival_punctuality_min, actual_taxi_in_min,
fir_to_app_min`. 필터: `airport_icao`(경로 파라미터), `operation_date`(선택).

이 컬럼들은 DB에 **text로 저장**(스킬의 `number_text()`가 NaN을 NULL이 아닌 빈
문자열로 직렬화)돼 있어, 집계 전 `nullif(col, '')`로 빈 문자열을 NULL로 바꾼 뒤
`cast(..., Numeric)`한다(`airport_ops.py:_numeric()`). `ctot_slot_adherence`는 숫자가
아니라 범주 문자열("CTOT없음"/"계산불가"/"조기"/"준수"/"지연") — "조기"+"준수"+"지연"을
분모, "준수"를 분자로 `ctot_adherence`를 계산한다("CTOT없음"·"계산불가"는 판정 대상이
아니므로 분모에서 제외).

**`on_time_rate` 임계값 확정(2026-07-23)**: 원본 스킬 계약·전처리 스크립트 어디에도
"정시" 판정 임계가 없어(부호·단위만 정의) EUROCONTROL/ICAO 산업표준 On-Time
Performance 정의(스케줄 대비 15분 이내, 조기는 항상 정시)를 채택했다
(`punctuality_min <= 15`). 도메인 판정값이라 재검토 필요 시 이 값만 바꾸면 된다
(`airport_ops.py:_ON_TIME_THRESHOLD_MIN`).

응답 예(키 기반, 물리 컬럼은 어댑터로 매핑):
```json
{
  "icao": "RKPC",
  "departure": { "flights": 1234, "on_time_rate": 0.87, "avg_taxi_out_min": 14.2, "ctot_adherence": 0.91 },
  "arrival":   { "flights": 1201, "on_time_rate": 0.90, "avg_taxi_in_min": 7.8, "avg_fir_to_app_min": 22.1 }
}
```

`run_id`는 ODR2(§4.1)·FOIS(§4.3)와 동일한 이유로 항상 null. `data_period`는 출발·도착
양쪽을 합친 실제 걸린 날짜의 min/max(둘 다 0건이면 null).

프론트: `frontend/js/ops-panel.js`(FOIS/흐름관리 패널과 동일하게 OD 선택·뷰모드와
무관한 독립 조회 도구) + `js/api.js:airportOps`.

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

### 4.4 흐름관리 (자체 전처리분만) — 구현됨(2단계 착수, 2026-07-23)
| 엔드포인트 | 설명 | 출처 | 정렬키 |
|---|---|---|---|
| `GET /api/flow-management?date_from=&date_to=&fir=&airway=&limit=&offset=` | 적용 흐름관리 조치 목록(페이지네이션) | `processed_flow_management` | `apply_start_dt`(1차) + `flow_id`(2차, 동률 타이브레이커) |

응답/필터 물리 컬럼: `apply_start_dt, apply_end_dt, apply_minutes, minit, mit, alt_speed_limit, target_airport, target_fir, target_route, target_fix, restriction_summary, quality_status`. 필터: `date_from`/`date_to`(선택, `YYYY-MM-DD` — [02](./02-db-integration.md) §3 최신본 뷰의 날짜 컬럼인 `record_date`에 매칭. 문서 초안이 언급한 `apply_start_dt` 필터는 채택하지 않음 — 최신본 윈도우 계산이 `record_date` 기준이라 필터도 같은 컬럼을 써야 윈도우·필터가 어긋나지 않는다) · `fir`(선택, 영문·숫자 1~10자 — `target_fir` 대소문자 무시 완전일치. 실측상 콤마 목록이 아니라 단일 값이라 부분일치 대신 완전일치 채택) · `airway`(선택, 동일 검증 — `target_route` 완전일치). `limit`(기본 100, 최대 500) · `offset`(기본 0) — [03 §7](#7-비기능-요건-mvp) "대량 목록(흐름관리)에 페이지네이션" 요건 반영.

`run_id`는 §4.1/§4.3과 동일한 이유로 항상 null. `data_period`는 페이지네이션 전 필터링된 전체 집합의 `record_date` min/max(결과 0건이면 null) — `total`도 이 페이지가 아니라 필터 전체 기준.

응답 예:
```json
{
  "data": {
    "items": [
      { "flow_id": "FLOW_20260101_0002", "apply_start_dt": "2026-01-01 04:30", "apply_end_dt": "2026-01-01 07:00", "apply_minutes": "150", "minit": null, "mit": null, "alt_speed_limit": null, "target_airport": null, "target_fir": "RKRR", "target_route": null, "target_fix": null, "restriction_summary": "...", "quality_status": "정상" }
    ],
    "total": 42, "limit": 100, "offset": 0
  },
  "meta": { "source": "processed_flow_management", "run_id": null, "data_period": "20260101-20260131", "warnings": [] }
}
```

프론트: `frontend/js/flow-management-panel.js`(FOIS 패널과 동일하게 store.js 전역 상태와 무관한 독립 조회 도구, `panel-right`에 배치, "더 보기" 버튼으로 offset 누적 로드) + `js/api.js:flowManagement` + `js/adapters.js:toFlowManagementItem`.

> **비행편 영향 결합은 제외.** 원본 `03`의 "흐름관리 탭(비행편 영향)"은 통합데이터·영향상세 테이블에 의존하며, 그 테이블은 전처리 1단계에서 제외됨([02](./02-db-integration.md) §2). 3단계로 보류.

### 4.5 AI 근거화 모드 C(백엔드 프록시) — 스켈레톤만, 비활성([13](./13-ai-reasoning-dev-plan.md) STEP C4, D9)
| 엔드포인트 | 설명 | 상태 |
|---|---|---|
| `POST /api/reasoning/complete` (body: `{system, user}`) | 모드 C(자동 호출) 스텁 | **항상 501** — `REASONING_PROXY_ENABLED=false`(기본) 또는 제공자/모델 미확정([14](./14-improvement-request.md) §8.1 C-7) |

`processed_*`/`reference_*`를 소비하지 않는다(위 표들과 무관) — 프론트의 `reasoning-context.js`(B2)·`reasoning-prompt.js`(C1)가 이미 만든 `{system, user}`를 그대로 받아 향후 외부 LLM으로 중계하는 자리만 예약해 둔 것. 요청 본문 크기 상한은 `MAX_REQUEST_BODY_BYTES`([06](./06-conventions.md) §1, `middleware.py::MaxBodySizeMiddleware`). 상세 계약·보안 규약은 `backend/app/routers/reasoning.py` 모듈 docstring이 단일 출처.

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
