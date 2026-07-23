/**
 * 공항 운항 KPI(ACDM) 패널 (docs/03-backend-api.md §4.2, 2단계).
 * FOIS/흐름관리 패널과 동일하게 OD 선택·뷰모드와 무관한 독립 조회 도구라 store.js
 * 전역 상태에 얹지 않고 이 모듈 안에서만 조회 세대를 관리한다.
 */
import { api, ApiError } from "./api.js";
import { toAirportOpsSummary } from "./adapters.js";

const _ICAO_RE = /^[A-Za-z]{4}$/;

function describeError(err) {
  if (err instanceof ApiError) {
    return err.status === 0 ? "네트워크 연결 실패 — 오프라인이거나 서버가 응답하지 않음" : err.message;
  }
  return String(err?.message ?? err);
}

function pct(rate) {
  return rate === null || rate === undefined ? "-" : `${(rate * 100).toFixed(1)}%`;
}

function minutes(value) {
  return value === null || value === undefined ? "-" : `${value.toFixed(1)}분`;
}

export function initOpsPanel() {
  const formEl = document.getElementById("ops-form");
  const airportEl = document.getElementById("ops-airport");
  const dateFromEl = document.getElementById("ops-date-from");
  const dateToEl = document.getElementById("ops-date-to");
  const summaryEl = document.getElementById("ops-summary");
  const resultEl = document.getElementById("ops-result");
  const errorEl = document.getElementById("ops-error");

  if (!formEl) return; // 패널 마크업이 없는 페이지(스모크 하네스 등)에서는 조용히 건너뜀

  let seq = 0;

  function showError(message) {
    errorEl.textContent = message;
    errorEl.hidden = !message;
  }

  function addRow(label, value) {
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = value;
    resultEl.append(dt, dd);
  }

  function renderResult(icao, data) {
    const departure = toAirportOpsSummary(data.departure);
    const arrival = toAirportOpsSummary(data.arrival);
    summaryEl.textContent = `${icao} — 출발 ${departure.flights}편 · 도착 ${arrival.flights}편`;
    resultEl.innerHTML = "";
    addRow("출발 정시율", pct(departure.onTimeRate));
    addRow("출발 평균 추가 taxi-out", minutes(departure.avgTaxiOutMin));
    addRow("출발 CTOT 준수율", pct(departure.ctotAdherence));
    addRow("도착 정시율", pct(arrival.onTimeRate));
    addRow("도착 평균 taxi-in", minutes(arrival.avgTaxiInMin));
    addRow("도착 평균 FIR→APP", minutes(arrival.avgFirToAppMin));
    resultEl.hidden = false;
  }

  async function search() {
    const airportRaw = airportEl.value.trim();
    if (!_ICAO_RE.test(airportRaw)) {
      showError("공항은 ICAO 4자리 영문이어야 함");
      return;
    }
    const icao = airportRaw.toUpperCase();
    showError("");
    const mySeq = ++seq;
    summaryEl.textContent = "조회 중…";
    resultEl.hidden = true;
    try {
      const res = await api.airportOps({
        icao,
        dateFrom: dateFromEl.value || undefined,
        dateTo: dateToEl.value || undefined,
      });
      if (mySeq !== seq) return; // 더 최신 조회가 진행 중 — 이 응답은 폐기(다른 패널과 동일 패턴)
      renderResult(icao, res.data);
    } catch (err) {
      if (mySeq !== seq) return;
      summaryEl.textContent = "";
      showError(describeError(err));
    }
  }

  // <form>+submit으로 감싸 Enter 키 제출도 지원(fois-panel.js와 동일 컨벤션).
  formEl.addEventListener("submit", (event) => {
    event.preventDefault();
    search();
  });
}
