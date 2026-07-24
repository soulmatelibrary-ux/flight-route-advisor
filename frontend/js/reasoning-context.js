/**
 * reasoningContext 어셈블러 (B2, docs/13-ai-reasoning-dev-plan.md STEP B2 · 스키마 §7/§7.2).
 * 순수 함수 — A1~A7이 이미 계산해 둔 값들을 §7 스키마 모양으로 옮겨 담을 뿐, 새 신호를
 * 계산하지 않는다(예외: castScript 자신이 인라인으로 하던 단순 산술 — usage_pct 백분율,
 * 빠른 대안 탐색, 월 총량→일평균 — 은 그대로 이식한다. 이건 "이식"이지 "신규 계산"이 아니다).
 * 부수효과 없음(DOM·fetch·Date.now() 없음, `nowKst`는 호출부가 주입) — 모드 C 서버 재사용 대비.
 *
 * 입력 계약이 STEP B2 원안(dep,arr,selectedRoute,flow,delayHistory,wind,sectorDemand,bottlenecks,metar)
 * 보다 넓다 — B1 리뷰 중 확인: `usage_pct`/`faster_alt`는 선택된 옵션 하나만으론 계산 불가하고
 * 전체 옵션 배열(총 운항편수 대비 비중, 다른 옵션과의 소요시간 비교)이 필요하다(docs/13 §7 개정 참고).
 * 그래서 `selectedRoute` 대신 `routeOptions`(전체) + `selectedIndex`를 받는다.
 */
import { catGrade } from "./layers/wind.js";
import { riskOf, windLine } from "./weather.js";

export const SCHEMA_VERSION = "1.0";

/** §7.2 필드별 민감도 태그 단일출처. `restricted` 등급 필드는 스키마 자체에 없으므로 여기 없음
 * (콜사인·편명·등록부호·FOIS reason 원문은 애초에 이 어셈블러의 입력에도 나오지 않는다). */
export const SENSITIVITY = Object.freeze({
  od: "public",
  selected_route: "public",
  faster_alt: "public",
  "flow.impact_pct": "public",
  "flow.on_time_affected": "public", // 항상 null(build_flow.py 미구현, on_time_pct와 동일 구조적 결측)
  "flow.on_time_normal": "public", // 항상 null(위와 동일)
  "flow.delay_affected_min": "public", // 항상 null(위와 동일)
  "flow.hour_impact_pct": "public",
  "flow.main_limits": "public",
  "flow.main_causes": "masked",
  "delay_history.hourly_flights": "public",
  "delay_history.hourly_avg_teet_min": "public",
  "delay_history.on_time_pct": "public",
  "delay_history.window": "public",
  "delay_history.causes": "masked",
  "delay_history.airport_hourly_flights": "public",
  wind: "public",
  sectors: "public",
  route_wx: "public",
  bottlenecks: "public",
  airport_wx: "public",
});

function round(n) {
  return n == null ? null : Math.round(n);
}

/** castScript 인라인 로직 이식(3370~3378줄) — 24시간 배열(`-1`=결측 센티널)을 선택 시간대
 * ±1시간 윈도우로 평균한 스칼라로 변환. 리뷰 지적(2026-07-24): flow_reasoning.flow_for()의
 * `hour_impact_pct`는 24개 배열 그대로인데 스키마(§7)는 선택 시간대 하나의 스칼라를 뜻한다 —
 * 이 스칼라화를 여기서 해야 한다(castScript도 인라인 산술로 처리, "신규 계산"이 아니라 "이식"). */
function windowedHourImpact(hourImpactPct, hour) {
  if (hour == null || !Array.isArray(hourImpactPct)) return null;
  const window = [(hour + 23) % 24, hour, (hour + 1) % 24];
  const vals = window.map((h) => hourImpactPct[h]).filter((v) => v != null && v >= 0); // -1 센티널 제거
  if (!vals.length) return null;
  return round(vals.reduce((s, v) => s + v, 0) / vals.length);
}

