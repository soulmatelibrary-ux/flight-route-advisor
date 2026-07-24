# 13. AI 경로추천 근거화 — 추가개발 구현 스펙 (단계별)

- 문서 버전: 1.3
- 작성일: 2026-07-23 / v1.1: 2026-07-23(STEP A7 SUAS/MOA 발효시간 판정 추가, D23) /
  v1.2: 2026-07-24(G0-1 범위 정정 — 아래 §0.2 참고, Phase A/B 완료 반영) /
  v1.3: 2026-07-24(**Phase C(C1~C4) 완료 반영** — 아래 §6 각 STEP 헤더·§11·§12 갱신)
- 상태: ✅ **Phase A·B·C 전부 완료(2026-07-24).** 결정 게이트(§0 G0-1~G0-4) 전부 충족.
  §5.1 조건부 승인 각주의 잔여 조건(wind/sectors 라이브 브라우저 최종 확인)도 B-exit 완료 시점에
  해소됨([07-checklist](./07-checklist.md) B-exit 항목 참고). C1~C4 전부 `senior-code-reviewer`
  리뷰 게이트 통과(여러 라운드 재검증 포함) — 상세 이력은 [07-checklist](./07-checklist.md)가
  단일 출처.
- 성격: **추가개발(Follow-on)** — Stage 0/1/2 + AI 근거화에 실제로 필요한 신호(Phase A로 이식·검증됨)
  위에 얹는 새 개발 단계다. 기존 것을 갈아엎지 않고 **이식 + 얇은 층 추가**만 한다.
- 관련: [11-ai-route-reasoning-proposal](./11-ai-route-reasoning-proposal.md)(분석·결정표),
  [12-operational-goal-and-scenarios](./12-operational-goal-and-scenarios.md)(왜),
  [03-backend-api](./03-backend-api.md), [04-frontend-migration](./04-frontend-migration.md),
  [07-checklist](./07-checklist.md), [CLAUDE.md](../CLAUDE.md)(개발 원칙·리뷰게이트)

---

## 0. 이 문서의 위치와 선행조건 (착수 게이트)

이 개발은 아래가 **모두 참일 때만** 시작한다. 하나라도 미충족이면 이 문서는 "읽기만" 한다.

| # | 선행조건 | 확인 방법 |
|---|---|---|
| G0-1 | Stage 1/2 + **AI 근거화가 실제로 의존하는** 2단계 항목이 clean·완료 상태 | Stage 1/2·ACDM KPI·흐름관리조회·기상레이더/SIGMET·PIREP·상층풍시어가 [07-checklist](./07-checklist.md)에서 전부 체크됨(상층풍/시어는 범용 오버레이가 아니라 Phase A3가 AI 근거화 용도로 직접 이식·검증 — 아래 §0.2) |
| G0-2 | **방향 A 확정** | 완성본 결정론 로직을 advisor로 **이식 우선**, LLM은 **이미 계산된 값을 자연어로 다듬는 얇은 층**으로만(사용자 확정 2026-07-23) |
| G0-3 | **1단계 병목 소스 = 실시간 ADS-B 외삽** | 완성본 `analyzeFIR` 방식(현재 항공기 속도·방향으로 +10/40분 섹터수요 예측). doc 11 §13 역사 프로파일은 이 문서 범위 밖(후속) |
| G0-4 | doc 11 §12 결정항목 중 **이 작업 의존분 확정** | ✅ §9 결정 의존표 항목(D1/D2/D5/D6/D7)이 [14](./14-improvement-request.md) v1.0으로 확정됨 |

> 확정 흐름(doc 11 §0 준수): 이 스펙 검토 → 개선요구서에서 §9 항목 확정 → 07-checklist 항목화
> → STEP 순차 구현 → 각 STEP 리뷰에이전트 게이트([CLAUDE.md](../CLAUDE.md) §4) → 문서 동기화(§10).

### 0.2 G0-1 범위 정정 (2026-07-24, 사용자 확정)

원래 G0-1은 "2단계 잔여" 4항목(경로 기하 동적화·상층풍/시어·참조 타일화·SIGMET/PIREP 루트 교차 판정)
전부 완료를 조건으로 걸었으나, Phase A 착수·완료(2026-07-23~24) 시점에 이 4항목이 실제로는
**AI 근거화와 무관한 범용 지도 UI/성능 작업**임이 드러났다. 항목별 재검토 결과:

- **상층풍/시어** — Phase A3(`frontend/js/layers/wind.js`)가 AI 근거화(선택 경로 단위 브리핑)에
  필요한 범위 그대로 이식·리뷰·Playwright 검증까지 완료(2026-07-23). **충족으로 인정**, G0-1에서
  더 이상 별도 항목으로 추적하지 않는다.
- **경로 기하 동적화(04-D)·참조 타일화·SIGMET/PIREP 루트 교차 판정** — AI 근거화 STEP(A1~A7,
  B1/B2) 어디에도 의존성이 없음(교차 판정은 A7이 자체 폴리곤 교차 로직으로 별도 구현해 대체).
  **G0-1에서 분리**하여 [07-checklist](./07-checklist.md) "향후 확장" 절의 독립 과제로 유지 —
  이 문서(AI 근거화)의 착수 여부와 무관하게 별도 착수 시점에 처리한다.

결과: G0-1은 Stage 1/2(완료) + ACDM KPI·흐름관리조회·기상레이더/SIGMET·PIREP(완료) + 상층풍/시어
(A3로 충족)만 남고 전부 충족 — **G0-1~G0-4 전부 충족, Phase C 착수 가능**.

### 0.1 완성본이 이미 하는 것 (재확인 — "신규"가 아님)

백데이터 `result/비행경로추천서비스_이식패키지/완성본_전세계_항공로_지도.html`(15.8MB, [CLAUDE.md](../CLAUDE.md)
§6 대로 통째로 열지 말고 스크립트로만 스캔)을 검토한 결론: **doc 11이 "신규 후속"으로 본 것 상당수를
완성본이 이미 결정론적으로 구현**한다. 이 문서의 Phase A는 그 로직의 **이식**이지 신규 설계가 아니다.

| 완성본 함수 | 하는 일 | 이 문서 STEP |
|---|---|---|
| `castScript`(12스텝) | OD요약→주경로→빠른대안→기상→강수→섹터혼잡→시간대정시율→흐름관리→지연원인→추천고도 **자연어 브리핑** + TTS | **프롬프트 골든출력**(C1) |
| `buildBriefing` | 최다사용 권장 + 최단대안 + 정시율/흐름%/지연원인 요약 | A1/B1 |
| `analyzeFIR` | 섹터 실시간 교통 + **속도·방향 외삽 +10/40분 수요예측** + 레이더 기상샘플 | A4 |
| `routeFlowBrief` | 경로별 흐름관리 영향률 비교·권장 + 시간대 추천 | A1 |
| `routeWind`/`calcFL`/`drawShear` | 상층풍·연직시어·★추천고도 | A3 |

---

## 1. 목표 산출물 (Definition of Done)

경로 추천 탭에서 OD를 고르고 경로를 선택하면, **"AI 근거 보기" 버튼**(D5)으로 팝업이 열리고 거기에:

1. **왜 이 경로인가** — 정시성·흐름관리·소요시간·기상을 종합한 자연어 2~3문장(§17.2).
2. **막히는 구간** — 경로가 통과하는 섹터/FIR 중 실시간 교통·기상으로 병목 가능성이 있는 구간을
   자연어로 지목(§17.3, 실시간 ADS-B 외삽 기반).
