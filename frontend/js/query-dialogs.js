/**
 * FOIS/흐름관리/ACDM 조회 팝업 3종의 열기/닫기만 담당한다(사용자 요청, 2026-07-24 —
 * 우측 패널 280px 폭에 폼이 늘어서 있어 좁고 무엇인지 안 보이는 문제를 상단바 아이콘
 * 버튼 + 중앙 팝업으로 분리해 해결). 조회 로직 자체는 fois-panel.js/
 * flow-management-panel.js/ops-panel.js가 그대로 담당한다 — 마크업만 <dialog> 안으로
 * 옮겨졌을 뿐 id는 그대로라 이 파일은 그 모듈들을 전혀 건드리지 않는다.
 */
const DIALOGS = [
  { trigger: "fois-open-btn", dialog: "fois-dialog", close: "fois-dialog-close" },
  { trigger: "flow-open-btn", dialog: "flow-dialog", close: "flow-dialog-close" },
  { trigger: "ops-open-btn", dialog: "ops-dialog", close: "ops-dialog-close" },
];

export function initQueryDialogs() {
  for (const { trigger, dialog, close } of DIALOGS) {
    const triggerBtn = document.getElementById(trigger);
    const dialogEl = document.getElementById(dialog);
    const closeBtn = document.getElementById(close);
    if (!triggerBtn || !dialogEl || !closeBtn) continue; // 마크업 없는 페이지(스모크 하네스 등)에서는 조용히 건너뜀

    triggerBtn.addEventListener("click", () => {
      if (!dialogEl.open) dialogEl.showModal(); // reasoning-panel.js와 동일 — 재호출 시 InvalidStateError 방지
    });
    closeBtn.addEventListener("click", () => dialogEl.close());
  }
}
