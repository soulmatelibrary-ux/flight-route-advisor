/**
 * 부트스트랩 (docs/04-frontend-migration.md §3.1 초기 부트 순서, F1~F10 결선).
 */
import { loadConfig, getConfig } from "./config.js";
import { getState, subscribe, bootMinimal } from "./store.js";
import { createReferenceLayers } from "./layers/reference.js";
import { createRouteLayers } from "./layers/route.js";
import { createAdsbLayer } from "./layers/adsb.js";
import { bindAirportWeatherButtons } from "./weather.js";
import { initRoutePanel } from "./route-panel.js";
import { initViewModeToggle } from "./viewmode.js";
import { initMinimap } from "./minimap.js";

const L = window.L;

function applyDesignTokens(CONFIG) {
  const root = document.documentElement.style;
  for (const [key, value] of Object.entries(CONFIG.tokens)) {
    root.setProperty(`--${key.replace(/([A-Z])/g, "-$1").toLowerCase()}`, value);
  }
}

function toast(message) {
  const root = document.getElementById("toast-root");
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = message;
  root.appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

function renderFirChain(routeResult, selectedIndex) {
  const el = document.getElementById("fir-chain");
  if (!routeResult || selectedIndex == null) {
    el.textContent = "경로를 선택하면 경유 FIR 체인이 표시됩니다.";
    el.classList.add("muted");
    return;
  }
  el.classList.remove("muted");
  const opt = routeResult.options[selectedIndex];
  el.innerHTML = opt.enrouteFirs.map((icao) => `<span class="fir-badge">${icao}</span>`).join('<span aria-hidden="true">→</span>');
}

function updateCounts(state) {
  const el = document.getElementById("counts");
  if (state.bulk) {
    el.textContent = `FIR ${state.bulk.firs.length} · 항로 ${state.bulk.airways.length} · 공항 ${state.bulk.airports.length}`;
  } else {
    el.textContent = `OD ${state.odPairs.length}`;
  }
}

async function main() {
  const CONFIG = await loadConfig();
  applyDesignTokens(CONFIG);

  const map = L.map("map", {
    center: CONFIG.map.center,
    zoom: CONFIG.map.zoom,
    minZoom: CONFIG.map.minZoom,
    maxBounds: CONFIG.map.maxBounds,
    preferCanvas: true,
    worldCopyJump: false,
  });

  if (CONFIG.tileUrl) {
    L.tileLayer(CONFIG.tileUrl, { maxZoom: 19 }).addTo(map);
  }

  const referenceLayers = createReferenceLayers(map, CONFIG);
  for (const group of Object.values(referenceLayers.groups)) group.addTo(map);
  const routeLayers = createRouteLayers(map, CONFIG);
  const adsb = createAdsbLayer(map, CONFIG);
  adsb.group.addTo(map);

  L.control.layers(null, {
    "전 세계 FIR": referenceLayers.groups.firs,
    "접근관제구역(TCA)": referenceLayers.groups.tca,
    항공로: referenceLayers.groups.airways,
    "항로 픽스": referenceLayers.groups.waypoints,
    항행시설: referenceLayers.groups.navaids,
    "실시간 항공기": adsb.group,
  }, { position: "bottomright" }).addTo(map);

  bindAirportWeatherButtons(map);
  initRoutePanel();
  initMinimap(map, CONFIG);

  function fitToSelectedRoute() {
    const state = getState();
    if (!state.routeResult || state.selectedOptionIndex == null) return false;
    const bounds = routeLayers.render(state.routeResult, state.selectedOptionIndex, state.derived.firByIcao);
    if (bounds) map.fitBounds(bounds, { padding: [40, 40] });
    return true;
  }

  initViewModeToggle(map, CONFIG, { onFocusEnter: fitToSelectedRoute });

  function renderForCurrentState() {
    const state = getState();
    if (state.viewMode === "focus") {
      referenceLayers.renderFirs(state.focusFirs);
      referenceLayers.renderAirways(state.focusAirways);
      referenceLayers.renderTca([]);
      referenceLayers.renderWaypoints([]);
      referenceLayers.renderNavaids([]);
      referenceLayers.renderAirports(state.bootAirports);
      referenceLayers.showFocus();
    } else if (state.bulk) {
      referenceLayers.renderFirs(state.bulk.firs);
      referenceLayers.renderTca(state.bulk.tca);
      referenceLayers.renderAirways(state.bulk.airways);
      referenceLayers.renderWaypoints(state.bulk.waypoints);
      referenceLayers.renderNavaids(state.bulk.navaids);
      referenceLayers.renderAirports(state.bulk.airports);
      referenceLayers.showBulk();
    }
    updateCounts(state);
  }

  subscribe((state, event) => {
    if (event.type === "boot:error" || event.type === "od:error" || event.type === "viewmode:error") {
      toast(event.message);
    }
    if (event.type === "boot:ok") {
      referenceLayers.renderAirports(state.bootAirports);
      referenceLayers.showFocus();
      updateCounts(state);
    }
    if (event.type === "od:selected" || event.type === "option:selected") {
      renderForCurrentState();
      routeLayers.render(state.routeResult, state.selectedOptionIndex, state.derived.firByIcao);
      renderFirChain(state.routeResult, state.selectedOptionIndex);
      if (state.viewMode === "focus" && state.selectedOptionIndex != null) fitToSelectedRoute();
    }
    if (event.type === "viewmode:changed") {
      renderForCurrentState();
    }
  });

  const chipEl = document.getElementById("adsb-chip");
  adsb.start(chipEl);

  try {
    await bootMinimal();
  } catch (err) {
    toast(`초기 데이터 로드 실패: ${err.message}`);
  }
}

main().catch((err) => {
  console.error(err);
  toast(`초기화 실패: ${err.message}`);
});
