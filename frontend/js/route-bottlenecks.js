/**
 * 세그먼트 병목 신호 종합 (docs/13-ai-reasoning-dev-plan.md STEP A5, doc11 §17.3). A1(흐름관리
 * 영향률)·A3(경로 상층풍/시어)·A4(섹터 교통)를 하나의 구조화 배열로 묶는다.
 *
 * **1단계 "부분 힌트" 범위(정직하게 명시, docs/07-checklist.md A5 항목 참고)**: doc11 §17.3은
 * 완전한 세그먼트 병목(교통×기상×경로교차)을 목표로 제시하지만, 그건 §13(교통 이력 프로파일)·
 * §15①(구간별 상층풍)·④(SIGMET/PIREP 루트 교차 판정)이 선행돼야 하는 **후속** 과제라고 그
 * 문서 자신이 명시한다(둘 다 이 저장소엔 아직 없음 — hazards.js도 교차판정을 의도적으로
 * 미구현 상태로 남겼다, [07-checklist](./07-checklist.md) F5 §"의도적으로 축소한 범위" 참고).
 * 그래서 이번 버전은 **이미 검증된 세 신호(A1/A3/A4)를 그대로 모으기만** 한다 — 새 임계값을
 * 발명하지 않고 각 신호가 이미 가진 등급함수(A3 `catGrade`, A4 `trafficGrade`)만 재사용한다.
 * "FIR별 흐름관리 유효창"(doc11이 제안한 4번째 신호)은 이 앱에 **실시간 흐름관리 피드가
 * 없어(`/api/flow-management`는 과거 배치 이력일 뿐, "지금 발효 중"을 판정할 근거가 없음)
 * 포함하지 않는다 — 없는 실시간성을 지어내지 않는다(허위 정보 생성 금지 원칙).
 *
 * A1(흐름관리)·A3(상층풍)은 경로 전체 단위 신호라 특정 FIR에 귀속시키지 않는다(`fir: null`) —
 * 원본 어디에도 "이 시어가 정확히 이 FIR 것"이라 판정할 근거(구간별 좌표→FIR 매핑)가 없어
 * 임의로 만들지 않는다. A4(섹터 교통)만 유일하게 실제 FIR(RKRR, 유일하게 섹터 데이터가
 * 있는 FIR)에 귀속 가능하다.
 *
 * **A6(터미널 신호 — 진출입 게이트·출발 활주로 분포)은 의도적으로 여기 포함하지 않는다**
 * (통합 리뷰 지적, 2026-07-24 — 문서에 명시가 안 돼 있어 남겨둠): A6는 "이 경로가 어떤
 * 게이트·활주로를 쓰는가"라는 경로 자체의 속성이라 이미 `route-panel.js`가 경로 카드에
 * 항상 표시하고, 병목 여부를 판정할 등급/임계값도 없다(그냥 사실 정보). 반면 이 파일이
 * 모으는 신호(A1/A3/A4/A7)는 전부 "정체·위험 가능성"을 등급화한 것 — 성격이 달라 같은
 * 배열에 섞으면 오히려 "왜 게이트 정보가 병목 목록에 있지"라는 혼란만 생긴다.
 *
 * **A7(SUAS/MOA 통과시각 발효 판정, docs/13 STEP A7, 신규 파생 — 완성본에도 없던 신호)**:
 * 경로가 지나는 SUAS/MOA 폴리곤 + 통과 예상시각(A3와 동일한 근사 — 순항 TAS 고정, 누적거리
 * 기반)으로 발효 여부를 판정해 `kind:"airspace"` 항목을 추가한다. 발효시간이 구조화 파싱된
 * 경우만 활성/비활성을 판정하고, 비정형(SR-SS/BY NOTAM 등)은 "확인 필요"로만 표시 —
 * 단정하지 않는다(안전 우선, docs/13 STEP A7 수용기준 (2)). `backend/batch/build_suas.py`를
 * 아직 안 돌렸으면(scheduleStatus가 null) 그 SUAS는 조용히 건너뛴다(수용기준 (3)과 동일한
 * 정신 — 없는 데이터로 판정을 지어내지 않음).
 */