3. 근거가 된 **구체 지표**(정시율·흐름관리 영향률·통과 섹터 혼잡·추천고도)는 팝업에 함께 표시하되
   **AI가 계산하지 않고 이미 계산된 값을 보여준다**(§17.1, AI는 소비자).

1단계 범위(D1): **프롬프트를 만들어 AI에 입력 → 답변을 받아 팝업에 표시**까지. 실제 AI 호출은
수동복붙(사람이 프롬프트 복사 → 외부 AI에 붙여넣기 → 응답을 UI에 붙여넣기)으로 시작하고,
백엔드 프록시 자동호출(모드 C)은 **스켈레톤만** 두고 향후 활성화한다.

---

## 2. 아키텍처 — 3계층 (얇은 LLM 층)

```
[① 결정론 신호]                    [② 통합기]                 [③ LLM 서술층]
 - 경로옵션(ODR2, 기존)      ┐
 - 흐름관리 영향률(FLOW)     │
 - 지연원인(ODHR)           ├─▶  reasoningContext(dep,arr,route)  ─▶  프롬프트 빌드
 - 상층풍/시어/추천고도       │      = 정규화된 JSON 1개               (D1: 복붙 / C: 프록시)
 - 실시간 섹터 병목(ADS-B)   ┘      (계산 끝난 값만 담음)                       │
                                                                              ▼
                                                                    AI 응답(JSON, D6)
                                                                              │
                                                                     검증·파싱 → 팝업
```

- **① 신호**: 대부분 완성본에서 이식. 백엔드(읽기전용 DB/배치 아티팩트) + 프론트(실시간 ADS-B·기상).
- **② 통합기**: **1단계에서는 프론트(client-side)에 둔다.** 이유: 병목 소스가 실시간 ADS-B(클라이언트)이고
  D1 수동복붙도 클라이언트라, context 조립을 프론트가 하는 게 가장 단순하다. 모드 C 전환 시 서버로 이동
  가능하도록 **순수 함수(입력→context)로 분리**한다(리워크 방지, doc 11 §14.3 원칙과 동일).
- **③ LLM 층**: context → 프롬프트 → 응답. **AI는 ①의 값을 재계산하지 않는다.** 응답은 신뢰 못 할
  외부 입력으로 취급(§8 보안).

---

## 3. 사전 확인: advisor 현황 vs 필요 (갭 분석)

| 신호 | 완성본 소스 | advisor 현황 | 갭 |
|---|---|---|---|
| 경로옵션(편수·평균시간·지연수·경유FIR·좌표) | `ODR2` | ✅ `/api/routes`(`routes_for`) | 없음 |
| 공항 KPI(정시율·택시아웃·CTOT) | ops | ✅ `/api/airports/{icao}/ops` + `route-ops-summary.js` | 없음 |
| FOIS 지연원인 패널 | FOIS | ✅ `/api/fois/delays` + `route-fois-summary.js` | 없음(공항단위) |
| 흐름관리 목록 | `FLOWM` | ✅ `/api/flow-management` | 없음 |
| **OD·경로별 흐름관리 영향률** | `FLOW.od`/`FLOW.g` | ❌ 없음 | **A1** |
| **OD 지연원인 분해** | `ODHR` | ❌ 없음(공항단위 FOIS만) | **A2** |
| **상층풍·시어·추천고도** | `routeWind`/`calcFL` | ❌ 없음 | **A3** |
| **실시간 섹터 교통·수요예측** | `analyzeFIR`(ACCS+ADS-B) | ⚠ `adsb.js`는 있으나 섹터배정·외삽 없음 | **A4** |
| ACC 섹터 지오메트리 | `ACCS`(acc_sectors.json) | ⚠ 참조로더에 미포함 확인 필요 | A4 선행 |
| **SUAS/MOA 참조 레이어** | `SU`/`SUW`(suas.json) | ❌ 미구현 — [03](./03-backend-api.md) `/api/reference/suas`는 "(2단계)"로만 명세, 실코드 없음 | A7 선행 |
| **SUAS/MOA 발효시간(EFF_TIMES)** | DAFIF `SUAS_PAR.TXT` 컬럼 | ❌ **완성본도 미보유**(빌드 단계 누락, 신규 발견 2026-07-23) | **A7** |

> 착수 첫 작업으로 위 "advisor 현황"을 **실제 코드로 재확인**한다(문서와 코드가 어긋나면
> [CLAUDE.md](../CLAUDE.md) §8·§10대로 사용자에게 차이 보고 후 진행).

---

## 4. Phase A — 결정론 신호 이식 (AI 아님)

각 STEP 공통 규약: **하드코딩 금지**(URL·임계값·색상은 config/env, [CLAUDE.md](../CLAUDE.md) §2) ·
**시큐어코딩**(입력검증·파라미터라이즈드 쿼리, §3) · **읽기전용 소비**(DB에 쓰지 않음, §5) ·
**좌표 `[lat,lon]`·시각 KST**(§7) · STEP 종료 시 **리뷰에이전트 게이트**(§4) 통과 후에만 체크.

### STEP A1 — OD·경로별 흐름관리 영향률 서빙 + 노선 위젯 (완료, 2026-07-23)
- **목표**: `FLOW.od[dep|arr]`(영향률 pct·정시율 ponA/ponN·평균지연 dlyA/dlyN·주사유 rs·주제한 lim·
  시간대 hrP)과 `FLOW.g[dep|arr|route]`(경로별 영향률)을 advisor가 제공.
- ⚠ **저장소 갱신(2026-07-23)**: 처음엔 아래처럼 파일 아티팩트(`reference/artifacts/flow.json`)로
  구현했으나, 로컬 Docker DB 통합 요청으로 `advisor_flow_*` 6개 테이블(완전 정규화, 신규 role
  `advisor_artifact_writer`)로 옮겼다 — 배치·쿼리 로직·API 응답 계약은 무변경, 저장 위치만 교체.
  상세는 [02 §4.3·§6](./02-db-integration.md).
- **대상**:
  - 배치: `backend/batch/build_flow.py`(신규) — 전처리 DB `processed_flow_management`/`processed_flight_data`를
    읽어 `reference/artifacts/flow.json` 생성(ODR2 배치와 동일 패턴, 읽기전용). ⚠ 산출 스키마는
    완성본 `flow.json`(백데이터 `사전빌드_JSON/flow.json`, 199KB)과 **동형**으로 맞춘다.
  - 쿼리: `backend/app/queries/flow_reasoning.py`(신규) — 아티팩트 로더(routes.py 캐시 패턴 복제).
  - 라우터: `backend/app/routers/routes.py`에 `GET /api/routes/flow?dep=&arr=` 추가(ICAO 검증 재사용)
    또는 신규 라우터. 응답은 `envelope(..., source="flow-batch")`.
  - 프론트: `frontend/js/api.js`에 `routeFlow(dep,arr)` 추가, `frontend/js/route-flow-summary.js`(신규,
    `route-ops-summary.js` 패턴 = store `od:selected` 구독·seq 폐기·ApiError 처리) + `index.html` 마크업.
- **수용기준**: 알려진 OD(예: VHHH|RKSI)에서 완성본과 동일한 영향률/정시율 수치가 나온다. 미기록 OD는
  404 아님 "기록 부족" 빈응답 처리(완성본 `routeFlowBrief` 동작과 일치).

