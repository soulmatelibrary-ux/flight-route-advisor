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
import { normalizeWinding, shiftRing } from "../geo.js";

const L = window.L;

export function createReferenceLayers(map, CONFIG, hooks = {}) {
  const { onFirClick } = hooks;
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

  // 그룹형 레이어 컨트롤 체크박스로 firs/tca/airways/waypoints/navaids를 껐다 켤 수 있게
  // 됐는데(사용자 요청 2026-07-23), showFocus()/showBulk()가 경로 선택·뷰모드 전환마다
  // 이 그룹들을 무조건 다시 addLayer해 체크박스로 꺼둔 상태가 도로 켜지는 회귀가 있었다
  // (리뷰 지적 — 처음엔 TCA만 개별 방어했으나 나머지도 동일 문제라 일반화). 이 맵을 그룹
  // on/off의 단일 출처로 두고, showFocus/showBulk/부팅 시 초기화 모두 이걸 참조한다.
  // 기본값(true 3개+false tca)은 기존 부팅 동작과 동일 — main.js가 하던 개별 addTo 루프를
  // 여기로 옮겼다.
  const enabledByName = { firs: true, tca: false, airways: true, waypoints: true, navaids: true };

  function setGroupEnabled(name, enabled) {
    enabledByName[name] = enabled;
    if (enabled) map.addLayer(groups[name]);
    else map.removeLayer(groups[name]);
  }

  function isGroupEnabled(name) {
    return enabledByName[name];
  }

  function applyEnabledGroups(names) {
    for (const name of names) {
      if (enabledByName[name]) map.addLayer(groups[name]);
      else map.removeLayer(groups[name]);
    }
  }

  applyEnabledGroups(Object.keys(enabledByName));

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
      // 지역컨텍스트에서 홈 FIR·경로 FIR 바깥은 항로/픽스가 기본적으로 안 보이는데(위
      // relevantFirBounds 설계), 사용자가 특정 FIR을 직접 클릭해 살펴보고 싶을 수 있다
      // (사용자 피드백, 2026-07-23) — 클릭한 FIR은 main.js가 "고정(pinned)"으로 기억해
      // 그 FIR도 항로/픽스 필터 범위에 포함시킨다.
      if (onFirClick) layer.on("click", () => onFirClick(fir.icao));
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
        .bindPopup(escapeHtml(t.nameKo))
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

  // 픽스/항행시설/공항 마커 크기·색상: 전세계/지역 컨텍스트에서 개수가 많아(픽스 800·
  // 항행시설 수천·공항 10,030) 진한 ink 톤 + 원래 크기가 너무 눈에 띈다는 피드백(2026-07-23)
  // 으로 크기 절반 + inkSoft(옅은 톤)로 낮춤. 결정 포커스는 tca/navaids가 항상 빈 배열이라
  // 영향 없지만, waypoints는 경로 스코프 픽스가 실제로 표시된다(showFocus() 참고).
  function renderWaypoints(rows) {
    clear("waypoints");
    for (const wp of rows) {
      // 외국 픽스는 우리나라보다 더 작게(사용자 피드백, 2026-07-23) — main.js가 이미
      // 우리나라+관련 FIR로 걸러서 넘기므로 여기선 크기만 구분한다.
      const isHome = wp.country === CONFIG.display.homeWaypointCountry;
      L.circleMarker(wp.latlng, {
        renderer: canvasRenderer,
        radius: isHome ? CONFIG.display.waypointRadius.home : CONFIG.display.waypointRadius.foreign,
        color: CONFIG.tokens.inkSoft,
        weight: 1,
        fillColor: CONFIG.tokens.paper,
        fillOpacity: 1,
      })
        // 클릭 팝업 대신 호버 툴팁(사용자 요청, 2026-07-23) — permanent:true가 아니라
        // 마우스가 올라간 마커 1개에서만 DOM이 생기므로, 이 파일 위 §180 주석의 permanent
        // 툴팁 성능 문제(줌 3~5·다량 마커에서 상시 DOM)와는 다르다.
        .bindTooltip(`<b>${escapeHtml(wp.ident)}</b><br>${wp.lat.toFixed(4)}, ${wp.lon.toFixed(4)}`, {
          direction: "top",
          offset: [0, -4],
        })
        .addTo(groups.waypoints);
    }
    updateLabelVisibility();
  }

  function renderNavaids(rows) {
    clear("navaids");
    for (const nv of rows) {
      L.marker(nv.latlng, {
        icon: L.divIcon({ className: "navaid-triangle", iconSize: [5, 5], iconAnchor: [2.5, 2.5] }),
      })
        .bindPopup(escapeHtml(nv.ident))
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
        radius: 2,
        color: CONFIG.tokens.inkSoft,
        weight: 1,
        fillColor: CONFIG.tokens.inkSoft,
        fillOpacity: 0.8,
      })
        .bindPopup(
          `<b>${escapeHtml(ap.icao)}</b> ${escapeHtml(ap.name)}<br>고도 ${escapeHtml(ap.elevFt)}ft<br><button data-weather-icao="${escapeHtml(ap.icao)}">공항 기상</button>`,
        );
      marker.addTo(groups.airportsAll);
      if (lowTypes.has(ap.type)) marker.addTo(groups.airportsLow);
    }
    updateLabelVisibility();
  }

  // 공항 레이어는 줌에 따라 airportsLow/airportsAll을 자동으로 swap하는 자체 로직이라
  // Leaflet의 단순 add/removeLayer 체크박스로는 표현이 안 된다 — 그룹형 레이어 컨트롤에
  // "공항" 항목을 추가해달라는 요청(2026-07-23)으로 이 on/off 플래그를 신설, 꺼져 있으면
  // 줌이 바뀌어도 두 그룹 다 지도에서 뺀다.
  let airportsEnabled = true;
  function applyAirportZoomVisibility() {
    if (!airportsEnabled) {
      map.removeLayer(groups.airportsAll);
      map.removeLayer(groups.airportsLow);
      return;
    }
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
  applyAirportZoomVisibility(); // 초기 상태 반영(main.js가 하던 개별 addTo 루프 대체, 2026-07-23)
  function setAirportsEnabled(enabled) {
    airportsEnabled = enabled;
    applyAirportZoomVisibility();
  }

  // TCA/픽스/항행시설/공항의 permanent 툴팁은 성능 문제(줌 3~5, 항로 89,555·공항 10,030
  // 규모에서 페이지 응답 없음 발생, 2026-07-23)로 제거했다 — 툴팁은 항상 열려 있는 DOM
  // 노드라 패닝/줌마다 위치 재계산 비용이 개수에 비례해 쌓인다. FIR·항로 라벨은
  // interactive:false 정적 divIcon(개수가 작음: FIR 247·항로는 ident당 1개로 dedupe)이라
  // 유지한다. 나머지는 bindPopup으로 대체해 클릭했을 때만 DOM이 생기도록 했다.
  function updateLabelVisibility() {
    const z = map.getZoom();
    const rules = [
      [".fir-label", CONFIG.display.labelZoom.fir],
      [".airway-label", CONFIG.display.labelZoom.airway],
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
      // "공항" 레이어 컨트롤 체크박스가 꺼져 있으면(2026-07-23 추가) 뷰모드 전환으로
      // 되살아나지 않게 한다 — airportsEnabled일 때만 low-detail 세트를 켠다.
      if (airportsEnabled) map.addLayer(groups.airportsLow);
      else map.removeLayer(groups.airportsLow);
      // waypoints는 2026-07-23 focusWaypoints 추가 이후 실제 경로 스코프 픽스 데이터가
      // 들어오는데도(main.js renderForCurrentState) 이 목록이 그대로 남아 있어 결정
      // 포커스에서 항상 숨겨지던 버그(사용자 제보) — tca/navaids는 focus에서 여전히 빈
      // 배열만 넘어오므로(renderTca([])·renderNavaids([])) 체크박스와 무관하게 계속 숨긴다.
      // firs/airways/waypoints는 체크박스 상태(enabledByName)를 존중한다(리뷰 지적 — 예전엔
      // 무조건 addLayer해 껐다 켠 상태가 뷰모드 전환마다 되살아났음).
      applyEnabledGroups(["firs", "airways", "waypoints"]);
      for (const name of ["tca", "navaids"]) map.removeLayer(groups[name]);
    },
    showBulk() {
      // 전부 체크박스 상태(enabledByName)를 존중한다(리뷰 지적, 2026-07-23 — 처음엔 TCA만
      // 개별 방어했으나 firs/항공로/픽스/항행시설도 뷰모드 전환마다 무조건 addLayer돼
      // 체크박스로 꺼둔 상태가 도로 켜지는 동일한 문제가 있었음).
      applyEnabledGroups(["firs", "tca", "airways", "waypoints", "navaids"]);
      applyAirportZoomVisibility();
    },
    setAirportsEnabled,
    setGroupEnabled,
    isGroupEnabled,
  };
}
