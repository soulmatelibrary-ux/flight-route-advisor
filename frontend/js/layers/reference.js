/**
 * 참조 레이어 6종 (FIR/TCA/항공로/픽스/공항/항행시설) 렌더 (docs/04 §6, F5).
 * 결정 포커스는 store.focusFirs/focusAirways만, 전세계/지역 컨텍스트는 store.bulk 전체.
 *
 * 04-F(겹침 폴리곤 채움) 이식: Leaflet Canvas 렌더러 기본 fillRule은 'evenodd'라 겹치는
 * FIR 멀티폴리곤이 상쇄돼 구멍이 생긴다(원본이 지적한 바로 그 버그) — fillRule:'nonzero' +
 * 멀티폴리곤 전체를 한 L.polygon(단일 패스)으로 넘기고, 링 방향을 shoelace로 통일해 해결한다.
 *
 * 명시적 단순화(완성본 04-A 커스텀 프리프로젝션 캔버스 엔진 대신 Leaflet 표준 캔버스/SVG
 * 렌더러 사용, docs/04-frontend-migration.md 결정 로그 참고): ±360 월드 랩 복제는 FIR에만
 * 적용(저비용, 247개)하고 항공로/픽스/공항/항행시설(도합 16.6만+)은 원 세계([-180,180])만
 * 그린다 — 결정 포커스(기본)는 이 범위 밖으로 나갈 일이 없고, 전세계 모드에서 antimeridian
 * 바로 옆으로 패닝하는 경우에만 공백이 생기는 코너케이스로 남긴다.
 *
 * 보안(리뷰 반영, 2026-07-22): popup/tooltip/divIcon html은 전부 innerHTML 삽입 경계라
 * escapeHtml을 거친다 — 이 레이어의 문자열은 사전빌드 참조 데이터라 공급망 오염 외에는
 * 실시간 변조 경로가 없지만, ADS-B/기상 레이어와 동일한 방어를 일관되게 적용한다.
 */
import { escapeHtml } from "../html.js";
import { normalizeWinding } from "../geo.js";

const L = window.L;

function shiftRing(ring, deltaLon) {
  return ring.map(([lat, lon]) => [lat, lon + deltaLon]);
}