import { catGrade, ptDist } from "./layers/wind.js";
import { pointInPolygon, boundsOfPolygons } from "./geo.js";
import { api, ApiError } from "./api.js";
import { toSuas } from "./adapters.js";

const WEEKDAY_CODES = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];

function previousWeekday(weekdayCode) {
  const idx = WEEKDAY_CODES.indexOf(weekdayCode);
  return WEEKDAY_CODES[(idx + 6) % 7];
}

/** 순수 함수 — HHMM 정수(예: 2300, 400)로 표현된 발효 구간이 주어진 요일·시각을 포함하는지.
 * 자정을 넘는 구간(utcStart>utcEnd, 예: "SAT 2300-0400Z")은 **시작 요일 기준**으로 판정한다 —
 * 이 구간은 "그 요일 저녁부터 다음날 새벽까지" 하나로 이어지는 창이라, 저녁 쪽(hhmm>=s)은
 * 오늘이 days에 있어야, 새벽 쪽(hhmm<=e)은 **어제**가 days에 있어야 활성이다(리뷰 지적,
 * 2026-07-24 — 원래는 "오늘이 days에 있으면 저녁·새벽 둘 다 활성"으로 잘못 판정해, days에
 * 없는 요일의 새벽 시간대를 활성으로 오판(예: MON-FRI만 있는데 월요일 00:30을 활성으로
 * 오판 — 일요일 밤 활성이 없으므로 실제로는 비활성이어야 함)하거나, 반대로 실제 활성인
 * 새벽 시간대를 비활성으로 놓치는(예: SAT 2300-0400인데 일요일 02:00을 비활성으로 오판 —
 * 토요일 밤이 이어지는 것이므로 실제로는 활성이어야 함) 두 방향 버그가 모두 있었다). */
export function isSuasActiveAt(segments, weekdayCode, hhmm) {
  const yesterday = previousWeekday(weekdayCode);
  for (const seg of segments ?? []) {
    const { utcStart: s, utcEnd: e } = seg;
    if (s <= e) {
      if (seg.days.includes(weekdayCode) && hhmm >= s && hhmm <= e) return true;
    } else {
      if (seg.days.includes(weekdayCode) && hhmm >= s) return true; // 저녁 쪽 — 오늘 시작
      if (seg.days.includes(yesterday) && hhmm <= e) return true; // 새벽 쪽 — 어제 저녁부터 이어짐
    }
  }
  return false;
}

// 경로 좌표(track_coords/full_route_coords)는 이름 붙은 픽스만 담은 성긴 배열이라(공항
// 인근은 촘촘, 대양 횡단 구간은 성김 — adsb.js의 sampleRoutePoints 주석과 동일한 특성),
// 두 픽스 사이에 SUAS 폴리곤이 통째로 들어가 있으면 픽스 자체는 폴리곤 밖인데 그 사이
// 구간은 실제로 통과하는 경우를 놓친다. 구간 길이에 비례해 보간 지점 수를 정한다(고정
// 개수였다가 리뷰에서 지적됨, 2026-07-24 — 성긴 구간이 길면 작은 SUAS 폴리곤을 여전히
// 건너뛸 수 있었음). 최소 간격 5NM마다 한 번 점검, 구간 하나가 과도하게 길어도(대양 횡단)
// 계산량이 폭발하지 않도록 구간당 상한을 둔다.
const _SUAS_INTERP_NM_PER_STEP = 5;
const _SUAS_INTERP_MIN_STEPS = 10;
const _SUAS_INTERP_MAX_STEPS = 400;

/** 순수 함수 — 경로가 폴리곤을 처음 지나는 지점까지 누적거리로 통과까지 걸리는 시간(분)을
 * 근사한다(A3 wind.js의 ptDist·순항 TAS 가정과 동일 정밀도). 구간을 보간해 점검하므로
 * 픽스 사이에 폴리곤이 있어도 감지한다(위 주석 참고). 안 지나면 null.
 * ⚠ 알려진 한계: 경도를 단순 선형보간해 날짜변경선을 넘는 구간(예: -170°↔170°)에서는
 * 반대쪽(먼 쪽)으로 보간될 수 있다(geo.js `unwrapLongitudes`가 다루는 것과 동일 종류의
 * 문제). SUAS 데이터가 한국·인접국 중심이라 실질적 영향은 낮지만 고쳐진 것은 아니다. */
