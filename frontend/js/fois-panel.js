/**
 * FOIS 지연원인 패널 (docs/03-backend-api.md §4.3, 2단계 착수).
 * ROUTE 패널(F6)과 달리 OD 선택·뷰모드와 무관한 독립 조회 도구라 store.js 전역
 * 상태에 얹지 않고 이 모듈 안에서만 조회 세대를 관리한다.
 */
import { api, ApiError } from "./api.js";
import { toFoisCause } from "./adapters.js";

const _ICAO_RE = /^[A-Za-z]{4}$/;

function describeError(err) {
  if (err instanceof ApiError) {
    return err.status === 0 ? "네트워크 연결 실패 — 오프라인이거나 서버가 응답하지 않음" : err.message;
  }
  return String(err?.message ?? err);
}

export function initFoisPanel() {
  const formEl = document.getElementById("fois-form");
  const airportEl = document.getElementById("fois-airport");
  const directionEl = document.getElementById("fois-direction");
  const dateFromEl = document.getElementById("fois-date-from");
  const dateToEl = document.getElementById("fois-date-to");
  const summaryEl = document.getElementById("fois-summary");
  const listEl = document.getElementById("fois-causes");
  const errorEl = document.getElementById("fois-error");

  if (!formEl) return; // 패널 마크업이 없는 페이지(스모크 하네스 등)에서는 조용히 건너뜀

  let seq = 0;

  function showError(message) {
    errorEl.textContent = message;
    errorEl.hidden = !message;
  }

  function renderResult(result) {
    summaryEl.textContent = `총 ${result.total}건`;
    listEl.innerHTML = "";
    for (const rawCause of result.causes) {
      const cause = toFoisCause(rawCause);
      const li = document.createElement("li");
      const row1 = document.createElement("div");
      row1.className = "row1";
      row1.textContent = `${cause.causeMajor ?? "-"} / ${cause.causeMinor ?? "-"}`;
      const row2 = document.createElement("div");
      row2.className = "row2";
      // textContent 대입은 브라우저가 자동으로 이스케이프하므로(innerHTML과 달리
      // HTML로 해석되지 않음) escapeHtml()이 불필요하다 — js/layers/*가 innerHTML/divIcon
      // html에 문자열을 넣을 때만 escapeHtml()을 쓰는 것과 다른 경로(docs/06 §8).
      row2.textContent =
        `${cause.causeProcess ?? "-"} · ${cause.involvedParty ?? "-"} · ${cause.reason ?? "-"} — ${cause.count}건`;
      li.append(row1, row2);
      listEl.appendChild(li);
    }
  }

  async function search() {
    const airportRaw = airportEl.value.trim();
    if (airportRaw && !_ICAO_RE.test(airportRaw)) {
      showError("공항은 ICAO 4자리 영문이어야 함");
      return;
    }
    showError("");
    const mySeq = ++seq;
    summaryEl.textContent = "조회 중…";
    listEl.innerHTML = "";
    try {
      const res = await api.foisDelays({
        direction: directionEl.value,
        airport: airportRaw ? airportRaw.toUpperCase() : undefined,
        dateFrom: dateFromEl.value || undefined,
        dateTo: dateToEl.value || undefined,
      });
      if (mySeq !== seq) return; // 더 최신 조회가 진행 중 — 이 응답은 폐기(selectOd 경쟁조건 방지와 동일 패턴)
      renderResult(res.data);
    } catch (err) {
      if (mySeq !== seq) return;
      summaryEl.textContent = "";
      showError(describeError(err));
    }
  }

  // <form>+submit(폼 제출)으로 감싸 Enter 키 제출도 지원(버튼 클릭에만 걸려 있던 갭 보강).
  formEl.addEventListener("submit", (event) => {
    event.preventDefault();
    search();
  });
}