// castScript 완성본(3352줄) `rs.filter(x=>x[0]!=='미상')` 이식 — 분류 실패(원문 미기록) placeholder는
// 근거인 것처럼 노출하지 않는다. `build_flow.py`가 reason_code 결측 시 채우는 값이 "미기재"로 개명됐을
// 뿐 같은 역할이라 둘 다 제외(통합 리뷰 지적, 2026-07-24).
const GENERIC_CAUSE_LABELS = new Set(["미상", "미기재"]);

/** masked 필드 방어(리뷰 지적, §7.2 "원문이 들어오면 어셈블러가 드롭") — 분류코드+비율 쌍만 통과,
 * 길이 초과(자유서술 의심) 항목·분류 실패 placeholder는 드롭, 개수도 상한(통합 리뷰 지적: 원문을
 * `maxLabelLen` 이하 조각 여러 개로 쪼개 넣는 우회 방지 — 길이 상한만으로는 배열 항목 수 자체를
 * 못 막는다). 업스트림이 이미 비식별화했다는 가정을 코드로도 검증한다. */
function sanitizeCausePct(pairs, { maxLabelLen = 40, maxItems = 10 } = {}) {
  if (!Array.isArray(pairs)) return [];
  return pairs
    .filter((p) => Array.isArray(p) && p.length === 2 && typeof p[0] === "string" && p[0].length <= maxLabelLen && typeof p[1] === "number")
    .filter((p) => !GENERIC_CAUSE_LABELS.has(p[0]))
    .slice(0, maxItems);
}

/** masked 필드 방어(리뷰 지적) — 분류명 문자열 목록만 통과, 길이 초과 항목은 드롭, 개수 상한(통합
 * 리뷰 지적). `delay_history.causes`의 "미분류"/"미분류·검토필요"는 FOIS 분류체계 자체의 정식
 * 카테고리(A2 `CAUSES` 골든 13종 중 일부)라 `main_causes`와 달리 드롭 대상이 아니다 — 실제 결측
 * placeholder가 아니라 "분류상 미분류"라는 유효한 분류값이므로 그대로 통과시킨다. */
function sanitizeCauseLabels(labels, { maxLabelLen = 40, maxItems = 20 } = {}) {
  if (!Array.isArray(labels)) return [];
  return labels.filter((s) => typeof s === "string" && s.length <= maxLabelLen).slice(0, maxItems);
}

/** `public` 필드 방어(C3 리뷰 지적, 2026-07-24) — `flow.main_limits`(흐름관리일지 원문 제한 텍스트,
 * 예: "OODAK NOT AVBL")도 원문 자유서술이라는 점은 masked 필드와 같은 성격이라 동일하게 길이·개수
 * 상한을 둔다(단, D7상 분류코드 아닌 제한사항 텍스트 자체는 마스킹 대상이 아니라 `public`으로 유지 —
 * 상한만 적용). 이전엔 `flow.main_causes`/`delay_history.causes`만 상한이 있고 이 필드는 무제한으로
 * 통과시키고 있었다(체크리스트 §C2에 "C3 소관"으로 잘못 미뤄져 있던 것을 이번에 여기서 해소). */
function sanitizeLimits(limits, { maxLabelLen = 80, maxItems = 10 } = {}) {
  if (!Array.isArray(limits)) return [];
  return limits.filter((s) => typeof s === "string" && s.length <= maxLabelLen).slice(0, maxItems);
}

/** castScript 인라인 로직 이식 — 선택 옵션 대비 더 빠른 대안(다른 옵션 중 평균소요 최소, 3분 이상 단축 시만). */
function findFasterAlt(routeOptions, selectedIndex, selected) {
  if (selected?.avgMin == null) return null;
  let bestIdx = -1;
  for (let i = 0; i < routeOptions.length; i++) {
    if (i === selectedIndex) continue;
    const avg = routeOptions[i].avgMin;
    if (avg == null) continue;
    if (bestIdx === -1 || avg < routeOptions[bestIdx].avgMin) bestIdx = i;
  }
  if (bestIdx === -1) return null;
  const alt = routeOptions[bestIdx];
  if (alt.avgMin >= selected.avgMin - 3) return null; // castScript: 3분 미만 단축은 언급 안 함
  return {
    rank: bestIdx + 1,
    saves_min: round(selected.avgMin - alt.avgMin),
    gate_in: alt.gateIn ?? null,
    gate_out: alt.gateOut ?? null,
  };
}