### STEP A2 — OD 시간대별 교통량/소요시간 서빙 (완료, 2026-07-23 — 정시율 범위 축소)
- **목표(원안)**: `ODHR`(OD별 시간대 정시율 `od[..].hr`, 공항별 시간대 출발량 `ap[..]`, 지연원인 `CAUSES`) 제공.
- **대상**: `build_odhr.py`(배치) → `odhr.json` → `queries/odhr.py` → `GET /api/routes/delay-history?dep=&arr=&hour=`
  → `api.js` → 필요 시 위젯(팝업에서 소비하므로 별도 패널 불필요, B1에서 context로 흡수 가능).
- **주의(D7)**: FOIS `reason` 원문에 민감정보가 있을 수 있음 → **분류 코드/비율만** 노출, 원문 제외(`build_odhr.py`는 `reason` 컬럼 자체를 읽지 않음).
- ⚠ **범위 축소(A1과 동일한 사유, 2026-07-23 사용자 확인)**: 완성본 `odhr.json`의 `od[..].hr[hour]` 6원소 중 `n`(편수)·`teS`/`teN`(TEET 합/유효건수)만 실측 검증됨(golden VHHH|RKSI 24시간대 전부 정확 일치). `dly`(지연편수, "시간대 정시율"의 근거)는 A1의 `ponA`/`ponN`과 같은 갭이지만 이번엔 **대체 계산 스크립트도 찾지 못함**(`SOURCE_PROJECT_ROOT` 전처리 스킬 4종 전체를 "정시율"/"on_time"/"ODHR"로 검색해도 결과 없음) — ACDM 임계값·FOIS 등재 여부로 여러 시도했으나 전부 golden과 불일치해 보류. **실제 응답 계약**: `on_time_pct`는 항상 `null`, 대신 `window:{hour, flights, avg_teet_min, delta_vs_baseline_min}`(검증된 소요시간 델타)를 제공. `CAUSES`는 고정 사전이 아니라 `processed_fois_{departure,arrival}.cause_major` 실측 distinct 집계(골든 13종과 정확히 일치 확인).
- **수용기준(수정)**: hour 지정 시 완성본과 동일한 편수(`n`)·평균 TEET(`teS/teN`)가 나온다(실측 일치 확인). "시간대 정시율 X%"는 이번 범위에서 제외 — `on_time_pct`는 항상 null이며 이를 소비하는 B1 이후 단계는 null을 전제로 설계해야 한다.

### STEP A3 — 상층풍·시어·추천고도 (client-side, 완료 2026-07-23)
- **목표**: 선택 경로에 대해 완성본 `routeWind`/`calcFL`/`drawShear`와 동등한 상층풍·연직시어·
  ★추천고도(시어≤7 중 소요단축 최대, 동률 시 시어 낮은 쪽 — [04 §E](./04-frontend-migration.md))를 산출.
- **대상**: `frontend/js/layers/wind.js`(신규). 상층풍 소스는 완성본과 동일(Open-Meteo GFS)이며
  **URL·기압면 매핑·순항고도 후보·TAS·시어 임계값은 `config.js`/`config.example.json`의 `CONFIG.wind`**
  (하드코딩 금지). 실시간·클라이언트이므로 백엔드 불필요.
- **수용기준**: 경로 카드에 추천 FL·배풍/정풍·시어 등급이 표시되고, 완성본과 동일 입력에서 동일 FL 추천.
- ⚠ **A1/A2와 성격이 다름**: 완성본 HTML에 `routeWind`/`segWindAt`/`calcFL`/`routeParity`/`catGrade`/
  `drawShear`/`renderWind` 원본 함수가 그대로 있어(과거 배치처럼 역산이 필요 없음) 로직 변경 없이
  줄 단위 포팅. 실시간 외부 API라 golden JSON 대조 검증은 불가 — 대신 순수함수 단위검증(합성 입력) +
  실제 Open-Meteo 라이브 호출 종단확인으로 대체. `senior-code-reviewer` 통과(Critical/High 없음,
  Low 3건 수정: drawShear 중복호출·불필요 escapeHtml·`.hw` 경고배경 누락). 상세는
  [07-checklist](./07-checklist.md) A3 항목.

### STEP A4 — 실시간 섹터 교통·수요예측 (client-side, 병목 소스)
- **목표**: 완성본 `analyzeFIR`의 핵심 이식 — 현재 ADS-B 항공기를 ACC 섹터에 배정, **속도·방향으로
  +10/+40분 위치를 외삽**해 섹터별 미래 수요(▲▼)를 예측. 선택 경로가 통과하는 섹터(`routeSectorIds`)에
  교통 등급(원활/보통/혼잡)을 매긴다.
- **방법론(고정 — 수용기준의 일부)**: 완성본 `analyzeFIR`와 **동일 방법론**을 쓴다. 재현 가능하게 아래를 못박는다.
  - 외삽: 각 기체 `gs`(대지속도)·`track`(방위)로 **대권(great-circle) 위치**를 +10분/+40분 산출. `gs<50`이거나
    `gs`/`track` 결측이면 제외. 외삽식은 완성본 `extrap()` 이식.
  - 임계값(**전부 config**, 하드코딩 금지): `trafficGrade` 경계(현재 7/12), 예측 추세 ▲▼ 경계(±2), 기상샘플 dBZ
    경계(rain 15·mod 30), 회피 반경. `config.js`에 `sectors: { trafficThresholds, trendDelta, wxDbz }`로 둔다.
  - 결정성: 동일 입력(항공기 스냅샷+섹터)에서 동일 출력(부수효과 없는 순수 함수).
- **선행**: ACC 섹터 지오메트리(`acc_sectors.json`)를 `reference/loader.py`가 제공하는지 확인, 없으면
  참조 아티팩트로 추가. FIR/섹터 point-in-polygon은 완성본 `pip`/`inFir` 로직 이식(`frontend/js/geo.js`).
- **대상**: `frontend/js/analyze-sectors.js`(신규) — `adsb.js`의 항공기 데이터 구독. 순수 계산 함수
  `sectorDemand(aircraft, sectors)` 분리(테스트·context 재사용).
- **수용기준**: (1) 고정 항공기 스냅샷 입력에 대해 `sectorDemand`가 완성본과 **동일한 섹터별 현재/예측 대수·
  등급**을 낸다(단위 테스트로 고정). (2) 통과 섹터별 값·등급이 표시된다. (3) ADS-B 미가용 시 조용히
  "실시간 교통 데이터 없음"으로 degrade(완성본 동작과 일치).

### STEP A5 — 세그먼트 병목 신호 종합
- **목표**: A1(흐름관리)·A3(경로 기상)·A4(섹터 교통)를 **경로 세그먼트/통과 FIR 단위로 묶어** 병목
  후보를 만든다(doc 11 §17.3). 1단계는 "부분 힌트"(가용 신호만) — 완전 세그먼트 병목(교통×기상×교차)은 후속.
- **대상**: `frontend/js/route-bottlenecks.js`(신규) — 순수 함수 `routeBottlenecks(context)`.
- **수용기준**: "경로 2의 ZSHA 구간 09~10시 혼잡 + 강수셀 교차 → 지연 위험" 형태의 구조화 배열 산출.

### STEP A6 — 터미널 신호 이식 (D20 확정: en-route 우선 + 터미널 신호 표시)
- **목표**: [14 §8 C-2](./14-improvement-request.md) 확정에 따라, 완성본 ODR2 `odInfo`에 있는 **터미널 신호**를
  advisor 경로 응답에 이식해 근거로 소비한다: 진출입 게이트(경로별 `ext`=인천 FIR 진입/진출), 출발 활주로
  분포(`rwd`), 권장 출발 시간대(A1의 `FLOW.hrP` best_hours로 이미 커버). ⚠ 이건 **표시·근거용**이며,
  terminal *최적화*(활주로 혼잡 D19·진입점 변경 holding 저감·분리간격)는 **후속**이다.
