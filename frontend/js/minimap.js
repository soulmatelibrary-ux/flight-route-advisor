/**
 * 미니맵 (docs/10-ui-and-realtime.md §2.3, F10) — 전세계 상 현재 포커스 위치 표시.
 * 항상 세계 전체를 보여주는 고정 뷰 + 메인 지도 이동 시 사각형만 갱신(뷰 자체는 고정).
 */
const L = window.L;

export function initMinimap(mainMap, CONFIG) {
  const miniMap = L.map("minimap", {
    zoomControl: false,
    attributionControl: false,
    dragging: false,
    scrollWheelZoom: false,
    doubleClickZoom: false,
    boxZoom: false,
    keyboard: false,
    tap: false,
    worldCopyJump: false,
  }).setView(CONFIG.map.center, CONFIG.display.minimap.zoom);

  if (CONFIG.tileUrl) L.tileLayer(CONFIG.tileUrl).addTo(miniMap);

  const rect = L.rectangle(mainMap.getBounds(), { color: CONFIG.tokens.orange, weight: 1, fill: false }).addTo(miniMap);

  function sync() {
    rect.setBounds(mainMap.getBounds());
  }
  mainMap.on("moveend", sync);
  sync();

  return { map: miniMap, sync };
}
