/**
 * "AI 근거 보기" 팝업 (C2, docs/13-ai-reasoning-dev-plan.md STEP C2, D1 수동복붙 모드).
 *
 * 흐름: 트리거 버튼(선택된 경로가 있을 때만 노출, 다른 route-* 위젯과 동일하게 store.js의
 * od:selected/option:selected만 구독하는 독립 위젯) → 클릭 시 이미 계산된 신호(A1~A7,
 * windLayer/sectorPanel/bottlenecksPanel의 getter)를 모아 reasoningContext(B2)를 조립하고
 * 프롬프트(C1)를 만들어 보여준다 → 사용자가 그 프롬프트를 외부 AI에 복붙하고 받은 JSON
 * 응답을 다시 붙여넣으면 파싱해 팝업에 렌더한다.
 *
 * 이 모듈은 AI를 호출하지 않는다(D1은 수동 복붙, 자동 호출은 C4 — 아직 비활성). 붙여넣은
 * 응답은 신뢰 못 할 입력이라 `reasoning-response.js`(C3)의 `validateReasoningResponse()`로
 * 필드·타입·길이 상한을 전부 검증한 뒤에만 렌더하고, DOM 삽입은 textContent만 쓴다(이
 * 저장소의 기존 위젯 전부와 동일한 기본 방어).
 */
import { getState, subscribe } from "./store.js";
import { api, ApiError } from "./api.js";
import { getMetar } from "./weather.js";
import { buildReasoningContext } from "./reasoning-context.js";
import { loadPromptTemplate, buildPrompt } from "./reasoning-prompt.js";
import { isRawTooLong, validateReasoningResponse } from "./reasoning-response.js";

function pad(n) {
  return String(n).padStart(2, "0");
}