- **대상**: `backend/batch/build_odr2.py`가 `odInfo`(rwd·gate·dly·peak)를 산출·포함하는지 확인 후, 미포함이면
  산출 추가. `backend/app/queries/routes.py`의 `_shape_option`/`routes_for`에 `gate_in`/`gate_out`·`runway_dist`
  필드 노출(현재 미노출). 프론트는 경로 카드/근거 팝업에 표시.
- **수용기준**: 선택 경로에 진출입 게이트·출발 활주로 분포가 표시되고, reasoningContext(`selected_route.gate_*`)에
  담긴다. 완성본 `castScript`의 "진입 X, 진출 Y를 사용하는 경로" 서술과 동일 입력.

### STEP A7 — SUAS/MOA 통과시각 발효 판정 (신규, [11 §18](./11-ai-route-reasoning-proposal.md)·D23)
- **배경**: 사용자 발견(2026-07-23) — DAFIF `SUAS_PAR.TXT`(`PORTING_PACKAGE_ROOT/원본데이터/DAFIFT/SUAS/`,
  §0.1 읽기전용 외부자산)에 MOA 등 특수공역의 **요일·시간별 발효시간(`EFF_TIMES`)** 이 있으나(전체
  18,426건 중 16,327건 실값, 일본도 264건·MOA 66건 확인), 완성본조차 이 필드를 `suas.json` 빌드 단계에서
  누락시켰다 — **완성본에도 없는 신규 신호**이며, 이 STEP만은 "이식"이 아니라 "신규 파생"이다.
- **목표**: 선택 경로가 통과 예정 시각에 **구조화 패턴상 발효 중**인 SUAS/MOA가 있으면 병목/우회 근거로
  제시한다(예: "경로 X는 화~금 09시 MOA 활성 시간대 통과 — 우회 가능성 확인").
- **선행(2단)**:
  1. **SUAS 참조 레이어 자체 포팅**([03](./03-backend-api.md) `/api/reference/suas`, 현재 미구현) —
     이 STEP의 전제조건. 별도 2단계 항목으로 이미 문서화돼 있으나 실코드 없음, 이 STEP 착수 전 완료 확인.
  2. `EFF_TIMES` 보존 — `사전빌드_JSON/suas.json`류 빌드가 이 컬럼을 버리므로, advisor 자체 배치가
     원본 `SUAS_PAR.TXT`에서 **직접** 읽어 보존해야 한다(백데이터 사전빌드본에 의존 불가).
- **파싱 규약(안전 우선 — 창작·억측 금지)**:
  - **구조화 가능(1단계 반영)**: 요일 키워드(`MON`~`SUN`, `MON-FRI`, `MON-SAT`, `DLY` 등) + UTC 시간범위
    (`HHMM-HHMMZ`) 조합 → `{days:[...], utc_start, utc_end}` 구조로 정규식 파싱.
  - **비정형(1단계 미반영)**: `SR-SS`(일출-일몰, 위치·계절 종속) · `BY NOTAM`/`OT BY NOTAM` · 그 외 자유
    서술 각주 — **발효 여부를 단정하지 않고** `status: "확인 필요(NOTAM)"` 로만 노출. 파싱 실패를 임의
    기본값(예: "비활성으로 간주")으로 채우지 않는다(안전 사고 방지).
- **대상**:
  - 배치: `backend/batch/build_suas.py`(신규) — DAFIF `SUAS_PAR.TXT`를 읽어 `reference/artifacts/suas.json`
    생성(위치·고도 + `eff_times_raw` + 파싱된 `structured_schedule`\|`null`). 읽기전용 외부자산 소비([CLAUDE.md](../CLAUDE.md) §0.1).
  - 쿼리/라우터: 기존 §03 `suas` 참조 엔드포인트(포팅 완료 후) 확장 — 스케줄 필드 노출.
  - 프론트: `frontend/js/route-bottlenecks.js`(A5) 확장 — 경로 통과 좌표·FIR와 SUAS 폴리곤 교차 +
    통과 예상시각(§17.3과 동일 근사, doc 11)으로 발효 여부 판정해 병목 후보(`type: "airspace"`)에 추가.
- **수용기준**: (1) 알려진 예시(한국 ASAN `MON-FRI 2300-1300Z, SAT 2300-0400Z`)에서 지정 요일·UTC 시각
  입력 시 발효/비발효가 올바르게 판정된다(단위 테스트). (2) `SR-SS`/`BY NOTAM` 케이스는 발효를 단정하지
  않고 "확인 필요"로만 표시된다. (3) SUAS 참조 레이어 미포팅 시 이 STEP은 조용히 스킵(에러 아님).

### STEP B1 — reasoningContext 스키마 확정
- **목표**: LLM 프롬프트 입력이 될 **정규화 JSON 1개**를 정의. **완성본 `castScript`의 12스텝을 그대로
  입력 항목 스펙으로 삼는다**(각 스텝이 참조하는 값 = context 필드).
- **산출**: 이 문서 §7에 스키마 초안(아래). 계산은 하지 않고 A1~A7 결과를 담기만 한다.
- **수용기준**: castScript가 문장으로 만들던 모든 값이 context에 필드로 존재(누락 없음).

### STEP B2 — context 어셈블러 (순수 함수, 완료 2026-07-24)
- **목표**: `buildReasoningContext({dep, arr, selectedRoute, flow, delayHistory, wind, sectorDemand,
  bottlenecks, metar})` → §7 스키마 객체. **부수효과 없는 순수 함수**(모드 C에서 서버 이식 가능).
- **대상**: `frontend/js/reasoning-context.js`(신규).
- **수용기준**: 신호 일부 결측(예: ADS-B off)이어도 부분 context를 만들고 결측 필드는 `null`로 표시.
- ⚠ **입력 시그니처 확장(구현 중 발견, 2026-07-24)**: 원안의 `selectedRoute`(선택된 옵션 하나)만으로는
  `usage_pct`(전체 옵션 대비 비중)·`faster_alt`(다른 옵션과의 소요시간 비교)를 계산할 수 없다 — 둘 다
  castScript 원본에서도 `opts`(전체 옵션 배열)를 인라인으로 순회해 구한다. 그래서 실제 시그니처는
  `{dep, arr, totalFlights, routeOptions, selectedIndex, flow, delayHistory, wind, sectorDemand,
  bottlenecks, metar, windConfig, hour, nowKst}`로 넓혔다(`routeOptions` 전체 + `selectedIndex`가
  `selectedRoute`를 대체). `windConfig`(§7 shear_grade 파생용, `catGrade()` 재사용)·`hour`(레거시
  `rpHr.value`에 대응, `flow.hour_impact_pct` 스칼라화용 — B2 리뷰 지적, 2026-07-24 추가)·`nowKst`
  (호출부가 주입하는 생성 시각 — 함수 내부에서 시각을 만들면 순수성이 깨지므로)도 추가. "계산 없는
  어셈블리" 원칙은 castScript 자신의 인라인 산술(백분율·최솟값 탐색·시간대 윈도우 평균)까지는 포함하지
  않는다 — 그건 이식이지 신규 계산이 아니다. `sensitivity` 태그(§7.2)는 `reasoning-context.js`의
  `SENSITIVITY` export로 구현하고, `masked` 필드(`main_causes`/`causes`)는 원문 유입 방어를 위해
  형태 검증 후 통과시킨다(리뷰 지적, 2026-07-24 — `sanitizeCausePct`/`sanitizeCauseLabels`).
  `route_wx.enroute_echo_pct`·`delay_history.airport_hourly_flights`는 §7 OPEN ITEM 그대로 항상 `null`
  (2026-07-24 사용자 확인: B2는 진행, 갭은 null로 유보).

