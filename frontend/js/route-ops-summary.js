/**
 * 노선-공항운항KPI(ACDM) 라이트 연동 (사용자 요청, 2026-07-23 — 참고 서비스 화면의
 * "정시율·택시아웃" 항목). route-fois-summary.js와 동일한 패턴(store.js의 od:selected만
 * 구독하는 독립 위젯, ops-panel.js의 범용 수동 조회와는 별개)을 그대로 따른다.
 *
 * ⚠ 의도적 한계: ACDM KPI는 "노선(출발-도착 쌍)" 단위가 아니라 "공항" 단위 집계다
 * (route-fois-summary.js와 동일한 한계) — 이 위젯은 "출발/도착 공항이 최근 이랬다"는
 * 참고 정보만 보여줄 뿐, 이 특정 노선의 실적으로 오인되지 않게 라벨을 공항 단위로 명시한다.
 */
import { getState, subscribe } from "./store.js";
import { api, ApiError } from "./api.js";
import { toAirportOpsSummary } from "./adapters.js";

function describeError(err) {
  if (err instanceof ApiError) {
    return err.status === 0 ? "네트워크 연결 실패" : err.message;
  }
  return String(err?.message ?? err);
}

function pct(rate) {
  return rate === null || rate === undefined ? "-" : `${Math.round(rate * 100)}%`;
}

function minutes(value) {
  return value === null || value === undefined ? "-" : `${value.toFixed(1)}분`;
}

function summaryLine(label, icao, outcome) {
  if (outcome.status === "rejected") return `${label}(${icao}): 조회 실패 — ${describeError(outcome.reason)}`;
  return label === "출발"
    ? (() => {
        const d = toAirportOpsSummary(outcome.value.data.departure);
        return `출발(${icao}) 정시율 ${pct(d.onTimeRate)} · 택시아웃 ${minutes(d.avgTaxiOutMin)} · CTOT준수 ${pct(d.ctotAdherence)}`;
      })()
    : (() => {
        const a = toAirportOpsSummary(outcome.value.data.arrival);
        return `도착(${icao}) 정시율 ${pct(a.onTimeRate)} · 택시인 ${minutes(a.avgTaxiInMin)}`;
      })();
}

export function initRouteOpsSummary() {
  const el = document.getElementById("route-ops-summary");
  if (!el) return; // 마크업이 없는 페이지(스모크 하네스 등)에서는 조용히 건너뜀

  let seq = 0;

  async function update(dep, arr) {
    const mySeq = ++seq;
    el.textContent = "출발·도착 공항 운항 KPI 조회 중…";
    const [depOutcome, arrOutcome] = await Promise.allSettled([
      api.airportOps({ icao: dep }),
      api.airportOps({ icao: arr }),
    ]);
    if (mySeq !== seq) return; // 더 최신 노선 선택이 진행 중 — 이 응답은 폐기

    el.innerHTML = "";
    const depLine = document.createElement("div");
    depLine.textContent = summaryLine("출발", dep, depOutcome);
    const arrLine = document.createElement("div");
    arrLine.textContent = summaryLine("도착", arr, arrOutcome);
    el.append(depLine, arrLine);
  }

  function clear() {
    seq += 1; // 진행 중이던 조회는 이제 폐기 대상
    el.textContent = "";
  }

  subscribe((state, event) => {
    if (event.type === "od:selecting") clear();
    if (event.type === "od:selected" && state.dep && state.arr) {
      update(state.dep, state.arr);
    }
    if (event.type === "od:error") clear();
  });

  const initial = getState();
  if (initial.dep && initial.arr && initial.routeResult) {
    update(initial.dep, initial.arr);
  }
}
