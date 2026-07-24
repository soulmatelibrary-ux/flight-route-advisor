# 13. AI 경로추천 근거화 — 추가개발 구현 스펙 (단계별)

- 문서 버전: 1.1
- 작성일: 2026-07-23 / v1.1: 2026-07-23(STEP A7 SUAS/MOA 발효시간 판정 추가, D23)
- 상태: ⚠ **이것은 "확정 방향(A)"에 따른 구현 스펙이다.** 결정 게이트(§0 G0-2·G0-3·G0-4)는
  [14 개선요구서](./14-improvement-request.md) v1.0으로 **충족됨(2026-07-23)**, [07-checklist](./07-checklist.md)
  항목화 완료. **남은 착수 조건은 G0-1(현재 빌드 완료)뿐** — 그 전에는 이 문서를 "읽기만" 한다.
- 성격: **추가개발(Follow-on)** — 지금 만들어진 것(Stage 0/1/2 + 2단계 잔여)이 모두 완료된
  뒤 그 위에 얹는 새 개발 단계다. 기존 것을 갈아엎지 않고 **이식 + 얇은 층 추가**만 한다.
- 관련: [11-ai-route-reasoning-proposal](./11-ai-route-reasoning-proposal.md)(분석·결정표),
  [12-operational-goal-and-scenarios](./12-operational-goal-and-scenarios.md)(왜),
  [03-backend-api](./03-backend-api.md), [04-frontend-migration](./04-frontend-migration.md),
  [07-checklist](./07-checklist.md), [CLAUDE.md](../CLAUDE.md)(개발 원칙·리뷰게이트)

---

## 0. 이 문서의 위치와 선행조건 (착수 게이트)

이 개발은 아래가 **모두 참일 때만** 시작한다. 하나라도 미충족이면 이 문서는 "읽기만" 한다.

| # | 선행조건 | 확인 방법 |
|---|---|---|
| G0-1 | 현재 빌드가 clean·완료 상태 | Stage 1/2 + 2단계 잔여(경로기하 동적화·상층풍시어·참조타일화·ACDM KPI·흐름관리조회·기상레이더/SIGMET·PIREP)가 [07-checklist](./07-checklist.md)에서 전부 체크됨 |
| G0-2 | **방향 A 확정** | 완성본 결정론 로직을 advisor로 **이식 우선**, LLM은 **이미 계산된 값을 자연어로 다듬는 얇은 층**으로만(사용자 확정 2026-07-23) |
| G0-3 | **1단계 병목 소스 = 실시간 ADS-B 외삽** | 완성본 `analyzeFIR` 방식(현재 항공기 속도·방향으로 +10/40분 섹터수요 예측). doc 11 §13 역사 프로파일은 이 문서 범위 밖(후속) |
| G0-4 | doc 11 §12 결정항목 중 **이 작업 의존분 확정** | ✅ §9 결정 의존표 항목(D1/D2/D5/D6/D7)이 [14](./14-improvement-request.md) v1.0으로 확정됨 |

> 확정 흐름(doc 11 §0 준수): 이 스펙 검토 → 개선요구서에서 §9 항목 확정 → 07-checklist 항목화
> → STEP 순차 구현 → 각 STEP 리뷰에이전트 게이트([CLAUDE.md](../CLAUDE.md) §4) → 문서 동기화(§10).

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

### STEP B2 — context 어셈블러 (순수 함수)
- **목표**: `buildReasoningContext({dep, arr, selectedRoute, flow, delayHistory, wind, sectorDemand,
  bottlenecks, metar})` → §7 스키마 객체. **부수효과 없는 순수 함수**(모드 C에서 서버 이식 가능).
- **대상**: `frontend/js/reasoning-context.js`(신규).
- **수용기준**: 신호 일부 결측(예: ADS-B off)이어도 부분 context를 만들고 결측 필드는 `null`로 표시.

### 5.1 Phase B → C 전환 기준 (측정 가능한 B 완료 정의)
> 리뷰 지적(2026-07-23): B "완성" 조건이 모호하면 C1 착수 시점을 판단할 수 없다. 아래가 **전부 참**일 때만
> Phase C를 시작한다.