export function findSuasCrossingEtaMin(coords, polygon, tasKt) {
  if (coords.length === 0) return null;
  let cumNm = 0;
  const [lat0, lon0] = coords[0];
  if (pointInPolygon(lat0, lon0, polygon)) return 0;
  for (let i = 1; i < coords.length; i++) {
    const [lat1, lon1] = coords[i - 1];
    const [lat2, lon2] = coords[i];
    const segNm = ptDist({ lat: lat1, lon: lon1 }, { lat: lat2, lon: lon2 }) * 60;
    const steps = Math.min(
      _SUAS_INTERP_MAX_STEPS,
      Math.max(_SUAS_INTERP_MIN_STEPS, Math.ceil(segNm / _SUAS_INTERP_NM_PER_STEP)),
    );
    for (let step = 1; step <= steps; step++) {
      const t = step / steps;
      const lat = lat1 + (lat2 - lat1) * t;
      const lon = lon1 + (lon2 - lon1) * t;
      if (pointInPolygon(lat, lon, polygon)) return ((cumNm + segNm * t) / tasKt) * 60;
    }
    cumNm += segNm;
  }
  return null;
}

/** 순수 함수 — 경로가 지나는 SUAS 중 발효시간 데이터가 있는 것만 병목 후보로 산출.
 * `nowMs`를 인자로 받아 순수성을 유지(호출부가 Date.now() 결과를 주입, docs 관례상 이
 * 함수 자체는 시각을 스스로 만들지 않음). */
export function suasBottleneckItems(coords, suasList, nowMs, tasKt) {
  const items = [];
  for (const suas of suasList ?? []) {
    const etaMin = findSuasCrossingEtaMin(coords, suas.polygon, tasKt);
    if (etaMin === null) continue; // 경로가 이 공역을 지나지 않음
    if (!suas.scheduleStatus) continue; // 발효시간 배치 미실행 — 조용히 스킵
    const label = `${suas.name || suas.ident}(${suas.ident}) 통과 예정(약 ${Math.round(etaMin)}분 후)`;
    if (suas.scheduleStatus === "confirm_required") {
      items.push({
        scope: "airspace", fir: null, kind: "airspace",
        label: `${label} — 발효시간 확인 필요(비정형: ${suas.effTimesRaw || "미기재"})`,
        severity: "info",
      });
      continue;
    }
    const arrival = new Date(nowMs + etaMin * 60000);
    const weekday = WEEKDAY_CODES[arrival.getUTCDay()];
    const hhmm = arrival.getUTCHours() * 100 + arrival.getUTCMinutes();
    if (isSuasActiveAt(suas.scheduleSegments, weekday, hhmm)) {
      items.push({
        scope: "airspace", fir: null, kind: "airspace",
        label: `${label} — 활성 시간대 통과, 우회 가능성 확인`,
        severity: "warn",
      });
    }
  }
  return items;
}

function describeError(err) {
  if (err instanceof ApiError) {
    return err.status === 0 ? "네트워크 연결 실패" : err.message;
  }
  return String(err?.message ?? err);
}

/**
 * 순수 함수 — 이미 계산된 세 신호를 구조화 배열로 합친다(부수효과 없음, 단위테스트 대상).
 * @param {object} context
 * @param {object|null} context.flowImpact - `/api/routes/flow` 응답의 `data`(found=false거나 null이면 신호 없음)
 * @param {object|null} context.windRec - `wind.js`의 `getRecommendation()`(추천 FL의 {maxShear,shearFrom,shearTo,wc,fl})
 * @param {Array|null} context.sectorDemand - `analyze-sectors.js`의 `getDemand()`(통과 섹터로 필터링된 sectorDemand 결과)
 * @param {object} context.windConfig - `CONFIG.wind`(catGrade 임계값 재사용)
 * @param {Array|null} context.suasItems - `suasBottleneckItems()`가 이미 계산해 둔 항공 결과(A7)
 */
