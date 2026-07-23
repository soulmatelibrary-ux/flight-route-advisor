/**
 * ROUTE 경로 지도 표시 (docs/03 §ROUTE 패널, F6). "전체"=모든 옵션 겹쳐보기(기본),
 * 옵션 선택 시 강조 + 경유 FIR 면(오렌지 10%, nonzero) + 출발/도착 배지.
 *
 * 명시적 단순화(docs/07-checklist.md Stage2 항목에 동기화): 최단 대비 "추가 구간만 빨강"
 * 세그먼트 diff, FIR 전환 화살표, ▶비행 애니메이션은 MVP DoD(경로추천 표시 자체)에는
 * 없는 부가 연출이라 이번 라운드에서는 생략 — 강조선(파랑, 굵게) + 정보 패널의 Δ소요(분)
 * 텍스트로 대체.
 */
import { normalizeWinding, unwrapLongitudes, shiftRing } from "../geo.js";
import { escapeHtml } from "../html.js";

const L = window.L;

export function createRouteLayers(map, CONFIG) {
  const group = L.layerGroup().addTo(map);
  const firHighlight = L.layerGroup().addTo(map);
  // 우리나라 공항: 출발이면 SID(파랑), 도착이면 STAR(녹색) — 경로 선택 시 함께 표시
  // (사용자 요청, 2026-07-23; 원본 문서/08 §SS 색상 규약). main.js가 비동기로 채운다.
  const sidstar = L.layerGroup().addTo(map);

  function clear() {
    group.clearLayers();
    firHighlight.clearLayers();
    sidstar.clearLayers();
  }

  function renderSidStar(rows) {
    sidstar.clearLayers();
    for (const proc of rows) {
      const color = proc.proc === 1 ? CONFIG.tokens.blue : CONFIG.tokens.green;
      L.polyline(proc.coords, { color, weight: 2, opacity: 0.85 })
        .bindPopup(escapeHtml(proc.name))
        .addTo(sidstar);
      const start = proc.coords[0];
      if (start) {
        L.circleMarker(start, { radius: 3, color, weight: 1, fillColor: color, fillOpacity: 1 }).addTo(sidstar);
      }
    }
  }

  function coordsOf(opt) {
    return opt.fullRouteCoords.length > 0 ? opt.fullRouteCoords : opt.trackCoords;
  }

  // ODR2 기록 트랙은 공항 자체가 아니라 어딘가(이륙/착륙 후 레이더 포착 시작·종료) 지점부터
  // 시작·끝난다 — 그래서 DEP/ARR 배지가 실제 공항과 떨어진 바다 위에 떠 보인다는 지적
  // (사용자 피드백, 2026-07-23). 실제 공항 좌표를 알면 그 지점까지 직선으로 이어 붙인다.
  // 이 항공편이 실제로 어느 SID/STAR를 탔는지는 알 근거가 없어(여러 개 있을 수 있음)
  // 임의로 특정 절차를 골라 잇지 않는다(허위 정보 생성 금지 원칙) — SID/STAR는 별도
  // 레이어(sidstar)로 참고용으로만 같이 보여준다.
  function coordsWithAirports(opt, routeResult, airportByIcao) {
    const base = coordsOf(opt);
    const depAirport = airportByIcao?.get(routeResult.dep);
    const arrAirport = airportByIcao?.get(routeResult.arr);
    const coords = base.slice();
    if (depAirport) coords.unshift(depAirport.latlng);
    if (arrAirport) coords.push(arrAirport.latlng);
    // 미국↔한국처럼 날짜변경선을 넘는 노선은 원시 좌표가 보정 없이 점프해(-152→171 같은
    // 식) 최단(태평양)이 아니라 최장(유럽 경유) 직선으로 그려지는 문제(사용자 지적,
    // 2026-07-23) — 경도 연속화로 이어 붙인다.
    return unwrapLongitudes(coords);
  }

  function drawOption(opt, emphasize, routeResult, airportByIcao) {
    return L.polyline(coordsWithAirports(opt, routeResult, airportByIcao), {
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
      // 미국↔한국처럼 노선이 unwrapLongitudes로 연속좌표(±360 범위 밖)를 쓰게 되면, FIR은
      // 원래 -180~180 좌표라 서로 다른 "세계 사본"에 놓여 노선과 FIR 하이라이트 사이에
      // 큰 간격이 생긴다(사용자 지적, 2026-07-23) — reference.js의 FIR ±360 복제와 동일하게
      // 3벌 그려서 노선이 어느 사본으로 이어지든 맞아떨어지게 한다.
      const allRings = [
        ...rings,
        ...rings.map((poly) => poly.map((r) => shiftRing(r, 360))),
        ...rings.map((poly) => poly.map((r) => shiftRing(r, -360))),
      ];
      L.polygon(allRings, {
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

  function addEndpointBadges(opt, routeResult, airportByIcao) {
    const coords = coordsWithAirports(opt, routeResult, airportByIcao);
    const first = coords[0];
    const last = coords[coords.length - 1];
    if (first) {
      L.marker(first, { icon: L.divIcon({ className: "route-badge dep", html: "DEP", iconSize: null }) }).addTo(group);
    }
    if (last) {
      L.marker(last, { icon: L.divIcon({ className: "route-badge arr", html: "ARR", iconSize: null }) }).addTo(group);
    }
  }

  /** routeResult 전체를 selectedIndex(없으면 전체 겹쳐보기)에 맞춰 다시 그린다.
   * airportByIcao가 있으면 실제 공항 좌표까지 선을 이어 붙인다(위 coordsWithAirports). */
  function render(routeResult, selectedIndex, firByIcao, airportByIcao) {
    clear();
    if (!routeResult) return null;
    const options = routeResult.options;
    if (selectedIndex === null || selectedIndex === undefined) {
      for (const opt of options) drawOption(opt, false, routeResult, airportByIcao);
      return null;
    }
    const selected = options[selectedIndex];
    options.forEach((opt, idx) => drawOption(opt, idx === selectedIndex, routeResult, airportByIcao));
    highlightFirs(selected.enrouteFirs, firByIcao);
    addEndpointBadges(selected, routeResult, airportByIcao);
    return L.latLngBounds(coordsWithAirports(selected, routeResult, airportByIcao));
  }

  // 뷰모드 전환("지역/전세계" ↔ "결정 포커스") 시 지도를 선택된 경로에 맞추려고 bounds만
  // 다시 계산할 때 쓴다 — render()를 다시 부르면 clear()가 sidstar까지 지워버리는데, 이
  // 호출 경로(viewmode.js의 onFocusEnter)는 refreshSidStar를 다시 부르지 않아 SID/STAR가
  // 지워진 채로 안 돌아오는 버그가 있었다(리뷰 지적사항, 2026-07-23). 아무것도 다시
  // 그리지 않고 bounds 계산만 하므로 이 문제가 없다.
  function boundsFor(routeResult, selectedIndex, airportByIcao) {
    if (!routeResult || selectedIndex === null || selectedIndex === undefined) return null;
    const selected = routeResult.options[selectedIndex];
    return L.latLngBounds(coordsWithAirports(selected, routeResult, airportByIcao));
  }

  return { group, firHighlight, sidstar, render, clear, renderSidStar, boundsFor };
}
