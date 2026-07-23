/**
 * 로딩된 데이터 보관 + 파생 상수 재계산 (docs/04-frontend-migration.md §4.3, F4).
 * 결정 포커스 기본 + 전세계 온디맨드 부트 순서(§3.1)를 그대로 구현한다.
 * 구독형 단순 스토어 — 프레임워크 없이 main.js/layers가 subscribe()로 재렌더 트리거.
 */
import { api, ApiError } from "./api.js";
import * as adapt from "./adapters.js";
import { getConfig } from "./config.js";
import { boundsOfPolygons, unionBounds } from "./geo.js";

const state = {
  viewMode: "focus", // "focus" | "region" | "world"
  odPairs: [],
  bootAirports: [], // 부팅 시 저배율 민간/공용만(§3.1 2번)
  dep: null,
  arr: null,
  routeResult: null, // {dep,arr,totalFlights,options:[...]}
  selectedOptionIndex: null, // null = 전체 겹쳐보기(기본)
  focusFirs: [], // 결정 포커스: 선택 OD의 enroute FIR + 인천(홈) FIR은 상시(2026-07-23)
  focusAirways: [], // 결정 포커스: 경로 bbox 스코프 항공로
  focusWaypoints: [], // 결정 포커스: 경로 bbox 스코프 픽스(2026-07-23 추가)
  bulk: null, // 전세계/지역 컨텍스트 온디맨드 캐시: {firs,tca,airways,airports,navaids,waypoints}
  derived: { firByIcao: new Map(), airportByIcao: new Map() },
};

const listeners = new Set();
export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
function notify(event) {
  for (const fn of listeners) fn(state, event);
}

export function getState() {
  return state;
}

function describeError(err) {
  if (err instanceof ApiError) {
    return err.status === 0 ? "네트워크 연결 실패 — 오프라인이거나 서버가 응답하지 않음" : err.message;
  }
  return String(err?.message ?? err);
}

/** 부트 최소 로드(§3.1 2번): OD select 채움 + OD 지점 표시용 저배율 공항. */
export async function bootMinimal() {
  try {
    const [odRes, apRes] = await Promise.all([
      api.odPairs(),
      api.airports({ type: "A,B" }),
      // 인천(홈) FIR·픽스는 노선 선택 전에도 상시 표시(사용자 요청, 2026-07-23) — 빈
      // options로 불러도 loadFocusReference가 homeFirIcao는 항상 포함해 계산한다.
      loadFocusReference([]),
    ]);
    state.odPairs = odRes.data.map(adapt.toOdPair);
    state.bootAirports = apRes.data.map(adapt.toAirport);
    for (const a of state.bootAirports) state.derived.airportByIcao.set(a.icao, a);
    notify({ type: "boot:ok" });
  } catch (err) {
    notify({ type: "boot:error", message: describeError(err) });
    throw err;
  }
}

// 부트 시 airports는 A/B(민간/공용)만 받는다(§3.1 2번, 최소 로드) — 그래서 군용/기타
// 타입 공항이 dep/arr로 선택되면 bootAirports에 없어 focus 모드 마커가 조용히 빠진다
// (리뷰 지적사항, 2026-07-23). 누락분만 icao 단건 조회(타입 무관)로 보강한다.
// pendingAirportIcaos: 같은 icao를 향한 동시 요청이 중복 fetch→bootAirports 중복 push로
// 이어지지 않도록 하는 가드(빠른 연속 OD 선택 시 재현 가능).
const pendingAirportIcaos = new Set();

async function ensureAirportsLoaded(icaos) {
  const missing = icaos.filter(
    (icao) => icao && !state.derived.airportByIcao.has(icao) && !pendingAirportIcaos.has(icao)
  );
  if (missing.length === 0) return;
  for (const icao of missing) pendingAirportIcaos.add(icao);
  try {
    const res = await api.airports({ icao: missing.join(",") });
    const fetched = res.data.map(adapt.toAirport);
    for (const a of fetched) {
      state.derived.airportByIcao.set(a.icao, a);
      state.bootAirports.push(a);
    }
  } finally {
    for (const icao of missing) pendingAirportIcaos.delete(icao);
  }
}

function boundingBoxOfOptions(options) {
  let minLat = Infinity;
  let minLon = Infinity;
  let maxLat = -Infinity;
  let maxLon = -Infinity;
  let any = false;
  for (const o of options) {
    // trackCoords는 인천 인근 국내 구간(incheon_track_fixes)만이라 이것만 쓰면 항로·픽스가
    // 출발지~경유국까지 안 뻗고 한국 인근에만 좁혀지는 버그가 있었다(사용자 지적, 2026-07-23
    // 재검증에서 발견 — 노드 하네스로 VTBS→RKSI 재현: FIR은 14개로 확장됐는데 픽스는
    // 여전히 437개 그대로였음). route.js의 coordsOf와 동일하게 fullRouteCoords를 우선한다.
    const coords = o.fullRouteCoords.length > 0 ? o.fullRouteCoords : o.trackCoords;
    for (const [lat, lon] of coords) {
      any = true;
      if (lat < minLat) minLat = lat;
      if (lat > maxLat) maxLat = lat;
      if (lon < minLon) minLon = lon;
      if (lon > maxLon) maxLon = lon;
    }
  }
  return any ? [minLat, minLon, maxLat, maxLon] : null;
}

