/**
 * ROUTE 경로 지도 표시 (docs/03 §ROUTE 패널, F6). "전체"=모든 옵션 겹쳐보기(기본),
 * 옵션 선택 시 강조 + 경유 FIR 면(오렌지 10%, nonzero) + 출발/도착 배지.
 *
 * 명시적 단순화(docs/07-checklist.md Stage2 항목에 동기화): 최단 대비 "추가 구간만 빨강"
 * 세그먼트 diff, FIR 전환 화살표, ▶비행 애니메이션은 MVP DoD(경로추천 표시 자체)에는
 * 없는 부가 연출이라 이번 라운드에서는 생략 — 강조선(파랑, 굵게) + 정보 패널의 Δ소요(분)
 * 텍스트로 대체.
 */
import { normalizeWinding } from "../geo.js";
import { escapeHtml } from "../html.js";

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
      // 04-F(겹침 폴리곤 채움) 이식: nonzero만으로는 부족 — reference.js와 동일하게 링 방향 통일
      const rings = fir.polygons.map((ring) => [normalizeWinding(ring)]);
      L.polygon(rings, {
        fillRule: "nonzero",
        color: CONFIG.tokens.orange,
        weight: 1,
        // 출발/도착 FIR처럼 노선이 스치듯만 지나가는 큰 FIR은 화면 가장자리에서 옅은
        // 색이 눈에 잘 안 띈다는 피드백(2026-07-23) — 투명도를 올려 가시성 확보
        fillOpacity: 0.22,
      })
        // 팝업이 없으면 "실제로 칠해지는지" 클릭으로 검증할 방법이 없었다 — reference.js
        // 기본 FIR 레이어와 동일하게 붙여 진단 가능하게 함
        .bindPopup(`<b>${escapeHtml(fir.icao)}</b><br>${escapeHtml(fir.nameEn)}`)
        .addTo(firHighlight);
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