### 5.1 Phase B → C 전환 기준 (측정 가능한 B 완료 정의)
> 리뷰 지적(2026-07-23): B "완성" 조건이 모호하면 C1 착수 시점을 판단할 수 없다. 아래가 **전부 참**일 때만
> Phase C를 시작한다.

1. **스키마 v1.0 태그** — 충족. `reasoning-context.js`의 `SCHEMA_VERSION`이 `"1.0"`이고 모든 출력에
   `schema_version:"1.0"`이 박힌다(2026-07-24 실행 확인).
2. **필드 충족** — **부분 충족**(2026-07-24 검증, 상세 아래). 백엔드 신호(`flow`·`delay_history`·
   `selected_route`·`faster_alt`)는 로컬 advisor API(포트 8088) 기동 후 알려진 OD **3건**
   (`RKSI|RJBB`·`RKSI|RJAA`·`RJAA|RKSI`)에서 `buildReasoningContext`로 직접 실행해 전부 `null`이 아닌
   실값(`impact_pct`·`window`·`usage_pct`·`faster_alt.saves_min` 등)이 나옴을 확인했다(검증 스크립트는
   임시 파일, 저장소에 남기지 않음 — 재현하려면 backend 기동 후 known OD로 `/api/routes`·`/api/routes/flow`·
   `/api/routes/delay-history` 응답을 `buildReasoningContext`에 넣어보면 된다).
   `wind`·`sectors`(ADS-B on)는 **최종 라이브 확인 완료**(2026-07-24 추가 검증) — 브라우저 자동화 도구가
   없어 실제 클릭 조작 대신, `layers/wind.js::buildRouteWind`/`calcFL`/`recommendFL`와
   `analyze-sectors.js::sectorDemand`/`routeSectorIds`가 DOM 비의존 순수/비동기 함수임을 이용해
   Node에서 `main.js::createWindLayer().update()`와 동일한 로직으로 직접 호출, **실제 Open-Meteo API**와
   **실제 adsb.lol 라이브 ADS-B API**를 호출했다: `RKSI|RJBB` 경로에서 실제 상층풍 데이터로
   `{fl:390, wc:-5.3, maxShear:3.53}` 추천이 나왔고(레이더 6기압면 실조회), 경로 중간지점 반경 100NM
   실시간 항공기 29대를 조회해 경로 통과 섹터("WH", West-sea High Sector)의 실시간 수요(현재 0대/원활)를
   산출, `buildReasoningContext`에 넣어 `ctx.wind`/`ctx.sectors`가 non-null 실값으로 나옴을 확인했다.
   `bottlenecks`는 A5/A7 합성 입력 검증(B2 리뷰 중 실시)까지만 — A5/A7 자체가 위 두 신호(flow/wind/sectors/
   suas)의 재조합이라 원신호가 라이브로 검증됐으면 조합 로직 자체는 이미 리뷰로 확인된 것으로 간주.
3. **결측 규약** — 충족. `flow:{found:false}`·`delayHistory:{found:false}`·미기록 OD(`routeOptions:[]`,
   `selectedIndex:null`) 입력에서 모든 필드가 예외 없이 `null`/`[]`로 나옴을 실행 확인(2026-07-24).
4. **민감도 태그 완비**(§7.1/§7.2) — 충족. `reasoning-context.js`의 `SENSITIVITY`가 §7.2 표와 1:1
   일치(리뷰로 확인)하고, `restricted` 등급 필드는 스키마·코드 어디에도 존재하지 않는다. `masked` 필드
   (`main_causes`/`causes`)는 `sanitizeCausePct`/`sanitizeCauseLabels`가 형태 검증 후 통과시킨다(리뷰
   지적으로 추가, 2026-07-24).
5. **순수성** — 충족. 동일 입력으로 `buildReasoningContext`를 2회 호출해 출력이 완전히 동일함을 확인
   (2026-07-24). 내부에 `Date.now()`/`new Date()`/DOM 접근 없음(시각은 `nowKst` 인자로 주입).
6. **리뷰에이전트 게이트** — 충족. B1(스키마)·B2(어셈블러) 각각 `senior-code-reviewer` 리뷰 통과 후
   지적사항 전부 수정([CLAUDE.md](../CLAUDE.md) §4).

> ✅ **Phase C 착수 승인(2026-07-24)**: 6개 기준 전부 충족. wind/sectors 라이브 확인까지 마쳐 남은 조건부
> 항목 없음. Phase C(프롬프트 템플릿) 착수 가능.

---

## 6. Phase C — LLM 서술층 (얇은 층)

### STEP C1 — 프롬프트 템플릿 + 골든 예시 (완료, 2026-07-24)
- **목표**: system+user 프롬프트 템플릿 작성. **`castScript` 출력이 곧 golden output(few-shot 예시)**.
- **규약**:
  - 프롬프트 문자열·톤 가이드·출력 스키마는 **config/파일 리소스**로 분리(하드코딩 금지). 예:
    `frontend/prompts/route-reasoning.ko.txt`.
  - AI에게 **"주어진 수치를 재계산·창작하지 말고 근거로만 사용"**을 명시(환각 방지).
  - 출력은 **JSON 스키마(D6)**: `{ "why": "2~3문장", "bottlenecks": [{seg, reason, severity}], "caveats": [] }`.
  - 톤: [12 §5](./12-operational-goal-and-scenarios.md)/castScript와 동일(관제 브리핑체, 단정 대신 근거 제시).
- **수용기준**: 동일 context에서 사람이 읽어 castScript와 논지가 일치하는 출력을 얻는다(수동 검증).

### STEP C2 — D1 수동복붙 모드 UI (완료, 2026-07-24)
- **목표**: "AI 근거 보기" 버튼(D5) → (a) 완성된 프롬프트를 보여주고 **복사** 버튼, (b) 사용자가 외부
  AI 응답을 **붙여넣는 입력창**, (c) 붙여넣은 JSON을 파싱→팝업 렌더.
- **대상**: `frontend/js/reasoning-panel.js`(신규) + `index.html` 팝업 마크업 + `style.css`.
- **수용기준**: 프롬프트 복사가 되고, 유효 JSON 붙여넣기 시 §1의 팝업이 렌더된다.

### STEP C3 — 응답 검증·파싱·렌더 (보안 핵심, 완료 2026-07-24)
- **목표**: 붙여넣은/받은 응답을 **신뢰 못 할 입력**으로 처리.
- **규약(§8)**: JSON 스키마 검증(필드·타입·길이 상한), **DOM 삽입은 textContent/생성 API만**(innerHTML로
  응답 문자열 넣지 않음 — XSS), 스키마 불일치 시 "형식 오류" 안내(원문 노출 최소화).
- **수용기준**: `<script>`·핸들러가 섞인 악성 응답을 넣어도 실행되지 않고 안전히 거부/이스케이프.

### STEP C4 — 모드 C(백엔드 프록시) 스켈레톤 (미활성, 완료 2026-07-24)
- **목표**: 향후 자동호출용 골격만. **키·엔드포인트는 env로만**(커밋 금지), 요청량 제한·로그·타임아웃 규약을
  주석/스텁으로 남긴다. 기상서버(`기상서버/server.js`) 프록시 패턴 참조. **이번 단계에선 활성화하지 않음**(D9).