function buildAirportWx(metar) {
  if (!metar) return null;
  return {
    cat: metar.fltCat ?? null,
    wind: windLine(metar),
    warn: riskOf(metar),
  };
}

/**
 * @param {object} p
 * @param {string} p.dep @param {string} p.arr
 * @param {number|null} p.totalFlights - routes_for().total_flights(od.monthly_flights)
 * @param {Array|null} p.routeOptions - routes_for().options를 adapters.toRouteOption()으로 변환한 전체 배열
 * @param {number|null} p.selectedIndex - 사용자가 선택한 옵션의 배열 인덱스(store.selectedOptionIndex), 미선택(null)이면 selected_route/faster_alt는 null
 * @param {object|null} p.flow - A1: api.routeFlow(dep,arr) 응답의 `data`(flow_for() 결과) 또는 null
 * @param {object|null} p.delayHistory - A2: api.delayHistory(dep,arr,hour) 응답의 `data`(delay_history_for() 결과) 또는 null
 * @param {object|null} p.wind - A3: windLayer.getRecommendation()({fl,wc,maxShear,...}) 또는 null
 * @param {Array|null} p.sectorDemand - A4: sectorPanel.getDemand()(통과 섹터로 필터링됨) 또는 null(ADS-B 미가용/미선택)
 * @param {Array|null} p.bottlenecks - A5/A7: routeBottlenecks() 결과(없으면 [])
 * @param {{dep?: object|null, arr?: object|null}} [p.metar] - 공항별 원시 METAR(weather.js getMetar 원소) 또는 null
 * @param {object} p.windConfig - CONFIG.wind(shear_grade 등급 임계값 재사용, 하드코딩 금지)
 * @param {number|null} [p.hour] - 사용자가 선택한 시간대(0~23, 레거시 `rpHr.value`에 대응) — `flow.hour_impact_pct`
 *   스칼라화(±1시간 윈도우 평균)에 쓰인다. `delay_history.window`는 이미 API 호출부가 같은 hour로 조회해 옴.
 * @param {string} p.nowKst - 호출부가 주입하는 생성 시각(KST ISO, 순수성 유지 — 함수가 시각을 스스로 만들지 않음)
 * @returns {object} §7 스키마 객체(schema_version "1.0")
 */
