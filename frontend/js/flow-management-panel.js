/**
 * 흐름관리 조치 패널 (docs/03-backend-api.md §4.4, 2단계 착수). FOIS 패널(fois-panel.js)과
 * 동일하게 store.js 전역 상태와 무관한 독립 조회 도구 — 이 모듈 안에서만 조회 세대와
 * 페이지네이션(offset)을 관리한다. 비행편 영향 결합은 3단계 소관이라 이 목록은 조치
 * 자체만 보여준다(§4.4 각주).
 */
import { api, ApiError } from "./api.js";
import { toFlowManagementItem } from "./adapters.js";

const _IDENT_RE = /^[A-Za-z0-9]{1,10}$/;
const PAGE_SIZE = 50;

function describeError(err) {
  if (err instanceof ApiError) {
    return err.status === 0 ? "네트워크 연결 실패 — 오프라인이거나 서버가 응답하지 않음" : err.message;
  }
  return String(err?.message ?? err);
}

export function initFlowManagementPanel() {
  const formEl = document.getElementById("flow-form");
  const dateFromEl = document.getElementById("flow-date-from");
  const dateToEl = document.getElementById("flow-date-to");
  const firEl = document.getElementById("flow-fir");
  const airwayEl = document.getElementById("flow-airway");
  const summaryEl = document.getElementById("flow-summary");
  const listEl = document.getElementById("flow-items");
  const moreBtn = document.getElementById("flow-more-btn");
  const errorEl = document.getElementById("flow-error");

  if (!formEl) return; // 패널 마크업이 없는 페이지(스모크 하네스 등)에서는 조용히 건너뜀

  let seq = 0;
  let currentFilters = null;
  let loadedCount = 0;
  let total = 0;

  function showError(message) {
    errorEl.textContent = message;
    errorEl.hidden = !message;
  }

  function renderItem(rawItem) {
    const item = toFlowManagementItem(rawItem);
    const li = document.createElement("li");
    const row1 = document.createElement("div");
    row1.className = "row1";
    const targets = [item.targetFir, item.targetRoute, item.targetAirport, item.targetFix]
      .filter(Boolean)
      .join(" · ") || "-";
    row1.textContent = `${item.flowId ?? "-"} — ${targets}`;
    const row2 = document.createElement("div");
    row2.className = "row2";
    row2.textContent =
      `${item.applyStartDt ?? "-"} ~ ${item.applyEndDt ?? "-"}` +
      `${item.applyMinutes ? ` (${item.applyMinutes}분)` : ""} · ${item.restrictionSummary ?? "-"} · ${item.qualityStatus ?? "-"}`;
    li.append(row1, row2);
    listEl.appendChild(li);
  }

  function updateSummary() {
    summaryEl.textContent = total > 0 ? `총 ${total}건 중 ${loadedCount}건 표시` : "조회 결과 없음";
    moreBtn.hidden = loadedCount >= total;
  }

  async function loadPage(offset) {
    const mySeq = seq;
    const res = await api.flowManagement({ ...currentFilters, limit: PAGE_SIZE, offset });
    if (mySeq !== seq) return; // 더 최신 조회가 진행 중 — 이 응답은 폐기
    total = res.data.total;
    for (const item of res.data.items) renderItem(item);
    loadedCount += res.data.items.length;
    updateSummary();
  }

  async function search() {
    const firRaw = firEl.value.trim();
    const airwayRaw = airwayEl.value.trim();
    if (firRaw && !_IDENT_RE.test(firRaw)) {
      showError("대상 FIR은 영문·숫자 1~10자여야 함");
      return;
    }
    if (airwayRaw && !_IDENT_RE.test(airwayRaw)) {
      showError("대상 항공로는 영문·숫자 1~10자여야 함");
      return;
    }
    showError("");
    const mySeq = ++seq;
    currentFilters = {
      dateFrom: dateFromEl.value || undefined,
      dateTo: dateToEl.value || undefined,
      fir: firRaw ? firRaw.toUpperCase() : undefined,
      airway: airwayRaw ? airwayRaw.toUpperCase() : undefined,
    };
    loadedCount = 0;
    total = 0;
    summaryEl.textContent = "조회 중…";
    listEl.innerHTML = "";
    moreBtn.hidden = true;
    // 이전 "더 보기" 클릭이 아직 응답 대기 중이었다면 그 클릭의 finally가 자신의(오래된)
    // mySeq로만 disabled를 되돌리려다 seq가 이미 바뀌어 건너뛰는 경우가 있다 — 새 검색을
    // 시작하는 시점에 명시적으로 풀어 버튼이 영구히 비활성 상태로 남지 않게 한다
    // (리뷰 지적사항, 2026-07-23: seq 가드는 데이터 오염은 막지만 이 별도 UI 플래그까지
    // 커버하지 않았음).
    moreBtn.disabled = false;
    try {
      await loadPage(0);
    } catch (err) {
      if (mySeq !== seq) return;
      summaryEl.textContent = "";
      showError(describeError(err));
    }
  }

  formEl.addEventListener("submit", (event) => {
    event.preventDefault();
    search();
  });

  moreBtn.addEventListener("click", async () => {
    const mySeq = seq;
    moreBtn.disabled = true; // 응답이 오기 전 연타로 같은 offset을 중복 로드하는 것 방지
    try {
      await loadPage(loadedCount);
    } catch (err) {
      if (mySeq !== seq) return;
      showError(describeError(err));
    } finally {
      if (mySeq === seq) moreBtn.disabled = false;
    }
  });
}
