/**
 * 경로 상세정보 슬라이드 드로어 (사용자 요청, 2026-07-24) — 왼쪽 ROUTE 패널(280px)이
 * 좁아 상층풍·섹터교통·병목신호 목록이 줄바꿈으로 뭉개져 가독성이 떨어진다는 피드백으로,
 * 이 세 패널(#route-wind/#sector-panel/#route-bottlenecks, DOM은 index.html에서
 * panel-left 밖으로 옮김)을 넓은 별도 드로어로 분리한다. 각 패널을 채우는
 * layers/wind.js·analyze-sectors.js·route-bottlenecks.js는 `document.getElementById`로
 * 독립적으로 요소를 찾으므로 DOM 위치만 옮겨도 기존 로직은 그대로 동작한다(무변경).
 *
 * 드로어는 경로 옵션이 실제로 선택됐을 때만 연다(main.js의 option:selected 핸들러가
 * state.selectedOptionIndex != null 분기에서 open(index), 그 반대(해제·"전체 겹쳐보기")에서
 * close() 호출) — 이 판단 자체는 이미 그 핸들러가 갖고 있으므로 이 모듈은 상태를 다시
 * 구독하지 않고 단순 open/close API만 제공한다. 닫기(×) 버튼은 경로 선택 자체를 해제하지
 * 않고 드로어만 숨긴다(순수 UI 토글).
 *
 * 재오픈 억제는 "닫았을 때의 경로 인덱스"로 판정한다(리뷰 지적, 2026-07-24) — 처음엔
 * 단순 boolean(manuallyClosed)이었으나, `selectOption()`이 다른 옵션 선택 시에도
 * null을 거치지 않고 selectedOptionIndex를 바로 갈아끼우므로(store.js) boolean은 "이번
 * 선택에서 닫았다"와 "이전에 닫아서 계속 억제 중"을 구분 못해 다른 경로를 다시 골라도
 * 영영 안 열리는 버그가 있었다. open(index)가 매번 인덱스를 받아, ×로 닫은 바로 그
 * 인덱스와 같을 때만 재오픈을 억제하고 인덱스가 달라지면(=다른 경로 선택) 정상 오픈한다.
 */
export function createRouteDetailDrawer() {
  const layoutEl = document.getElementById("layout");
  const drawerEl = document.getElementById("route-detail-drawer");
  const closeBtn = document.getElementById("route-detail-close");
  let currentIndex = null; // 마지막 open(index) 호출의 인덱스
  let closedForIndex = null; // ×로 닫은 시점의 인덱스(null=닫힘 억제 없음)

  function show() {
    drawerEl.hidden = false;
    layoutEl.classList.add("drawer-open");
  }

  function hide() {
    drawerEl.hidden = true;
    layoutEl.classList.remove("drawer-open");
  }

  closeBtn?.addEventListener("click", () => {
    closedForIndex = currentIndex;
    hide();
  });

  return {
    /** option:selected(선택 있음) 분기에서 호출 — 선택된 경로 인덱스를 그대로 전달. */
    open(index) {
      currentIndex = index;
      if (closedForIndex !== null && closedForIndex === index) return;
      show();
    },
    /** option:selected(해제) 분기에서 호출 — 다음 선택을 위해 억제 상태도 리셋. */
    close() {
      currentIndex = null;
      closedForIndex = null;
      hide();
    },
  };
}