1. **스키마 v1.0 태그**: §7 스키마가 `schema_version: "1.0"`으로 확정되고, 이후 변경은 버전업으로만.
2. **필드 충족**: A1~A7의 실제 데이터로 context 필드가 채워진다 — 알려진 OD 3건 이상에서 `flow`·`wind`·
   `selected_route`·`sectors`(ADS-B on 시)·`bottlenecks`가 `null`이 아닌 실값으로 나오는 것을 확인.
3. **결측 규약**: 신호 미가용 필드는 예외 없이 `null`(임의 기본값·추정 금지) — C 층이 "데이터 없음"을 알 수 있어야 함.
4. **민감도 태그 완비**(§7.1): 모든 필드에 민감도 등급이 부여되고, `restricted` 필드가 context에 실리지 않음이 검증됨.
5. **순수성**: `buildReasoningContext`가 부수효과 없는 순수 함수임을 테스트로 확인(모드 C 서버 이식 대비).
6. 리뷰에이전트 게이트 통과([CLAUDE.md](../CLAUDE.md) §4).

---

## 6. Phase C — LLM 서술층 (얇은 층)

### STEP C1 — 프롬프트 템플릿 + 골든 예시
- **목표**: system+user 프롬프트 템플릿 작성. **`castScript` 출력이 곧 golden output(few-shot 예시)**.
- **규약**:
  - 프롬프트 문자열·톤 가이드·출력 스키마는 **config/파일 리소스**로 분리(하드코딩 금지). 예:
    `frontend/prompts/route-reasoning.ko.txt`.
  - AI에게 **"주어진 수치를 재계산·창작하지 말고 근거로만 사용"**을 명시(환각 방지).
  - 출력은 **JSON 스키마(D6)**: `{ "why": "2~3문장", "bottlenecks": [{seg, reason, severity}], "caveats": [] }`.
  - 톤: [12 §5](./12-operational-goal-and-scenarios.md)/castScript와 동일(관제 브리핑체, 단정 대신 근거 제시).
- **수용기준**: 동일 context에서 사람이 읽어 castScript와 논지가 일치하는 출력을 얻는다(수동 검증).

### STEP C2 — D1 수동복붙 모드 UI
- **목표**: "AI 근거 보기" 버튼(D5) → (a) 완성된 프롬프트를 보여주고 **복사** 버튼, (b) 사용자가 외부
  AI 응답을 **붙여넣는 입력창**, (c) 붙여넣은 JSON을 파싱→팝업 렌더.
- **대상**: `frontend/js/reasoning-panel.js`(신규) + `index.html` 팝업 마크업 + `style.css`.
- **수용기준**: 프롬프트 복사가 되고, 유효 JSON 붙여넣기 시 §1의 팝업이 렌더된다.

### STEP C3 — 응답 검증·파싱·렌더 (보안 핵심)
- **목표**: 붙여넣은/받은 응답을 **신뢰 못 할 입력**으로 처리.
- **규약(§8)**: JSON 스키마 검증(필드·타입·길이 상한), **DOM 삽입은 textContent/생성 API만**(innerHTML로
  응답 문자열 넣지 않음 — XSS), 스키마 불일치 시 "형식 오류" 안내(원문 노출 최소화).
- **수용기준**: `<script>`·핸들러가 섞인 악성 응답을 넣어도 실행되지 않고 안전히 거부/이스케이프.

### STEP C4 — 모드 C(백엔드 프록시) 스켈레톤 (미활성)
- **목표**: 향후 자동호출용 골격만. **키·엔드포인트는 env로만**(커밋 금지), 요청량 제한·로그·타임아웃 규약을
  주석/스텁으로 남긴다. 기상서버(`기상서버/server.js`) 프록시 패턴 참조. **이번 단계에선 활성화하지 않음**(D9).
- **수용기준**: `reasoning-context.js`(순수)·프롬프트 빌더를 서버에서 재사용할 수 있는 경계가 문서화됨.

---

## 7. reasoningContext 스키마 초안 (B1 산출물)

> castScript 12스텝 ↔ 필드 매핑. 값은 전부 ①계층이 이미 계산한 것(AI는 읽기만).