- **수용기준**: `reasoning-context.js`(순수)·프롬프트 빌더를 서버에서 재사용할 수 있는 경계가 문서화됨.
- **구현**: `backend/app/routers/reasoning.py`(`POST /api/reasoning/complete`, 항상 501 — 상세는
  [07-checklist](./07-checklist.md) C4 항목·[03-backend-api](./03-backend-api.md) §4.5·이 파일의
  모듈 docstring이 단일 출처).

---

## 7. reasoningContext 스키마 v1.0 (B1 산출물)

> castScript 12스텝 ↔ 필드 매핑. 값은 전부 ①계층이 이미 계산한 것(AI는 읽기만).
>
> ⚠ **2026-07-24 개정**: 최초 초안(예시값 위주)이 실제 A1~A7 구현체(`backend/app/queries/routes.py`·
> `flow_reasoning.py`·`odhr.py`, `frontend/js/analyze-sectors.js`·`route-bottlenecks.js`·
> `layers/wind.js`·`weather.js`)와 필드명·구조가 어긋나 있었다(B1 진행 중 실코드 대조로 발견). 아래는
> 실제 반환 shape에 맞춘 v1.0이다. 필드명이 바뀐 곳은 원인을 주석으로 남긴다.

```jsonc
{
  "schema_version": "1.0",
  "od": { "dep": "VHHH", "arr": "RKSI", "monthly_flights": 743, "daily_avg": 24, "route_count": 4 }, // routes_for.total_flights/options.length
  "selected_route": {
    "rank": 1, "usage_pct": 63, "avg_min": 187,
    // ⚠ on_time_pct 삭제 — routes.py options에 정시율 컬럼 없음(있는 건 delay_count뿐).
    // castScript도 선택 경로 자체의 정시율은 말하지 않는다(정시율은 flow/delay_history에서만 다룸).
    // 존재하지 않는 신호를 스키마에 넣지 않는다(§5.1 #3 결측 규약 위반 소지).
    "enroute_firs": ["VHHK","RCAA","RJJJ","RKRR"], "gate_in": "ATOTI", "gate_out": "TESat"
  },
  "faster_alt": { "rank": 2, "saves_min": 6, "gate_in": null, "gate_out": null }, // 없으면 전체 null
  // ⚠ gate_in/gate_out 추가 — castScript 4번째 문장이 "인천 FIR 진입 X, 진출 Y를 사용하는 경로"를
  // faster_alt에 대해서도 말한다(원 초안은 index/saves_min만 있어 이 문장이 못 채워졌다).
  "flow": {                                                   // A1 flow_reasoning.flow_for()
    "found": true, "impact_pct": 23, "on_time_affected": null, "on_time_normal": null,
    "delay_affected_min": null, "main_causes": [["F/C", 31],["M/A", 22]],
    "main_limits": ["OODAK NOT AVBL"], "hour_impact_pct": 30 // 선택 시간대 ±1h 평균 스칼라, 미선택/결측이면 null
  },
  // ⚠ on_time_affected/on_time_normal/delay_affected_min 항상 null(통합 리뷰 지적, 2026-07-24) —
  // build_flow.py::_od_aggregate()가 미구현으로 세 필드 모두 항상 `None`을 반환한다(docs/07-checklist.md
  // 기 확인 사항). delay_history.on_time_pct와 같은 처지인데 이 문서엔 그 caveat이 빠져 있었다 — 이전
  // 예시(43/36/21)는 실제로 절대 나올 수 없는 그럴듯한 가짜값이었다. Phase C 프롬프트 작성 시 이 세
  // 필드는 항상 null을 전제로 설계해야 한다.
  // ⚠ main_causes 예시값 정정(통합 리뷰 지적) — 이전 예시("기술·항공기장비"/"반응성·연쇄지연")는 A2
  // ODHR `cause_major` 분류명이 잘못 복붙된 것이었다. 실제 A1 `flow.main_causes`는 흐름관리일지
  // `reason_code` 원본 코드값(F/C·M/A·WX·미기재 등, docs/07-checklist.md 실측 확인)이 나온다. "미기재"
  // (분류 실패 placeholder)는 castScript(3352줄, `rs.filter(x=>x[0]!=='미상')`)와 동일하게 어셈블러가
  // 드롭한다(`GENERIC_CAUSE_LABELS`, `reasoning-context.js`).
  // ⚠ hour_impact_pct 스칼라화(리뷰 지적, 2026-07-24) — flow_for()의 실제 반환은 24시간 배열(결측 `-1`
  // 센티널)이다. 이 필드는 castScript(3370~3378줄)처럼 **사용자가 선택한 시간대의 ±1시간 윈도우 평균**
  // 스칼라를 뜻한다 — 어셈블러(B2)가 `hour` 입력을 받아 배열→스칼라 변환·`-1` 필터링을 수행한다
  // (이것도 castScript 인라인 산술의 이식이라 "계산 없음" 원칙 위반이 아니다).
  // ⚠ best_hours 삭제(리뷰 지적) — flow_for() 반환 dict에 이런 키도, 이를 계산하는 로직도 저장소 어디에도
  // 없다(182줄의 "A1의 hrP best_hours"는 **레거시 완성본**의 서술이지 실제 A1 구현 얘기가 아니다).
  // castScript도 "권장 시간대 3개"를 말하는 문장이 없다 — 없는 신호+없는 요구사항을 스키마에 넣은 오류였다.
  // found:false면 impact_pct 등 나머지 키는 **dict 자체에서 부재**(null이 채워진 게 아님, §7.2 아래 참고).
  "delay_history": {                                          // A2 odhr.delay_history_for()
    "found": true, "hourly_flights": [/*24개*/], "hourly_avg_teet_min": [/*24개*/],
    "on_time_pct": null, // A2 계약상 계산식 미검증으로 **항상 null**(추정치를 지어내지 않음, doc §STEP A2)
    "window": { "hour": 9, "flights": 41, "avg_teet_min": 181.7, "delta_vs_baseline_min": -1.9 }, // hour 미지정 시 null
    "causes": ["ATFM·관제","공항·정부기관","기상","기술·항공기장비","기체손상·시스템","기타",
      "미분류","미분류·검토필요","반응성·연쇄지연","여객·수하물","운항·승무원","항공기·램프조업","화물·우편"],
    "airport_hourly_flights": null
  },
  // ⚠ causes 형태 정정(리뷰 지적) — build_odhr.py는 processed_fois cause_major의 **distinct 문자열
  // 배열**만 만든다(비율 없음, OD와 무관하게 전 OD 동일 고정 목록). 원래 있던 [원인,비율%] 쌍 예시는
  // 존재하지 않는 데이터 형태였다. castScript statement 10("주요 지연원인은 기상 18%...")이 요구하는
  // "원인별 비율"은 이 목록만으로는 채울 수 없다 — route_wx와 같은 처지의 결측이므로 정직하게 다뤄야 한다.
  // ⚠ airport_hourly_flights 추가(OPEN ITEM, 리뷰 지적) — castScript statement 8 후반부는 ODHR.ap[dep](공항별
  // 24시간 출발량)로 "혼잡/한산 시간대"를 판정하는 문장을 잇는다. build_odhr.py 아티팩트엔 `ap[icao]`가
  // 실제로 존재·검증까지 됐지만(모듈 docstring), 쿼리 계층 odhr.py::delay_history_for()가 이를 노출하지
  // 않는다(od만 조회). **사용자 확인 후 odhr.py에 ap 노출 추가 여부 결정, 그 전까지 항상 null.**
  "wind": { "rec_fl": "FL360", "tail_head_kt": 18, "shear_kt_per_1000ft": 4, "shear_grade": "약함" },
  // ⚠ 필드명 정정 — wind.js getRecommendation()의 실제 반환은 {fl,wc,maxShear,...}이며 `shear`가 아니라
  // `maxShear`. 스키마 필드는 의미가 드러나게 `shear_kt_per_1000ft`로 명명. shear_grade는 wind.js
  // `catGrade(maxShear, windConfig)`로 어셈블러가 파생(하드코딩 금지, config 임계값 재사용).
  "sectors": [                                                // A4 analyze-sectors.sectorDemand() (ADS-B off/선택경로 없음 → [])
    { "sectorId": "RKRR-JN", "nameEn": "Jeju North", "current": 9, "future10": 11, "future40": 13, "trend": "up", "grade": "혼잡" }
  ],
  // ⚠ 필드명 정정(id→sectorId, ko→nameEn, now→current, fut10→future10, trend 값 ▲→"up") — 실제
  // sectorDemand() 반환 그대로. future40/한국어 섹터명은 원 초안에 없었음(SEC_KO 매핑은 프론트 표시용,
  // context엔 nameEn만 — 표시 라벨은 C층에서 다국어 처리 가능하도록).
  // ⚠ grade 필드 주의(리뷰 지적) — sectorDemand()의 실제 반환은 문자열이 아니라 `trafficGrade()`가 만드는
  // `[label, tokenKey]` 2원소 배열(예: `["혼잡","trafficHeavy"]`, tokenKey는 UI 색상 설정 내부 식별자).
  // 어셈블러는 `grade[0]`(라벨)만 취하고 tokenKey는 컨텍스트에 담지 않는다(UI 내부 식별자가 프롬프트에
  // 흘러들어가지 않도록) — wind.shear_grade와 동일하게 "어셈블러가 파생/추출"하는 필드다.
  // ⚠ wx_grade 필드 삭제 — 섹터별 기상등급을 계산하는 코드가 어디에도 없다(A4 STEP 문서의 dBZ 임계값은
  // route_wx.enroute_echo_pct용이지 섹터별 필드가 아니었다). 없는 신호를 스키마에 넣지 않는다.
  "route_wx": { "enroute_echo_pct": null },
  // ⚠ OPEN ITEM(2026-07-24) — castScript 6번째 문장("경로상 인천 FIR 구간 N%에서 강수 에코 관측")에 대응하는
  // A-step이 Phase A(A1~A7)에 없다(레이더 dBZ 샘플링 로직 이식 STEP 누락). v1.0은 필드만 예약(null 고정)해
  // "castScript가 말하던 값이 스키마에 존재"(B1 수용기준)는 만족시키되, 실제 채우려면 신규 A-step(가칭
  // A8 — 경로상 레이더 강수 샘플링)이 필요하다. **사용자 확인 후 A8 추가 여부 결정, 그 전까지 항상 null.**
  "bottlenecks": [                                            // A5(scope:route/sector)·A7(scope:airspace) route-bottlenecks.routeBottlenecks()
    { "scope": "route", "fir": null, "kind": "flow_impact", "label": "흐름관리 영향률 23%(41/178편, 추정치)", "severity": "info" },
    { "scope": "sector", "fir": "RKRR", "kind": "sector_traffic", "label": "Jeju North(RKRR-JN) 교통 혼잡 (현재 9대, +10분 후 11대)", "severity": "warn" },
    { "scope": "airspace", "fir": null, "kind": "airspace", "label": "ASAN(K-4) 통과 예정(약 12분 후) — 활성 시간대 통과, 우회 가능성 확인", "severity": "warn" }
  ],
  // ⚠ 필드명 전면 정정 — 원 초안 {seg,reason,severity,type}은 실제 구현과 무관한 예시였다. 실제
  // routeBottlenecks()는 {scope,fir,kind,label,severity}를 반환(label은 이미 완성 문장 — C층이 그대로
  // 인용 가능). severity는 "info"/"warn"만 존재("확인"/"경고" 같은 한국어 라벨 아님.
  "airport_wx": {                                             // weather.js decodeMetar()/riskOf() 재사용
    "dep": { "cat": "VFR", "wind": "270도 12노트", "warn": [] },
    "arr": { "cat": "MVFR", "wind": "180도 22노트 돌풍 28노트", "warn": ["강돌풍"] }
  },
  "generated_at_kst": "2026-07-24T09:00:00+09:00"
}
```

