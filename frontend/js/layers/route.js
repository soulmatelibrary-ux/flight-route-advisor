/**
 * ROUTE 경로 지도 표시 (docs/03 §ROUTE 패널, F6). "전체"=모든 옵션 겹쳐보기(기본),
 * 옵션 선택 시 강조 + 경유 FIR 면(오렌지 10%, nonzero) + 출발/도착 배지.
 *
 * 명시적 단순화(docs/07-checklist.md Stage2 항목에 동기화): 최단 대비 "추가 구간만 빨강"
 * 세그먼트 diff, FIR 전환 화살표, ▶비행 애니메이션은 MVP DoD(경로추천 표시 자체)에는
 * 없는 부가 연출이라 이번 라운드에서는 생략 — 강조선(파랑, 굵게) + 정보 패널의 Δ소요(분)
 * 텍스트로 대체.
 */
const L = window.L;

export function createRouteLayers(map, CONFIG) {
  const group = L.layerGroup().addTo(map);
  const firHighlight = L.layerGroup().addTo(map);

  function clear() {
    group.clearLayers();
    firHighlight.clearLayers();
  }

  function coordsOf(opt) {
    return opt.fullRouteCoords.length > 0 ? opt.fullRouteCoords : opt.trackCoords;
  }

  function drawOption(opt, emphasize) {
    return L.polyline(coordsOf(opt), {
      color: emphasize ? CONFIG.tokens.blue : CONFIG.tokens.inkSoft,
      weight: emphasize ? 4 : 2,
      opacity: emphasize ? 0.95 : 0.45,
    }).addTo(group);
  }

  function highlightFirs(icaoList, firByIcao) {
    for (const icao of icaoList) {
      const fir = firByIcao.get(icao);
      if (!fir) continue;
      const rings = fir.polygons.map((ring) => [ring]);
      L.polygon(rings, {
        fillRule: "nonzero",
        color: CONFIG.tokens.orange,
        weight: 1,
        fillColor: CONFIG.tokens.orange,
        fillOpacity: 0.12,
      }).addTo(firHighlight);
    }
  }

  function addEndpointBadges(opt) {
    const coords = coordsOf(opt);
    const first = coords[0];
    const last = coords[coords.length - 1];
    if (first) {
      L.marker(first, { icon: L.divIcon({ className: "route-badge dep", html: "DEP", iconSize: null }) }).addTo(group);
    }
    if (last) {
      L.marker(last, { icon: L.divIcon({ className: "route-badge arr", html: "ARR", iconSize: null }) }).addTo(group);
    }
  }

  /** routeResult 전체를 selectedIndex(없으면 전체 겹쳐보기)에 맞춰 다시 그린다. */
  function render(routeResult, selectedIndex, firByIcao) {
    clear();
    if (!routeResult) return null;
    const options = routeResult.options;
    if (selectedIndex === null || selectedIndex === undefined) {
      for (const opt of options) drawOption(opt, false);
      return null;
    }
    const selected = options[selectedIndex];
    options.forEach((opt, idx) => drawOption(opt, idx === selectedIndex));
    highlightFirs(selected.enrouteFirs, firByIcao);
    addEndpointBadges(selected);
    return L.latLngBounds(coordsOf(selected));
  }

  return { group, firHighlight, render, clear };
}