export function routeBottlenecks({ flowImpact, windRec, sectorDemand, windConfig, suasItems }) {
  const items = [];

  if (flowImpact?.found) {
    items.push({
      scope: "route",
      fir: null,
      kind: "flow_impact",
      label: `흐름관리 영향률 ${flowImpact.impact_pct}%(${flowImpact.affected_flights}/${flowImpact.total_flights}편, 추정치)`,
      severity: "info",
    });
  }

  if (windRec) {
    const [gradeLabel] = catGrade(windRec.maxShear, windConfig);
    if (gradeLabel !== "약함 이하") {
      items.push({
        scope: "route",
        fir: null,
        kind: "wind_shear",
        label: `연직시어 ${gradeLabel} (최대 ${windRec.maxShear.toFixed(1)}kt/1000ft, 경로 ${windRec.shearFrom}~${windRec.shearTo}% 구간) — FL${windRec.fl}`,
        severity: gradeLabel === "강함 가능" ? "warn" : "info",
      });
    }
  }

  for (const s of sectorDemand ?? []) {
    const [gradeLabel] = s.grade;
    if (gradeLabel === "원활") continue;
    items.push({
      scope: "sector",
      fir: "RKRR",
      kind: "sector_traffic",
      label: `${s.nameEn ?? s.sectorId}(${s.sectorId}) 교통 ${gradeLabel} (현재 ${s.current}대, +10분 후 ${s.future10}대)`,
      severity: gradeLabel === "혼잡" ? "warn" : "info",
    });
  }

  items.push(...(suasItems ?? []));

  return items;
}

function line(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div;
}

/**
 * DOM 패널(#route-bottlenecks) 관리 + A1 흐름관리 영향률 자체 조회(route-flow-summary.js와
 * 동일하게 독립 조회 — 이 코드베이스 위젯 공통 관례). A3/A4는 자체 조회하지 않고 이미 계산을
 * 끝낸 windLayer/sectorPanel의 요약 getter만 읽는다(중복 API 호출·중복 ADS-B 구독 방지).
 * main.js가 windLayer.update()/sectorPanel.update()가 끝난 뒤 호출해야 최신 신호를 읽는다.
 */
