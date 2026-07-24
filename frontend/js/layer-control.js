/**
 * 그룹형 레이어 컨트롤 (사용자 요청 2026-07-23 — 참고 완성본처럼 "기본 항공정보/절차·공역/
 * 실시간·기상" 섹션으로 묶어서 표시). Leaflet 기본 `L.control.layers`는 overlay를 평면
 * 목록으로만 렌더링해 섹션 구분을 지원하지 않으므로(확인됨, docs/07-checklist.md 참고)
 * `L.Control`을 직접 확장한다.
 *
 * `L.Control.Layers`와의 호환성: 체크박스가 바뀔 때 `map.addLayer`/`removeLayer`를 직접
 * 호출하고, 그 뒤에 동일한 `overlayadd`/`overlayremove` 이벤트를 수동으로 발생시킨다 —
 * main.js의 SIGMET/PIREP 온디맨드 조회(`map.on("overlayadd", ...)`)가 컨트롤 종류와
 * 무관하게 그대로 동작하게 하기 위함(Leaflet 기본 컨트롤이 내부적으로 하는 것과 동일).
 *
 * item.layer가 없고 item.onChange만 있는 항목(예: 공항 줌연동 토글, 실시간 항공기
 * STCA/CPA처럼 map.addLayer로 표현 안 되는 계산 오버레이)도 지원한다 — 이 경우
 * addLayer/removeLayer·overlayadd/overlayremove를 생략하고 onChange(checked)만 호출한다.
 */
import { escapeHtml } from "./html.js";

const L = window.L;

export function createGroupedLayerControl(map, sections) {
  const control = L.control({ position: "bottomright" });

  control.onAdd = function () {
    const container = L.DomUtil.create("div", "leaflet-control layer-control");
    L.DomEvent.disableClickPropagation(container);
    L.DomEvent.disableScrollPropagation(container);

    const title = L.DomUtil.create("div", "layer-control-title", container);
    title.textContent = "레이어";

    for (const section of sections) {
      const sectionEl = L.DomUtil.create("div", "layer-control-section", container);
      const header = L.DomUtil.create("div", "layer-control-header", sectionEl);
      header.innerHTML = `<span class="layer-control-arrow" aria-hidden="true">▾</span>${escapeHtml(section.title)}`;
      const body = L.DomUtil.create("div", "layer-control-body", sectionEl);
      header.addEventListener("click", () => sectionEl.classList.toggle("collapsed"));

      for (const item of section.items) {
        const label = L.DomUtil.create("label", "layer-control-item", body);
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        const initiallyOn = item.layer ? map.hasLayer(item.layer) : Boolean(item.checked);
        checkbox.checked = initiallyOn;
        checkbox.addEventListener("change", () => {
          if (item.layer) {
            if (checkbox.checked) {
              map.addLayer(item.layer);
              map.fire("overlayadd", { layer: item.layer, name: item.label });
            } else {
              map.removeLayer(item.layer);
              map.fire("overlayremove", { layer: item.layer, name: item.label });
            }
          }
          item.onChange?.(checkbox.checked);
        });
        label.appendChild(checkbox);
        label.appendChild(document.createTextNode(item.label));
      }
    }

    return container;
  };

  control.addTo(map);
  return control;
}
