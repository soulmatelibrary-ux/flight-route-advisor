/**
 * 뷰모드 토글 3종 (docs/10-ui-and-realtime.md §2.1, F9). 모드 전환 시 참조 레이어
 * 표시범위를 전환하고 지도를 그 범위로 fit한다.
 *
 * 명시적 단순화: "지역 컨텍스트"(인천 FIR+인접 FIR)는 FIR 인접 그래프 계산 없이 인천 FIR
 * 주변 고정 bbox로 근사한다(docs/07-checklist.md Stage2 동기화 — 인접 FIR 그래프는 2단계
 * buildGeo(04-D)에서나 필요한 수준의 지오메트리 인접 판정이라 MVP 범위 밖).
 */
import { setViewMode, getState } from "./store.js";

const REGION_CONTEXT_BBOX = [
  [20, 110],
  [45, 145],
]; // 인천 FIR 인접 권역 근사

// 레이어 표시/숨김 자체는 main.js가 store 구독(renderForCurrentState)으로 처리한다 —
// 이 모듈은 지도 뷰(중심/줌/fitBounds)와 토글 버튼 상태만 맡는다.
export function initViewModeToggle(map, CONFIG, { onFocusEnter } = {}) {
  const buttons = [...document.querySelectorAll("#viewmode-toggle button")];

  function setActiveButton(mode) {
    for (const b of buttons) {
      const active = b.dataset.mode === mode;
      b.classList.toggle("active", active);
      b.setAttribute("aria-selected", String(active));
    }
  }

  async function applyMode(mode) {
    try {
      await setViewMode(mode);
    } catch {
      return; // store가 viewmode:error notify — 상위 구독자가 토스트 처리
    }
    if (mode === "focus") {
      const fit = onFocusEnter?.();
      if (!fit) map.setView(CONFIG.map.center, CONFIG.map.zoom);
    } else if (mode === "region") {
      map.fitBounds(REGION_CONTEXT_BBOX);
    } else {
      map.setView(CONFIG.map.center, CONFIG.map.zoom);
    }
    setActiveButton(mode);
  }

  for (const b of buttons) b.addEventListener("click", () => applyMode(b.dataset.mode));

  return { applyMode, currentMode: () => getState().viewMode };
}