/** 현재 시각 → KST ISO 문자열(§7 `generated_at_kst`, 예: "2026-07-24T09:00:00+09:00"). */
function nowKstIso() {
  const kstMillis = Date.now() + 9 * 3600 * 1000;
  const d = new Date(kstMillis);
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}+09:00`;
}

function describeError(err) {
  if (err instanceof ApiError) return err.status === 0 ? "네트워크 연결 실패" : err.message;
  return String(err?.message ?? err);
}

export function initReasoningPanel(CONFIG, { windLayer, sectorPanel, bottlenecksPanel }) {
  const triggerBtn = document.getElementById("reasoning-open-btn");
  const dialogEl = document.getElementById("reasoning-dialog");
  if (!triggerBtn || !dialogEl) return; // 마크업 없는 페이지(스모크 하네스 등) — 조용히 건너뜀

  const closeBtn = document.getElementById("reasoning-close-btn");
  const promptTextEl = document.getElementById("reasoning-prompt-text");
  const copyBtn = document.getElementById("reasoning-copy-btn");
  const copyStatusEl = document.getElementById("reasoning-copy-status");
  const responseInputEl = document.getElementById("reasoning-response-input");
  const applyBtn = document.getElementById("reasoning-apply-btn");
  const parseErrorEl = document.getElementById("reasoning-parse-error");
  const resultEl = document.getElementById("reasoning-result");
  const resultWhyEl = document.getElementById("reasoning-result-why");
  const resultBottlenecksEl = document.getElementById("reasoning-result-bottlenecks");
  const resultCaveatsEl = document.getElementById("reasoning-result-caveats");
  const resultNoticeEl = document.getElementById("reasoning-result-notice");

  let openGen = 0; // 오픈 세대 토큰(openDialog 참고) — close→다른 경로 선택→재오픈 경쟁조건 방지

  function resetDialogBody() {
    promptTextEl.value = "";
    copyStatusEl.textContent = "";
    responseInputEl.value = "";
    parseErrorEl.hidden = true;
    parseErrorEl.textContent = "";
    resultEl.hidden = true;
    resultWhyEl.textContent = "";
    resultBottlenecksEl.textContent = "";
    resultCaveatsEl.textContent = "";
    resultNoticeEl.hidden = true;
    resultNoticeEl.textContent = "";
  }

  function showParseError(message) {
    parseErrorEl.textContent = message;
    parseErrorEl.hidden = false;
  }

  /**
   * @param {{why: string, bottlenecks: Array, caveats: string[]}} value - validateReasoningResponse()가
   *   이미 필드·타입·길이 상한을 전부 검증·정제한 값(reasoning-response.js, C3) — 여기서는 그대로
   *   신뢰해 textContent로만 렌더한다(innerHTML 금지, CLAUDE.md §3).
   * @param {{whyTruncated: boolean, droppedBottlenecks: number, droppedCaveats: number}} meta - 드롭·절단
   *   여부(리뷰 지적, 2026-07-24 — "일부만 표시됨"을 조용히 감추지 않고 알린다. 원문을 다시 노출하지
   *   않으므로 신뢰 못 할 입력을 되풀이 렌더하는 것도 아니다).
   */
  function renderResult(value, meta) {
    // 이전 apply()에서 남은 알림을 먼저 지운다 — 안 그러면 "드롭 있었음" 알림 뒤에 깨끗한
    // 응답을 다시 적용해도 알림이 그대로 남는다(리뷰 재검증 중 실제로 재현·발견한 버그,
    // resetDialogBody()는 다이얼로그를 "열 때"만 호출돼 같은 세션 내 재적용에는 안 걸림).
    resultNoticeEl.hidden = true;
    resultNoticeEl.textContent = "";

    resultWhyEl.textContent = meta.whyTruncated ? `${value.why}…` : value.why;

    resultBottlenecksEl.textContent = "";
    for (const item of value.bottlenecks) {
      const li = document.createElement("li");
      li.textContent = item.reason ? `${item.seg} — ${item.reason}` : item.seg;
      li.classList.add(`bottleneck-${item.severity}`);
      resultBottlenecksEl.append(li);
    }

    resultCaveatsEl.textContent = "";
    for (const c of value.caveats) {
      const li = document.createElement("li");
      li.textContent = c;
      resultCaveatsEl.append(li);
    }

    const notices = [];
    if (meta.whyTruncated) notices.push("근거 문장이 길어 일부만 표시했습니다.");
    if (meta.droppedBottlenecks > 0) notices.push(`병목 항목 ${meta.droppedBottlenecks}건은 형식이 맞지 않거나 개수 상한을 넘어 표시되지 않았습니다.`);
    if (meta.droppedCaveats > 0) notices.push(`유의사항 ${meta.droppedCaveats}건은 형식이 맞지 않거나 개수 상한을 넘어 표시되지 않았습니다.`);
    if (notices.length > 0) {
      resultNoticeEl.textContent = notices.join(" ");
      resultNoticeEl.hidden = false;
    }

    resultEl.hidden = false;
  }

  async function buildContextForCurrentSelection() {
    const state = getState();
    const { flow, bottlenecks } = bottlenecksPanel.getSignals();
    const wind = windLayer.getRecommendation();
    const sectorDemand = sectorPanel.getDemand();

    const [delayHistoryOutcome, metarRows] = await Promise.allSettled([
      api.delayHistory(state.dep, state.arr, null),
      getMetar(`${state.dep},${state.arr}`),
    ]);
    const delayHistory = delayHistoryOutcome.status === "fulfilled" ? delayHistoryOutcome.value.data : null;
    const rows = metarRows.status === "fulfilled" ? metarRows.value : [];
    const metar = {
      dep: rows.find((r) => r.icaoId === state.dep) ?? null,
      arr: rows.find((r) => r.icaoId === state.arr) ?? null,
    };

    return buildReasoningContext({
      dep: state.dep,
      arr: state.arr,
      totalFlights: state.routeResult?.totalFlights ?? null,
      routeOptions: state.routeResult?.options ?? null,
      selectedIndex: state.selectedOptionIndex,
      flow,
      delayHistory,
      wind,
      sectorDemand,
      bottlenecks,
      metar,
      windConfig: CONFIG.wind,
      hour: null, // 시간대 선택 UI 없음(레거시 rpHr 대응 UI 미구현) — 항상 미지정
      nowKst: nowKstIso(),
    });
  }

  async function openDialog() {
    // 닫기(허용된 유일한 탈출구)→다른 경로 선택→재오픈이 빠르게 일어나면, 이전 오픈의
    // buildContextForCurrentSelection()/loadPromptTemplate()이 늦게 끝나며 방금 새로 연
    // 프롬프트를 덮어쓸 수 있었다(리뷰 지적, 2026-07-24 — 이 저장소의 다른 모든 비동기
    // 흐름(store.js/main.js의 seq 토큰들)과 동일한 종류의 문제라 동일 패턴으로 방어).
    const myGen = ++openGen;
    resetDialogBody();
    if (!dialogEl.open) dialogEl.showModal(); // 이미 열려 있으면 재호출 시 InvalidStateError 방지
    promptTextEl.value = "프롬프트 생성 중…";
    try {
      const [context, template] = await Promise.all([buildContextForCurrentSelection(), loadPromptTemplate()]);
      if (myGen !== openGen) return; // 더 최신 오픈이 진행 중 — 이 응답은 폐기
      const built = buildPrompt(template, context);
      promptTextEl.value = built.combined;
    } catch (err) {
      if (myGen !== openGen) return;
      promptTextEl.value = `프롬프트 생성 실패 — ${describeError(err)}`;
    }
  }

  triggerBtn.addEventListener("click", openDialog);
  closeBtn.addEventListener("click", () => dialogEl.close());

  copyBtn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(promptTextEl.value);
      copyStatusEl.textContent = "복사됨";
    } catch {
      // Clipboard API 미가용(비보안 컨텍스트 등) — 텍스트를 선택해 수동 복사(Ctrl/Cmd+C)할 수 있게 함
      promptTextEl.select();
      copyStatusEl.textContent = "자동 복사 실패 — 선택된 텍스트를 직접 복사(Ctrl/Cmd+C)하세요";
    }
  });

  applyBtn.addEventListener("click", () => {
    parseErrorEl.hidden = true;
    resultEl.hidden = true;
    const raw = responseInputEl.value.trim();
    if (!raw) {
      showParseError("응답을 붙여넣어 주세요.");
      return;
    }
    if (isRawTooLong(raw, CONFIG.reasoning)) {
      showParseError(`응답이 너무 깁니다(최대 ${CONFIG.reasoning.responseMaxRawLen.toLocaleString()}자) — AI 응답만 붙여넣었는지 확인하세요.`);
      return;
    }
    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch {
      showParseError("JSON 형식이 아닙니다 — AI 응답 전체를 그대로 붙여넣었는지 확인하세요.");
      return;
    }
    const result = validateReasoningResponse(parsed, CONFIG.reasoning);
    if (!result.ok) {
      showParseError(result.error);
      return;
    }
    renderResult(result.value, result.meta);
  });

  function updateTriggerVisibility(state) {
    triggerBtn.hidden = !(state.dep && state.arr && state.selectedOptionIndex != null && state.routeResult);
  }

  subscribe((state, event) => {
    if (event.type === "od:selected" || event.type === "option:selected") updateTriggerVisibility(state);
  });
}
