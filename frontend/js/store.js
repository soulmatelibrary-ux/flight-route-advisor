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

/** OD 선택(§3.1 5번): 옵션 조회 → 경유 FIR/항공로 온디맨드 스코프 로드. */
export async function selectOd(dep, arr) {
  state.dep = dep;
  state.arr = arr;
  state.routeResult = null;
  state.selectedOptionIndex = null;
  state.focusFirs = [];
  state.focusAirways = [];
  notify({ type: "od:selecting" });
  try {
    const res = await api.routes(dep, arr);
    const options = res.data.options.map(adapt.toRouteOption);
    state.routeResult = { dep: res.data.dep, arr: res.data.arr, totalFlights: res.data.total_flights, options };
    await loadFocusReference(options);
    notify({ type: "od:selected" });
  } catch (err) {
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

/** 뷰모드 전환(F9): region/world는 전세계 벌크를 온디맨드 로드. */
export async function setViewMode(mode) {
  state.viewMode = mode;
  notify({ type: "viewmode:changing", mode });
  try {
    if (mode !== "focus") await ensureBulkLoaded();
    notify({ type: "viewmode:changed", mode });
  } catch (err) {
    notify({ type: "viewmode:error", message: describeError(err) });
    throw err;
  }
}