export function createBottlenecksPanel(CONFIG, windLayer, sectorPanel) {
  const panelEl = document.getElementById("route-bottlenecks");
  const windConfig = CONFIG.wind;
  let seq = 0;
  // update() 이후 도착하는 ADS-B 스냅샷마다 섹터 신호만 다시 그리기 위한 캐시(refreshSectorSignal
  // 참고) — A1은 매 스냅샷마다 재조회하지 않는다(12초마다 서버를 다시 때릴 이유가 없음, ADS-B
  // 폴링 주기와 무관하게 노선 선택 시 1회만 조회).
  let lastFlowImpact = null;
  let lastFlowError = null;
  let lastSuasItems = [];
  let lastDep = null;
  let lastArr = null;

  function clearPanel() {
    if (panelEl) {
      panelEl.hidden = true;
      panelEl.innerHTML = "";
    }
  }

  function renderItems(items, flowError) {
    if (!panelEl) return;
    if (items.length === 0 && !flowError) {
      clearPanel();
      return;
    }
    panelEl.hidden = false;
    panelEl.innerHTML = "";
    panelEl.append(line("경로 병목 신호 (1단계 — 흐름관리·상층풍·섹터교통·특수공역, 부분 힌트)"));
    // 흐름관리 조회 실패는 "신호 없음"과 구분해 명시한다(route-flow-summary.js와 동일 원칙) —
    // 안 그러면 "이 노선은 흐름관리 영향이 없다"와 "서버 응답을 못 받았다"를 사용자가 구분 못 함.
    if (flowError) {
      const row = document.createElement("div");
      row.className = "bottleneck-row bottleneck-warn";
      row.textContent = `흐름관리 영향률 조회 실패 — ${flowError}`;
      panelEl.append(row);
    }
    for (const item of items) {
      const row = document.createElement("div");
      row.className = `bottleneck-row bottleneck-${item.severity}`;
      row.textContent = item.label;
      panelEl.append(row);
    }
  }

  function renderFromCache() {
    const items = routeBottlenecks({
      flowImpact: lastFlowImpact,
      windRec: windLayer.getRecommendation(),
      sectorDemand: sectorPanel.getDemand(),
      windConfig,
      suasItems: lastSuasItems,
    });
    renderItems(items, lastFlowError);
  }

  /** 경로 bbox로 SUAS 목록을 서버에서 걸러 받는다(18,000+건을 전부 클라이언트로 내려받지
   * 않기 위해 — reference.js가 항로/픽스에 이미 쓰는 것과 동일한 bbox 사전필터 관례).
   * 실패해도(예: SUAS 참조 레이어 자체가 아직 미포팅) 조용히 빈 배열로 취급 — doc13 STEP A7
   * 수용기준 (3) "SUAS 참조 레이어 미포팅 시 조용히 스킵"과 동일한 정신, 다른 신호(A1/A3/A4)는
   * 그대로 표시돼야 하므로 여기서 예외를 던지지 않는다. */
  async function fetchSuasForRoute(coords) {
    try {
      const [minLat, minLon, maxLat, maxLon] = boundsOfPolygons([coords]);
      const res = await api.suas({ bbox: `${minLat},${minLon},${maxLat},${maxLon}` });
      return res.data.map(toSuas);
    } catch {
      return [];
    }
  }

  async function update(dep, arr, coords) {
    const mySeq = ++seq;
    lastDep = dep;
    lastArr = arr;
    lastFlowImpact = null;
    lastFlowError = null;
    // lastSuasItems도 다른 캐시와 동일하게 await 전에 동기적으로 비운다(리뷰 지적,
    // 2026-07-24) — 안 비우면 이 await가 끝나기 전 도착하는 ADS-B 스냅샷(refreshSectorSignal)이
    // lastDep/lastArr는 이미 새 노선을 가리키는데 lastSuasItems만 이전 노선 것을 그대로 써서,
    // 병목 패널에 엉뚱한 노선의 SUAS 경고가 잠깐 섞여 나올 수 있었다.
    lastSuasItems = [];
    const [flowOutcome, suasList] = await Promise.all([
      api.routeFlow(dep, arr).then(
        (res) => ({ ok: true, data: res.data }),
        (err) => ({ ok: false, error: err }),
      ),
      fetchSuasForRoute(coords),
    ]);
    if (flowOutcome.ok) lastFlowImpact = flowOutcome.data;
    else lastFlowError = describeError(flowOutcome.error); // 흐름관리 신호만 조회 실패 — 다른 신호는 그대로 표시
    lastSuasItems = suasBottleneckItems(coords, suasList, Date.now(), windConfig.tasKt);
    if (mySeq !== seq) return; // 더 최신 선택이 진행 중 — 이 응답은 폐기
    renderFromCache();
  }

  /** ADS-B 스냅샷이 새로 도착해 sectorPanel의 getDemand()가 바뀔 때마다 main.js가 호출 —
   * A1(흐름관리, 재조회 없음)·A3(캐시)는 그대로 두고 A4(섹터 교통) 표시만 최신화한다.
   * 선택된 경로가 없으면(clear() 이후) 조용히 무시한다. */
  function refreshSectorSignal(dep, arr) {
    if (dep !== lastDep || arr !== lastArr) return; // 이 신호가 유효한 노선 선택이 아님
    if (!panelEl || panelEl.hidden) return; // 아직 update()가 한 번도 렌더한 적 없음(선택 안 됨)
    renderFromCache();
  }

  function clear() {
    seq += 1;
    lastDep = null;
    lastArr = null;
    lastFlowImpact = null;
    lastFlowError = null;
    lastSuasItems = [];
    clearPanel();
  }

  return { update, clear, refreshSectorSignal };
}