export function buildReasoningContext({
  dep,
  arr,
  totalFlights = null,
  routeOptions = null,
  selectedIndex = null,
  flow = null,
  delayHistory = null,
  wind = null,
  sectorDemand = null,
  bottlenecks = null,
  metar = null,
  windConfig,
  hour = null,
  nowKst,
}) {
  const options = routeOptions ?? [];
  const totN = options.reduce((s, o) => s + (o.flights ?? 0), 0);

  const od = {
    dep: dep ?? null,
    arr: arr ?? null,
    monthly_flights: totalFlights ?? null,
    daily_avg: totalFlights != null ? Math.max(1, round(totalFlights / 31)) : null,
    route_count: options.length,
  };

  let selectedRoute = null;
  let fasterAlt = null;
  if (selectedIndex != null && options[selectedIndex]) {
    const sel = options[selectedIndex];
    selectedRoute = {
      rank: selectedIndex + 1,
      usage_pct: totN > 0 && sel.flights != null ? round((100 * sel.flights) / totN) : null,
      avg_min: sel.avgMin ?? null,
      enroute_firs: sel.enrouteFirs ?? [],
      gate_in: sel.gateIn ?? null,
      gate_out: sel.gateOut ?? null,
    };
    fasterAlt = findFasterAlt(options, selectedIndex, sel);
  }

  const flowOut = flow?.found
    ? {
        found: true,
        impact_pct: flow.impact_pct ?? null,
        // on_time_affected/on_time_normal/delay_affected_min: build_flow.py가 미구현으로 항상 None을
        // 반환한다(docs/07-checklist.md 기 확인) — delay_history.on_time_pct와 같은 처지의 구조적 결측.
        // 그대로 통과(이미 null)시키되, 통합 리뷰 지적(2026-07-24)으로 이 사실을 명시한다 — Phase C
        // 프롬프트 작성자가 §7 예시의 숫자를 실제 신호로 오인하지 않도록.
        on_time_affected: flow.on_time_affected ?? null,
        on_time_normal: flow.on_time_normal ?? null,
        delay_affected_min: flow.delay_affected_min ?? null,
        main_causes: sanitizeCausePct(flow.main_causes),
        main_limits: sanitizeLimits(flow.main_limits),
        hour_impact_pct: windowedHourImpact(flow.hour_impact_pct, hour),
      }
    : { found: false, impact_pct: null, on_time_affected: null, on_time_normal: null, delay_affected_min: null, main_causes: [], main_limits: [], hour_impact_pct: null };

  const delayHistoryOut = delayHistory?.found
    ? {
        found: true,
        hourly_flights: delayHistory.hourly_flights ?? null,
        hourly_avg_teet_min: delayHistory.hourly_avg_teet_min ?? null,
        on_time_pct: null, // A2 계약상 항상 null(doc §STEP A2 — 계산식 미검증, 추정치를 지어내지 않음)
        window: delayHistory.window ?? null,
        causes: sanitizeCauseLabels(delayHistory.causes),
        // OPEN ITEM(docs/13 §7, 2026-07-24 사용자 확인: B2 진행하며 null로 유보) — odhr.py가
        // 아티팩트의 ap[dep]를 아직 노출하지 않아 항상 null.
        airport_hourly_flights: null,
      }
    : { found: false, hourly_flights: null, hourly_avg_teet_min: null, on_time_pct: null, window: null, causes: [], airport_hourly_flights: null };

  // windConfig 누락(계약 위반) 시에도 크래시 대신 등급만 null로 degrade(리뷰 지적, 방어적 코딩).
  const canGradeShear = wind?.maxShear != null && windConfig?.shearStrongKt1000ft != null && windConfig?.shearModerateKt1000ft != null;
  const windOut = wind
    ? {
        rec_fl: wind.fl != null ? `FL${wind.fl}` : null,
        tail_head_kt: wind.wc != null ? round(wind.wc) : null,
        shear_kt_per_1000ft: wind.maxShear ?? null,
        shear_grade: canGradeShear ? catGrade(wind.maxShear, windConfig)[0] : null,
      }
    : null;

  const sectorsOut = (sectorDemand ?? []).map((s) => ({
    sectorId: s.sectorId,
    nameEn: s.nameEn ?? null,
    current: s.current ?? null,
    future10: s.future10 ?? null,
    future40: s.future40 ?? null,
    trend: s.trend ?? null,
    grade: Array.isArray(s.grade) ? s.grade[0] : (s.grade ?? null),
  }));

  return {
    schema_version: SCHEMA_VERSION,
    od,
    selected_route: selectedRoute,
    faster_alt: fasterAlt,
    flow: flowOut,
    delay_history: delayHistoryOut,
    wind: windOut,
    sectors: sectorsOut,
    // OPEN ITEM(docs/13 §7, 2026-07-24 사용자 확인: B2 진행하며 null로 유보) — 경로상 강수 에코 %를
    // 산출하는 A-step이 Phase A에 없다(신규 A8 필요 여부 결정 대기).
    route_wx: { enroute_echo_pct: null },
    bottlenecks: bottlenecks ?? [],
    airport_wx: {
      dep: buildAirportWx(metar?.dep),
      arr: buildAirportWx(metar?.arr),
    },
    generated_at_kst: nowKst ?? null,
  };
}