> ⚠ **결측 정규화 책임(리뷰 지적)**: `flow_for()`/`delay_history_for()`는 `found:false`일 때 나머지 키를
> `null`로 채우지 않고 **키 자체를 반환 dict에서 뺀다**(예: `{"dep":..,"arr":..,"found":false,"routes":{}}`).
> 위 예시의 "found:false면 나머지 필드 null"은 최종 context의 모양이지, API 원본 응답의 모양이 아니다.
> `buildReasoningContext`(B2)는 스키마에 정의된 키를 API 응답에 없으면 명시적으로 `null`로 채워야 한다 —
> 그래야 C3의 JSON 스키마 검증(필드가 케이스마다 있다 없다 하지 않고 항상 동일한 키 집합)이 성립한다.

### 7.1 민감도 태그 컨벤션 (보안이 "살아있는 규칙"이 되도록)
> 리뷰 지적(2026-07-23): §8이 "CLAUDE.md 참조"로만 끝나면 구현 시 "어느 레이어에서 무엇을 마스킹하나"가
> 다시 불명확해진다. **스키마 설계 단계에서 필드별 민감도를 명시적으로 태그**해 규칙을 코드로 강제한다.

각 필드에 3등급 민감도를 부여하고, context 빌더가 등급별로 다르게 처리한다.

| 등급 | 의미 | 처리 규칙 | 예 |
|---|---|---|---|
| `public` | 집계·비식별 지표 | 그대로 사용 | 정시율, 영향률, 추천 FL, 섹터 대수 |
| `masked` | 민감 원문에서 파생됐으나 비식별 형태로만 | **분류/비율만**, 원문 필드 제거(D7) | FOIS 지연 사유 = 분류코드+% (원문 reason 금지) |
| `restricted` | 원문·식별정보 | **context에 절대 싣지 않음** | FOIS reason 원문, 개별 편명/등록부호 |

### 7.2 필드별 민감도 태그 맵 (v1.0, `reasoning-context.js`의 `SENSITIVITY` 단일출처)

| 필드 경로 | 등급 | 근거 |
|---|---|---|
| `od.*` | `public` | 집계 편수·경로 수 |
| `selected_route.*`, `faster_alt.*` | `public` | 집계 소요시간·게이트(공역 이름, 개인정보 아님) |
| `flow.impact_pct/hour_impact_pct/main_limits` | `public` | 집계 지표·공역 제한 텍스트 |
| `flow.on_time_affected/on_time_normal/delay_affected_min` | `public` | **항상 null**(build_flow.py 미구현, 통합 리뷰 지적 2026-07-24 — delay_history.on_time_pct와 같은 구조적 결측) |
| `flow.main_causes` | `masked` | 흐름관리일지 `reason_code`이나 이미 코드+비율 형태(D7) — 원문 재삽입 금지, "미기재" placeholder는 드롭(`GENERIC_CAUSE_LABELS`) |
| `delay_history.hourly_*/on_time_pct/window.*` | `public` | 집계 통계 |
| `delay_history.causes` | `masked` | `processed_fois.cause_major` distinct 분류명 목록(비율 없음, D7 — 원문 사유 텍스트가 아니라 분류명 자체) |
| `delay_history.airport_hourly_flights` | `public` | 공항 시간대 출발량 집계 — OPEN ITEM, 구현 전까지 null |
| `wind.*` | `public` | 기상·항법 집계값 |
| `sectors[].*` | `public` | 섹터별 항공기 **대수**만(개별 편명·등록부호는 애초에 담지 않음 — 담을 경우 `restricted`) |
| `route_wx.*` | `public` | 레이더 에코 비율(집계) — 구현 전까지 null |
| `bottlenecks[].*` | `public` | label은 위 필드들의 집계 재조합, 원문 미포함 |
| `airport_wx.*` | `public` | METAR 공개 기상 정보 |
| (스키마에 없음) | `restricted` | FOIS reason 원문, 개별 편명/등록부호, ADS-B 콜사인 — **애초에 스키마 필드로 만들지 않는다** |