export function createReferenceLayers(map, CONFIG) {
  const canvasRenderer = L.canvas({ padding: 0.4 });
  const groups = {
    firs: L.layerGroup(),
    tca: L.layerGroup(),
    airways: L.layerGroup(),
    waypoints: L.layerGroup(),
    airportsLow: L.layerGroup(),
    airportsAll: L.layerGroup(),
    navaids: L.layerGroup(),
  };

  function clear(name) {
    groups[name].clearLayers();
  }

  function renderFirs(firs) {
    clear("firs");
    for (const fir of firs) {
      const rings = fir.polygons.map((ring) => [normalizeWinding(ring)]);
      // ±360 복제(월드 랩) — FIR만(저비용, docs 06 §2.4 경도 연속화 전제)
      const allRings = [...rings, ...rings.map((poly) => poly.map((r) => shiftRing(r, 360))), ...rings.map((poly) => poly.map((r) => shiftRing(r, -360)))];
      const layer = L.polygon(allRings, {
        renderer: canvasRenderer,
        fillRule: "nonzero",
        color: CONFIG.tokens.inkSoft,
        weight: 1,
        fillColor: CONFIG.tokens.ink,
        fillOpacity: 0.04,
      });
      layer.on("mouseover", () => layer.setStyle({ fillOpacity: 0.16 }));
      layer.on("mouseout", () => layer.setStyle({ fillOpacity: 0.04 }));
      layer.bindPopup(`<b>${escapeHtml(fir.icao)}</b><br>${escapeHtml(fir.nameEn)}`);
      layer.addTo(groups.firs);
      if (fir.label) {
        L.marker([fir.label.lat, fir.label.lon], {
          icon: L.divIcon({ className: "ref-label fir-label", html: escapeHtml(fir.icao), iconSize: null }),
          interactive: false,
        }).addTo(groups.firs);
      }
    }
    updateLabelVisibility();
  }

  function renderTca(rows) {
    clear("tca");
    for (const t of rows) {
      L.polygon([t.polygon], {
        renderer: canvasRenderer,
        color: CONFIG.tokens.inkSoft,
        weight: 1,
        dashArray: "4,4",
        fill: false,
      })
        .bindTooltip(escapeHtml(t.nameKo), { permanent: true, direction: "center", className: "ref-label tca-label" })
        .addTo(groups.tca);
    }
    updateLabelVisibility();
  }

  function renderAirways(rows) {
    clear("airways");
    const labeled = new Set();
    for (const aw of rows) {
      L.polyline(aw.coords, { renderer: canvasRenderer, color: CONFIG.tokens.inkSoft, weight: 1, opacity: 0.7 }).addTo(
        groups.airways,
      );
      // 라벨은 항로명(ident)당 1개만(원본의 그리드 dedupe 대신 단순화, docs/04-frontend-migration.md 결정 로그)
      if (!labeled.has(aw.ident) && aw.seq === 0) {
        labeled.add(aw.ident);
        const mid = [(aw.coords[0][0] + aw.coords[1][0]) / 2, (aw.coords[0][1] + aw.coords[1][1]) / 2];
        L.marker(mid, {
          icon: L.divIcon({ className: "ref-label airway-label", html: escapeHtml(aw.ident), iconSize: null }),
          interactive: false,
        }).addTo(groups.airways);
      }
    }
    updateLabelVisibility();
  }

  function renderWaypoints(rows) {
    clear("waypoints");
    for (const wp of rows) {
      L.circleMarker(wp.latlng, {
        renderer: canvasRenderer,
        radius: 3,
        color: CONFIG.tokens.ink,
        weight: 1,
        fillColor: CONFIG.tokens.paper,
        fillOpacity: 1,
      })
        .bindTooltip(escapeHtml(wp.ident), { permanent: true, direction: "top", className: "ref-label wp-label" })
        .addTo(groups.waypoints);
    }
    updateLabelVisibility();
  }

  function renderNavaids(rows) {
    clear("navaids");
    for (const nv of rows) {
      L.marker(nv.latlng, {
        icon: L.divIcon({ className: "navaid-triangle", iconSize: [10, 10], iconAnchor: [5, 5] }),
      })
        .bindTooltip(escapeHtml(nv.ident), { permanent: true, direction: "right", className: "ref-label nv-label" })
        .addTo(groups.navaids);
    }
    updateLabelVisibility();
  }

  function renderAirports(rows) {
    clear("airportsLow");
    clear("airportsAll");
    const lowTypes = new Set(CONFIG.display.airportLowZoomTypes);
    for (const ap of rows) {
      const marker = L.circleMarker(ap.latlng, {
        renderer: canvasRenderer,
        radius: 4,
        color: CONFIG.tokens.ink,
        weight: 1,
        fillColor: CONFIG.tokens.ink,
        fillOpacity: 0.8,
      })
        .bindPopup(
          `<b>${escapeHtml(ap.icao)}</b> ${escapeHtml(ap.name)}<br>고도 ${escapeHtml(ap.elevFt)}ft<br><button data-weather-icao="${escapeHtml(ap.icao)}">공항 기상</button>`,
        )
        .bindTooltip(escapeHtml(ap.icao), { permanent: true, direction: "top", className: "ref-label ap-label" });
      marker.addTo(groups.airportsAll);
      if (lowTypes.has(ap.type)) marker.addTo(groups.airportsLow);
    }
    updateLabelVisibility();
  }

  function applyAirportZoomVisibility() {
    const showAll = map.getZoom() >= CONFIG.display.airportFullTypeZoom;
    if (showAll) {
      if (!map.hasLayer(groups.airportsAll)) map.addLayer(groups.airportsAll);
      map.removeLayer(groups.airportsLow);
    } else {
      if (!map.hasLayer(groups.airportsLow)) map.addLayer(groups.airportsLow);
      map.removeLayer(groups.airportsAll);
    }
  }
  map.on("zoomend", applyAirportZoomVisibility);

  function updateLabelVisibility() {
    const z = map.getZoom();
    const rules = [
      [".fir-label", CONFIG.display.labelZoom.fir],
      [".airway-label", CONFIG.display.labelZoom.airway],
      [".tca-label", CONFIG.display.labelZoom.tca],
      [".wp-label", CONFIG.display.labelZoom.fix],
      [".nv-label", CONFIG.display.labelZoom.navaid],
      [".ap-label", CONFIG.display.labelZoom.airportIcao],
    ];
    for (const [selector, threshold] of rules) {
      const show = z >= threshold;
      for (const el of document.querySelectorAll(selector)) {
        el.style.display = show ? "" : "none";
      }
    }
  }
  map.on("zoomend", updateLabelVisibility);
  map.whenReady(updateLabelVisibility);

  return {
    groups,
    canvasRenderer,
    renderFirs,
    renderTca,
    renderAirways,
    renderWaypoints,
    renderNavaids,
    renderAirports,
    applyAirportZoomVisibility,
    showFocus() {
      map.removeLayer(groups.airportsAll);
      map.addLayer(groups.airportsLow);
      for (const name of ["firs", "airways"]) map.addLayer(groups[name]);
      for (const name of ["tca", "waypoints", "navaids"]) map.removeLayer(groups[name]);
    },
    showBulk() {
      for (const name of ["firs", "tca", "airways", "waypoints", "navaids"]) map.addLayer(groups[name]);
      applyAirportZoomVisibility();
    },
  };
}
