/**
 * 로딩된 데이터 보관 + 파생 상수 재계산 (docs/04-frontend-migration.md §4.3, F4).
 * 결정 포커스 기본 + 전세계 온디맨드 부트 순서(§3.1)를 그대로 구현한다.
 * 구독형 단순 스토어 — 프레임워크 없이 main.js/layers가 subscribe()로 재렌더 트리거.
 */
import { api, ApiError } from "./api.js";
import * as adapt from "./adapters.js";

const state = {
  viewMode: "focus", // "focus" | "region" | "world"
  odPairs: [],
  bootAirports: [], // 부팅 시 저배율 민간/공용만(§3.1 2번)
  dep: null,
  arr: null,
  routeResult: null, // {dep,arr,totalFlights,options:[...]}
  selectedOptionIndex: null, // null = 전체 겹쳐보기(기본)
  focusFirs: [], // 결정 포커스: 선택 OD의 enroute FIR만
  focusAirways: [], // 결정 포커스: 경로 bbox 스코프 항공로
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
    const [odRes, apRes] = await Promise.all([api.odPairs(), api.airports({ type: "A,B" })]);
    state.odPairs = odRes.data.map(adapt.toOdPair);
    state.bootAirports = apRes.data.map(adapt.toAirport);
    for (const a of state.bootAirports) state.derived.airportByIcao.set(a.icao, a);
    notify({ type: "boot:ok" });
  } catch (err) {
    notify({ type: "boot:error", message: describeError(err) });
    throw err;
  }
}

function boundingBoxOfOptions(options) {
  let minLat = Infinity;
  let minLon = Infinity;
  let maxLat = -Infinity;
  let maxLon = -Infinity;
  let any = false;
  for (const o of options) {
    for (const [lat, lon] of o.trackCoords) {
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
  const icaoSet = new Set();
  for (const o of options) for (const icao of o.enrouteFirs) icaoSet.add(icao);
  if (icaoSet.size > 0) {
    const firRes = await api.firs({ icao: [...icaoSet].join(",") });
    state.focusFirs = firRes.data.map(adapt.toFir);
    for (const f of state.focusFirs) state.derived.firByIcao.set(f.icao, f);
  } else {
    state.focusFirs = [];
  }
  const bbox = boundingBoxOfOptions(options);
  if (bbox) {
    const awRes = await api.airways({ bbox: bbox.join(",") });
    state.focusAirways = awRes.data.map(adapt.toAirway);
  } else {
    state.focusAirways = [];
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
  notify({ type: "od:selecting" });
  try {
    const res = await api.routes(dep, arr);
    if (seq !== odRequestSeq) return; // 더 최신 선택이 진행 중 — 이 응답은 폐기
    const options = res.data.options.map(adapt.toRouteOption);
    state.routeResult = { dep: res.data.dep, arr: res.data.arr, totalFlights: res.data.total_flights, options };
    await loadFocusReference(options);
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