async function loadFocusReference(options) {
  const CONFIG = getConfig();
  // 인천(홈) FIR은 노선의 enrouteFirs에 안 잡히는 예외적 경우에도 상시 표시(사용자 요청,
  // 2026-07-23) — icaoSet에 항상 넣어 둔다.
  const icaoSet = new Set([CONFIG.display.homeFirIcao]);
  for (const o of options) for (const icao of o.enrouteFirs) icaoSet.add(icao);
  const firRes = await api.firs({ icao: [...icaoSet].join(",") });
  state.focusFirs = firRes.data.map(adapt.toFir);
  for (const f of state.focusFirs) state.derived.firByIcao.set(f.icao, f);

  // 항로·픽스 조회 범위 = 노선 bbox ∪ 인천 FIR 자체 bbox(노선이 없어도 인천 픽스는 항상
  // 나오도록). 픽스는 main.js의 전세계 컨텍스트 처리와 동일하게 bbox로 서버에서 좁혀
  // 받는다(전량 800 하드캡 문제, 2026-07-23).
  const routeBbox = boundingBoxOfOptions(options);
  const homeFir = state.focusFirs.find((f) => f.icao === CONFIG.display.homeFirIcao);
  const homeBbox = homeFir ? boundsOfPolygons(homeFir.polygons) : null;
  const bboxList = [routeBbox, homeBbox].filter(Boolean);
  if (bboxList.length > 0) {
    const bbox = unionBounds(bboxList).join(",");
    const [awRes, wpRes] = await Promise.all([
      api.airways({ bbox }),
      api.waypoints({ bbox, limit: CONFIG.display.waypointLimit }),
    ]);
    state.focusAirways = awRes.data.map(adapt.toAirway);
    state.focusWaypoints = wpRes.data.map(adapt.toWaypoint);
  } else {
    state.focusAirways = [];
    state.focusWaypoints = [];
  }
}

// selectOd 경쟁 조건 방지(리뷰 지적사항, 2026-07-22): 사용자가 도착지를 빠르게 연속
// 변경하면 먼저 시작된 요청이 나중에 끝나 최신 선택을 덮어쓸 수 있다 — 세대 토큰으로
// 자신이 최신 호출이 아니게 된 경우 상태 반영을 건너뛴다.
let odRequestSeq = 0;

/** OD 선택(§3.1 5번): 옵션 조회 → 경유 FIR/항공로 온디맨드 스코프 로드. */
export async function selectOd(dep, arr) {
  const seq = ++odRequestSeq;
  state.dep = dep;
  state.arr = arr;
  state.routeResult = null;
  state.selectedOptionIndex = null;
  state.focusFirs = [];
  state.focusAirways = [];
  state.focusWaypoints = [];
  notify({ type: "od:selecting" });
  try {
    const res = await api.routes(dep, arr);
    if (seq !== odRequestSeq) return; // 더 최신 선택이 진행 중 — 이 응답은 폐기
    const options = res.data.options.map(adapt.toRouteOption);
    state.routeResult = { dep: res.data.dep, arr: res.data.arr, totalFlights: res.data.total_flights, options };
    await Promise.all([loadFocusReference(options), ensureAirportsLoaded([dep, arr])]);
    if (seq !== odRequestSeq) return;
    notify({ type: "od:selected" });
  } catch (err) {
    if (seq !== odRequestSeq) return; // 이미 폐기된 요청의 실패는 무시
    notify({ type: "od:error", message: describeError(err) });
    throw err;
  }
}

export function selectOption(index) {
  state.selectedOptionIndex = index;
  notify({ type: "option:selected" });
}

async function ensureBulkLoaded() {
  if (state.bulk) return; // 세션 캐시 — 모드 재전환 시 재요청하지 않음(§3.1 6번 각주)
  const [firs, tca, airways, airports, navaids, waypoints] = await Promise.all([
    api.firs(),
    api.tca(),
    api.airways(),
    api.airports(),
    api.navaids(),
    api.waypoints(),
  ]);
  state.bulk = {
    firs: firs.data.map(adapt.toFir),
    tca: tca.data.map(adapt.toTca),
    airways: airways.data.map(adapt.toAirway),
    airports: airports.data.map(adapt.toAirport),
    navaids: navaids.data.map(adapt.toNavaid),
    waypoints: waypoints.data.map(adapt.toWaypoint),
  };
  for (const f of state.bulk.firs) state.derived.firByIcao.set(f.icao, f);
  for (const a of state.bulk.airports) state.derived.airportByIcao.set(a.icao, a);
}

// setViewMode 경쟁 조건 방지(리뷰 지적사항, 2026-07-22): 사용자가 뷰모드를 빠르게 전환하면
// 진행 중인 ensureBulkLoaded()를 취소하고 새 요청을 시작한다(AbortController 패턴).
let viewModeAbortController = null;

/** 뷰모드 전환(F9): region/world는 전세계 벌크를 온디맨드 로드. */
export async function setViewMode(mode) {
  viewModeAbortController?.abort();  // 진행 중인 요청 취소
  viewModeAbortController = new AbortController();
  const signal = viewModeAbortController.signal;
  
  notify({ type: "viewmode:changing", mode });
  try {
    if (mode !== "focus") {
      await ensureBulkLoaded();
      if (signal.aborted) return;  // 도중 취소됨 — 상태 반영하지 않음
    }
    // 성공한 뒤에만 반영(리뷰 지적사항, 2026-07-22) — 벌크 로드 실패 시 state.viewMode를
    // 먼저 바꿔버리면 main.js의 renderForCurrentState()가 focus도 bulk도 아닌 상태에
    // 빠져 참조 레이어가 전혀 갱신되지 않는 버그가 있었다.
    state.viewMode = mode;
    notify({ type: "viewmode:changed", mode });
  } catch (err) {
    if (signal.aborted) return;  // 취소된 것 무시
    notify({ type: "viewmode:error", message: describeError(err) });
    throw err;
  }
}