```jsonc
{
  "od": { "dep": "VHHH", "arr": "RKSI", "monthly_flights": 743, "daily_avg": 24, "route_count": 4 },
  "selected_route": {
    "index": 1, "usage_pct": 63, "avg_min": 187, "on_time_pct": 78,
    "enroute_firs": ["VHHK","RCAA","RJJJ","RKRR"], "gate_in": "ATOTI", "gate_out": "TESat"
  },
  "faster_alt": { "index": 2, "saves_min": 6 },              // 없으면 null
  "flow": {                                                   // A1
    "impact_pct": 23, "on_time_affected": 43, "on_time_normal": 36,
    "delay_affected_min": 21, "main_causes": ["기술·항공기장비 31","반응성·연쇄지연 22"],
    "main_limits": ["OODAK NOT AVBL"], "hour_impact_pct": 30, "best_hours": ["03","04","05"]
  },
  "delay_history": { "hour": 9, "on_time_pct": null, "avg_teet_min": 181.7, "delta_vs_baseline_min": -1.9 }, // A2(2026-07-23 구현) — on_time_pct는 계산식 미검증으로 항상 null, 소요시간 델타만 실측 검증됨. 없으면 전체 null
  "wind": { "rec_fl": "FL360", "tail_head_kt": 18, "shear": 4, "shear_grade": "약함" }, // A3
  "sectors": [                                                // A4 (실시간, ADS-B off면 [])
    { "id":"JN","ko":"제주북","now":9,"fut10":11,"trend":"▲","grade":"혼잡","wx_grade":"주의" }
  ],
  "bottlenecks": [                                            // A5, A7(type:"airspace")
    { "seg":"ZSHA 09~10시", "reason":"역사 상위 혼잡 + 강수셀 교차", "severity":"경고", "type":"traffic_wx" },
    { "seg":"KADIZ 인근 MOA", "reason":"화~금 09시 MOA 활성 시간대 통과", "severity":"확인", "type":"airspace" }
  ],
  "airport_wx": { "dep": { "cat":"VFR","wind":"...","warn":[] }, "arr": {...} }, // 기존 weather.js
  "generated_at_kst": "2026-07-23T09:00:00+09:00"
}
```

### 7.1 민감도 태그 컨벤션 (보안이 "살아있는 규칙"이 되도록)
> 리뷰 지적(2026-07-23): §8이 "CLAUDE.md 참조"로만 끝나면 구현 시 "어느 레이어에서 무엇을 마스킹하나"가
> 다시 불명확해진다. **스키마 설계 단계에서 필드별 민감도를 명시적으로 태그**해 규칙을 코드로 강제한다.

각 필드에 3등급 민감도를 부여하고, context 빌더가 등급별로 다르게 처리한다.

| 등급 | 의미 | 처리 규칙 | 예 |
|---|---|---|---|
| `public` | 집계·비식별 지표 | 그대로 사용 | 정시율, 영향률, 추천 FL, 섹터 대수 |
| `masked` | 민감 원문에서 파생됐으나 비식별 형태로만 | **분류/비율만**, 원문 필드 제거(D7) | FOIS 지연 사유 = 분류코드+% (원문 reason 금지) |
| `restricted` | 원문·식별정보 | **context에 절대 싣지 않음** | FOIS reason 원문, 개별 편명/등록부호 |

- 스키마에 필드별 태그를 병기한다(예: `flow.main_causes` = `masked`, `sectors[].callsign` 같은 식별자는
  아예 스키마에서 배제 = `restricted`). context 빌더는 `restricted` 키를 만나면 **드롭**, `masked`는
  **비식별 변환기를 통과**시킨 값만 담는다.
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

## 12. 열린 질문 (착수 중 사용자 확인)

1. ~~상층풍 소스(A3)~~ → ✅ **해소**: [14 C-6](./14-improvement-request.md) — 완성본과 동일 외부 API(URL은 config), 기상서버 프록시 통합은 후속.
2. `acc_sectors.json` 등 참조 아티팩트를 배치로 재생성할지, 백데이터 사전빌드본을 그대로 적재할지. **(유효 — 착수 중 결정)**
3. ~~모드 C 실제 AI 제공자(D9)~~ → ✅ **해소**: [14 C-7](./14-improvement-request.md) — 1단계 미정 유지(수동복붙은 모델 무관), 모드 C 활성 시 [claude-api] 규약으로 결정.