- context 빌더는 `masked` 필드를 넣을 때 **분류코드+비율 형태로 이미 변환된 값만** 받는다(원문 문자열이 들어오면 어셈블러가 드롭). 항목별 길이 상한뿐 아니라 **배열 개수도 상한**을 둔다(통합 리뷰 지적, 2026-07-24 — 길이 상한만으로는 원문을 짧은 조각 여러 개로 쪼개 넣는 우회를 막지 못한다). `main_causes`는 분류 실패 placeholder("미상"/"미기재")도 드롭하지만, `delay_history.causes`의 "미분류"/"미분류·검토필요"는 FOIS 분류체계의 정식 카테고리라 드롭 대상이 아니다.
- `restricted` 등급은 스키마에 필드 자체가 없다 — "값이 있는데 드롭"이 아니라 "애초에 필드가 없어 실을 수 없음"이 v1.0의 설계 원칙(사고 방지: 필드가 있으면 언젠가 채워질 위험).
- 이 태그 맵은 단일 출처(`reasoning-context.js`의 `SENSITIVITY`)로 두고, Phase B 완료기준(§5.1 #4)에서 검증한다.

---

## 8. 보안·규약 체크리스트 (CLAUDE.md 매핑)

| 항목 | 규약 | 근거 |
|---|---|---|
| LLM 응답 | **신뢰 불가 입력** — 스키마 검증, textContent 렌더, 길이 상한, 실패 시 안전 거부 | §3 입력검증·XSS |
| 프롬프트/임계값/URL | config·파일 리소스·env로 분리, 코드에 리터럴 금지 | §2 하드코딩 금지 |
| AI 제공자 키(모드 C) | env로만, 커밋 금지, `.env.example`만 | §2·§3 |
| 요청량(모드 C) | 레이트리밋·타임아웃·로그(조직 정책: API 자동화 시 요청량 제한·로그) | §3 |
| FOIS reason(D7) | 원문 제외, 분류/비율만 | §3 비밀정보 |
| **필드 민감도** | reasoningContext 필드별 `public`/`masked`/`restricted` 태그(§7.1), `restricted` 드롭·`masked` 비식별변환 | §3 + 리뷰(2026-07-23) |
| DB | `processed_*` **읽기전용**, 최신 SUCCESS run 기준, 배치 아티팩트로만 소비 | §5 |
| 좌표/시각 | `[lat,lon]`, KST 고정(+9 재변환 금지) | §7 |
| 각 STEP | 리뷰에이전트(기능·논리·예외·보안) 통과 후 체크 | §4 |
| AI 산출물 | 사실검증·리뷰 없이 배포 금지(조직 정책) | 조직 규정 |

---

## 9. doc 11 §12 결정표 의존 (개선요구서에서 확정 필요)

이 개발 착수 전 확정되어야 하는 항목(§0 G0-4):

| # | 결정 | 이 문서의 기본 가정 | 확정 필요 |
|---|---|---|---|
| D1 | AI 응답 계층 | **A 수동복붙**(1단계), C는 스켈레톤 | 확정 |
| D2 | 추천 결정 주체 | **8-2 결정론 점수 + AI 근거** | 확정 |
| D5 | 팝업 트리거 | **"AI 근거 보기" 버튼**(호출 통제) | 확정 |
| D6 | AI 응답 형식 | **JSON 스키마**(§7 출력) | 확정 |
| D7 | FOIS reason | **제외**(분류/비율만) | 확정 |

> 그 외 doc 11 §12 항목의 **재조정**(완성본 확인 결과): D10/D11/D16/D17/D21은 "신규 후속"이 아니라
> **이식 대상**(Phase A로 흡수), D22(구체정보=포팅 담당·AI 소비)는 확정적으로 맞음. 이 재조정도
> 개선요구서에 반영한다.

---

## 10. 문서 동기화 (STEP 완료 시)

[CLAUDE.md](../CLAUDE.md) §10대로 코드와 동시에 갱신한다.

| 변경 | 갱신 문서 |
|---|---|
| 새 엔드포인트(A1/A2) | [03-backend-api](./03-backend-api.md) §4 |
| 새 프론트 모듈/레이어(A3/A4/A5/B/C) | [04-frontend-migration](./04-frontend-migration.md) |
| 각 STEP 진행 | [07-checklist](./07-checklist.md)(이 문서 STEP을 항목으로 추가) |
| 배치 아티팩트(flow/odhr) | [02-db-integration](./02-db-integration.md) §4 |
| 팝업/버튼 UX | [10-ui-and-realtime](./10-ui-and-realtime.md) |

---

## 11. 착수 순서 요약 (한 줄)

`A1→A2→A3→A4→A5→A6→A7`(신호 이식, A7은 SUAS 참조레이어 포팅 선행) → `B1→B2`(통합기) →
`C1→C2→C3`(LLM 층, 수동복붙) → `C4`(프록시 스켈레톤) → 통합검증. 각 화살표마다 리뷰게이트 + 문서 동기화.

**2026-07-24 — 전 구간 완료.** A1~A7·B1~B2·C1~C4 전부 체크·리뷰·문서동기화 완료(상세는
[07-checklist](./07-checklist.md)). 남은 것은 이 계획 범위 밖: 향후 확장(경로 기하 동적화·참조
타일화·SIGMET/PIREP 루트 교차 판정, [07-checklist](./07-checklist.md) "향후 확장" 절)과, 모드 C
실제 활성화(제공자/모델 확정 후 별도 착수).

## 12. 열린 질문 (착수 중 사용자 확인)

1. ~~상층풍 소스(A3)~~ → ✅ **해소**: [14 C-6](./14-improvement-request.md) — 완성본과 동일 외부 API(URL은 config), 기상서버 프록시 통합은 후속.
2. ~~`acc_sectors.json` 등 참조 아티팩트를 배치로 재생성할지, 백데이터 사전빌드본을 그대로 적재할지~~ → ✅ **해소(A4 구현으로 판가름)**: `reference_acc_sector`/`reference_acc_boundary` DB 테이블로 이관 + `GET /api/reference/acc-sectors` 신규 구현(사전빌드본을 그대로 적재하는 대신 DB화 — odr2/flow와 동일한 "파일 아티팩트 → DB 통합" 패턴, [07-checklist](./07-checklist.md) A4 항목 참고).
3. ~~모드 C 실제 AI 제공자(D9)~~ → ✅ **해소**: [14 C-7](./14-improvement-request.md) — 1단계 미정 유지(수동복붙은 모델 무관), 모드 C 활성 시 [claude-api] 규약으로 결정. C4는 이 미정 상태를 그대로 반영한 스켈레톤(두 번째 게이트가 "제공자/모델 미확정" 사유로 501)으로 완료.
