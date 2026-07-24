/**
 * 부트스트랩 (docs/04-frontend-migration.md §3.1 초기 부트 순서, F1~F10 결선).
 */
import { loadConfig } from "./config.js";
import { getState, subscribe, bootMinimal } from "./store.js";
import { escapeHtml } from "./html.js";
import { createReferenceLayers } from "./layers/reference.js";
import { createRouteLayers } from "./layers/route.js";
import { createWindLayer } from "./layers/wind.js";
import { createAdsbLayer } from "./layers/adsb.js";
import { createSectorPanel } from "./analyze-sectors.js";
import { createBottlenecksPanel } from "./route-bottlenecks.js";
import { createHazardLayers } from "./layers/hazards.js";
import { createRadarLayer } from "./layers/radar.js";
import { createGroupedLayerControl } from "./layer-control.js";
import { bindAirportWeatherButtons, getSigmets, getPireps } from "./weather.js";
import { initRoutePanel } from "./route-panel.js";
import { initFoisPanel } from "./fois-panel.js";
import { initFlowManagementPanel } from "./flow-management-panel.js";
import { initRouteFoisSummary } from "./route-fois-summary.js";
import { initRouteOpsSummary } from "./route-ops-summary.js";
import { initRouteFlowSummary } from "./route-flow-summary.js";
import { initOpsPanel } from "./ops-panel.js";
import { initViewModeToggle } from "./viewmode.js";
import { initMinimap } from "./minimap.js";
import { boundsOfPolygons, pointInBounds, unionBounds } from "./geo.js";
import { api } from "./api.js";
import { toWaypoint, toSidStar } from "./adapters.js";

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
  el.innerHTML = opt.enrouteFirs
    .map((icao) => `<span class="fir-badge">${escapeHtml(icao)}</span>`)
    .join('<span aria-hidden="true">→</span>');
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

  // 지역컨텍스트에서 클릭으로 "고정"한 FIR(홈 FIR·경로 FIR 외 추가로 항로/픽스를 보고
  // 싶은 FIR, 사용자 피드백 2026-07-23) — relevantFirBounds가 참조한다. onFirClick은
  // 뷰모드와 무관하게 항상 등록돼 있어 결정 포커스에서 클릭해도 pin은 기록되지만, 그
  // 즉시 반영되진 않고(gate: viewMode !== "focus") 이후 지역컨텍스트로 전환할 때
  // renderForCurrentState()가 relevantFirBounds를 다시 계산하며 자동 적용된다.
  const pinnedFirIcaos = new Set();
  const referenceLayers = createReferenceLayers(map, CONFIG, {
    onFirClick(icao) {
      if (pinnedFirIcaos.has(icao)) return;
      pinnedFirIcaos.add(icao);
      const state = getState();
      if (state.viewMode !== "focus" && state.bulk) applyBulkOverlayFilters(state);
    },
  });
  // 참조 레이어(FIR/TCA/항공로/픽스/항행시설/공항)의 기본 표시 여부는 reference.js가
  // 자체적으로 초기화한다(enabledByName/applyAirportZoomVisibility, 2026-07-23) — 여기서
  // 별도로 addTo하지 않는다. 예전엔 이 파일이 전부 무조건 addTo했는데, 그러면 그룹형
  // 레이어 컨트롤 체크박스로 뷰모드 전환 후에도 상태를 지키기 위한 단일 출처(reference.js)와
  // 부팅 시점 상태가 두 곳에 나뉘어 어긋날 수 있었다(리뷰 지적).
  const routeLayers = createRouteLayers(map, CONFIG);
  const windLayer = createWindLayer(map, CONFIG);
  const adsb = createAdsbLayer(map, CONFIG);
  // 실시간 섹터 교통·수요예측(A4, docs/13 STEP A4) — adsb.js의 매 폴링 스냅샷을 구독해
  // 선택된 경로가 지나는 섹터의 현재/+10분 교통량을 갱신한다(windLayer와 동일한 선택 경로
  // 연동 지점, 아래 od:selected/option:selected 핸들러 참고).
  const sectorPanel = createSectorPanel(CONFIG);
  // 세그먼트 병목 종합(A5, docs/13 STEP A5) — A1(흐름관리)·A3(상층풍)·A4(섹터교통)를 한 패널로.
  // windLayer/sectorPanel의 update()가 끝난 뒤에만 호출해야 그 둘의 getRecommendation()/
  // getDemand()가 최신 값을 반환한다(아래 option:selected 핸들러에서 Promise.all로 순서 보장).
  const bottlenecksPanel = createBottlenecksPanel(CONFIG, windLayer, sectorPanel);
  adsb.onSnapshot((aircraft) => {
    sectorPanel.onAircraftUpdate(aircraft);
    // 섹터 패널 자체는 매 폴링(12초)마다 실시간 갱신되는데 A5 패널은 선택 시점에 한 번만
    // 그려서 그 사이 정체 신호가 새로 생겨도 반영이 안 됐다(리뷰 지적, 2026-07-24) — A1(흐름
    // 관리)은 재조회하지 않고 A4(섹터 교통) 표시만 최신화(refreshSectorSignal 내부에서 현재
    // 선택된 노선인지 확인 후 무해하게 무시).
    const state = getState();
    bottlenecksPanel.refreshSectorSignal(state.dep, state.arr);
  });
  // 실시간 항공기는 기본 꺼짐(참고 완성본 원본 주석 "실시간 항공기 — 기본 꺼짐"과 동일,
  // 사용자 요청 2026-07-23) — adsb.start()는 폴링을 그대로 돌려 STCA/CPA 계산에 쓰지만
  // 마커 표시 자체는 레이어 컨트롤에서 켤 때만.
  const hazards = createHazardLayers(CONFIG);
  const radar = createRadarLayer(map, CONFIG);
  // 기상 레이더는 기본 켜짐(사용자 요청 2026-07-23) — SIGMET/PIREP과 달리 온디맨드 로드를
  // 트리거하는 overlayadd를 수동으로 한 번 발생시켜야 최초 프레임이 즉시 뜬다(체크박스를
  // 사용자가 직접 클릭한 것과 동일한 경로).
  radar.group.addTo(map);
  map.fire("overlayadd", { layer: radar.group, name: "기상 레이더(강수)" });

  // 위험기상(SIGMET/PIREP)은 기본 OFF·조건부 토글(docs/10 §2.5 ④) — 레이어 컨트롤에서
  // 켤 때만 조회한다(radar.js의 온디맨드 로드와 동일 원칙). SIGMET은 전세계 목록이라
  // bbox 없이 1회 조회, PIREP은 `bbox` 필수라 현재 지도 뷰포트 기준으로 조회 —
  // 지도를 이동해도 자동 재조회는 하지 않는다(토글 재클릭으로 갱신, 의도적 축소범위).
  // seq 가드(리뷰 지적사항, 2026-07-23): 체크박스를 빠르게 껐다 켰다 하면 프록시
  // 폴백 체인이 수초 걸리는 동안 오래된 응답이 나중에 도착해 최신 상태를 덮어쓸 수
  // 있다 — selectOd/setViewMode와 동일한 세대 토큰 패턴.
  let sigmetSeq = 0;
  let pirepSeq = 0;
  map.on("overlayadd", async (e) => {
    if (e.layer === hazards.sigmetGroup) {
      const seq = ++sigmetSeq;
      try {
        const data = await getSigmets();
        if (seq !== sigmetSeq) return;
        hazards.renderSigmets(data);
      } catch {
        if (seq !== sigmetSeq) return;
        toast("SIGMET 조회 실패 — 네트워크 연결을 확인하세요");
      }
    }
    if (e.layer === hazards.pirepGroup) {
      const seq = ++pirepSeq;
      const b = map.getBounds();
      const bbox = [b.getSouth(), b.getWest(), b.getNorth(), b.getEast()].join(",");
      try {
        const data = await getPireps({ bbox });
        if (seq !== pirepSeq) return;
        hazards.renderPireps(data);
      } catch {
        if (seq !== pirepSeq) return;
        toast("PIREP 조회 실패 — 네트워크 연결을 확인하세요");
      }
    }
  });

  // 그룹형 레이어 컨트롤(사용자 요청 2026-07-23, 참고 완성본과 동일한 3섹션 구성) —
  // Leaflet 기본 L.control.layers는 평면 목록만 지원해 섹션 구분이 안 되므로 커스텀
  // 컨트롤(layer-control.js)로 교체. SUAS 특수공역(한국/세계)은 2026-07-24 DB 적재 완료 —
  // "절차·공역" 섹션에 2개 체크박스로 추가(referenceLayers.setGroupEnabled와 동일 패턴).
  createGroupedLayerControl(map, [
    {
      title: "기본 항공정보",
      // firs/tca/airways/waypoints/navaids는 item.layer(직접 map.addLayer/removeLayer)
      // 대신 referenceLayers.setGroupEnabled를 거친다 — showFocus()/showBulk()(뷰모드
      // 전환·경로 선택마다 호출)가 같은 enabledByName을 단일 출처로 참조하므로, 체크박스로
      // 꺼둔 레이어가 뷰모드를 바꿔도 다시 켜지지 않는다(리뷰 지적, 2026-07-23 — 이전엔
      // item.layer 방식이라 이 두 곳의 상태가 서로 몰랐음).
      items: [
        {
          label: "전 세계 FIR",
          checked: referenceLayers.isGroupEnabled("firs"),
          onChange: (checked) => referenceLayers.setGroupEnabled("firs", checked),
        },
        {
          label: "접근관제구역 TCA",
          checked: referenceLayers.isGroupEnabled("tca"),
          onChange: (checked) => referenceLayers.setGroupEnabled("tca", checked),
        },
        {
          label: "항공로",
          checked: referenceLayers.isGroupEnabled("airways"),
          onChange: (checked) => referenceLayers.setGroupEnabled("airways", checked),
        },
        {
          label: "항로 픽스",
          checked: referenceLayers.isGroupEnabled("waypoints"),
          onChange: (checked) => referenceLayers.setGroupEnabled("waypoints", checked),
        },
        // 공항은 줌 레벨에 따라 airportsLow/airportsAll을 자체 교체하는 별도 로직이라
        // enabledByName이 아니라 전용 airportsEnabled 플래그를 쓴다(reference.js 참고).
        { label: "공항", checked: true, onChange: (checked) => referenceLayers.setAirportsEnabled(checked) },
        {
          label: "항행시설 VOR/NDB",
          checked: referenceLayers.isGroupEnabled("navaids"),
          onChange: (checked) => referenceLayers.setGroupEnabled("navaids", checked),
        },
      ],
    },
    {
      title: "절차·공역",
      items: [
        { label: "SID 출발절차(한국)", layer: routeLayers.sidGroup },
        { label: "STAR 도착절차(한국)", layer: routeLayers.starGroup },
        {
          label: "특수공역 SUAS/MOA(한국)",
          checked: referenceLayers.isGroupEnabled("suasKr"),
          onChange: (checked) => referenceLayers.setGroupEnabled("suasKr", checked),
        },
        {
          label: "특수공역 SUAS/MOA(세계)",
          checked: referenceLayers.isGroupEnabled("suasWorld"),
          onChange: (checked) => referenceLayers.setGroupEnabled("suasWorld", checked),
        },
      ],
    },
    {
      title: "실시간·기상",
      items: [
        { label: "실시간 항공기 ADS-B", layer: adsb.group },
        // STCA/CPA는 map.addLayer로 표현되는 실제 레이어가 아니라(마커 아이콘에 링을
        // 얹고 연결선/패널을 갱신하는 계산형 오버레이) onChange만으로 처리.
        { label: "근접 경고 (참고용 STCA)", checked: false, onChange: (checked) => adsb.setStcaEnabled(checked) },
        { label: "동고도 조우 예측 (15분)", checked: false, onChange: (checked) => adsb.setCpaEnabled(checked) },
        { label: "SIGMET(위험기상)", layer: hazards.sigmetGroup },
        { label: "PIREP(조종사 기상 보고)", layer: hazards.pirepGroup },
        { label: "기상 레이더(강수)", layer: radar.group },
      ],
    },
  ]);

  bindAirportWeatherButtons(map);
  initRoutePanel();
  initFoisPanel();
  initFlowManagementPanel();
  initRouteFoisSummary();
  initRouteOpsSummary();
  initRouteFlowSummary();
  initOpsPanel();
  initMinimap(map, CONFIG);

  function fitToSelectedRoute() {
    const state = getState();
    if (!state.routeResult || state.selectedOptionIndex == null) return false;
    // render()가 아니라 boundsFor()만 쓴다 — render()는 clear()로 sidstar까지 지우는데
    // 여기(뷰모드 전환)는 refreshSidStar를 다시 안 불러서 SID/STAR가 사라진 채로 안
    // 돌아오는 버그가 있었다(리뷰 지적사항, 2026-07-23). 경로 자체는 이미 od:selected/
    // option:selected 때 그려져 있으므로 다시 그릴 필요가 없다.
    const bounds = routeLayers.boundsFor(state.routeResult, state.selectedOptionIndex, state.derived.airportByIcao);
    if (bounds) map.fitBounds(bounds, { padding: [40, 40] });
    return true;
  }

  initViewModeToggle(map, CONFIG, { onFocusEnter: fitToSelectedRoute });

  // OD를 고르기 전에는 부트 공항 전체(민간/공용)를 보여줘 사용자가 지도에서 위치를
  // 훑어볼 수 있게 하지만, OD를 고른 뒤에는 출발·도착 공항 외 나머지는 경로와 무관한
  // 잡음이라 숨긴다(사용자 피드백, 2026-07-23).
  function focusAirportsFor(state) {
    if (!state.dep || !state.arr) return state.bootAirports;
    return state.bootAirports.filter((a) => a.icao === state.dep || a.icao === state.arr);
  }

  // 전세계/지역 컨텍스트에서 항로·픽스·항행시설(country 태그 없음) 전량을 그대로 그리면
  // 너무 번잡하다는 피드백(2026-07-23) — 우리나라(CONFIG.display.homeFirIcao) FIR은 항상,
  // 나머지는 현재 관련 있는 FIR(선택된 경로의 경유 FIR)의 bbox 안에 있을 때만 남긴다.
  // 정확한 점-폴리곤 판정 대신 bbox를 쓰는 이유는 geo.js의 boundsOfPolygons 주석 참고
  // (항로 89,555개 전부에 폴리곤 판정을 돌리면 메인 스레드가 오래 막힘).
  function relevantFirBounds(state) {
    const icaos = new Set([CONFIG.display.homeFirIcao, ...pinnedFirIcaos]);
    for (const f of state.focusFirs) icaos.add(f.icao);
    const bounds = [];
    for (const icao of icaos) {
      const fir = state.derived.firByIcao.get(icao);
      if (fir) bounds.push(boundsOfPolygons(fir.polygons));
    }
    return bounds;
  }

  function inAnyBounds(lat, lon, boundsList) {
    return boundsList.some((b) => pointInBounds(lat, lon, b));
  }

  // 픽스(waypoints)는 서버가 limit<=800으로 강제 하드캡한다(전 세계 실제 개수는 58,812).
  // bbox 없이 받으면 세계 어딘가의 임의 800개일 뿐이라(실측: 그중 우리나라·관련 FIR에
  // 속하는 게 800개 중 4개뿐이었음, 2026-07-23), state.bulk.waypoints를 그대로 클라이언트
  // 필터링해봐야 의미가 없다 — 관련 FIR bbox로 서버에 다시 요청해서 그 범위 안에서
  // 800개를 채우도록 한다. 관련 FIR(선택 경로)이 바뀔 때마다 다시 부른다.
  let waypointsFetchSeq = 0;
  async function refreshScopedWaypoints(state) {
    if (state.viewMode === "focus" || !state.bulk) return;
    const boundsList = relevantFirBounds(state);
    if (boundsList.length === 0) return;
    const seq = ++waypointsFetchSeq;
    const bbox = unionBounds(boundsList).join(",");
    try {
      const res = await api.waypoints({ bbox, limit: CONFIG.display.waypointLimit });
      // 응답 도착 전에 더 최신 요청이 시작됐거나(seq 불일치) 그사이 결정 포커스로
      // 전환됐으면(포커스는 자기 몫의 state.focusWaypoints를 이미 동기로 렌더해 둠) 폐기한다.
      if (seq !== waypointsFetchSeq || getState().viewMode === "focus") return;
      referenceLayers.renderWaypoints(res.data.map(toWaypoint));
    } catch {
      // 픽스 조회 실패는 치명적이지 않음(장식적 참조 레이어) — 기존 표시 유지
    }
  }

  // 우리나라 공항: 출발이면 SID, 도착이면 STAR를 경로 선택 시 같이 표시(사용자 요청,
  // 2026-07-23). sidstar 데이터는 한국 공항만 있어(원본 문서/08 §SS) 외국 공항이면
  // 그냥 빈 배열이 온다 — ICAO 접두사로 미리 거를 필요 없이 결과만 각 역할별로 필터.
  let sidStarSeq = 0;
  // A5(경로 병목 종합) 오케스트레이션 전용 세대 토큰 — bottlenecksPanel 내부의 `seq`(update()
  // 호출 간 순서)와는 별개 문제를 막는다: 사용자가 노선을 고르자마자 빠르게 선택 해제하면
  // (bottlenecksPanel.clear() 먼저 실행) windLayer/sectorPanel의 Promise.all이 뒤늦게 끝나면서
  // 이미 숨긴 패널을 다시 그릴 수 있었다(리뷰 지적, 2026-07-24) — 아래 두 지점(선택/해제)
  // 모두에서 증가시켜, Promise.all의 `.then()`이 실행될 때 "그 사이 다른 선택/해제가
  // 없었는지"를 확인한다.
  let bottlenecksSeq = 0;
  async function refreshSidStar(dep, arr) {
    const seq = ++sidStarSeq;
    // 출발/도착 중 하나만 조회 실패해도(네트워크 일시 오류 등) 나머지 하나는 보여준다
    // (리뷰 지적사항, 2026-07-23) — waypoints/sigmet/pirep과 동일하게 Promise.all 대신
    // allSettled로 부분 실패를 허용.
    const [depOutcome, arrOutcome] = await Promise.allSettled([
      api.sidstar({ airport: dep }),
      api.sidstar({ airport: arr }),
    ]);
    if (seq !== sidStarSeq) return; // 더 최신 선택이 진행 중 — 폐기
    const sid = depOutcome.status === "fulfilled" ? depOutcome.value.data.filter((r) => r.proc === 1).map(toSidStar) : [];
    const star = arrOutcome.status === "fulfilled" ? arrOutcome.value.data.filter((r) => r.proc === 2).map(toSidStar) : [];
    routeLayers.renderSidStar([...sid, ...star]);
  }

  function filterNavaidsForBulk(rows, boundsList) {
    return rows.filter((nv) => inAnyBounds(nv.lat, nv.lon, boundsList));
  }

  function filterAirwaysForBulk(rows, boundsList) {
    return rows.filter(
      (aw) => inAnyBounds(aw.coords[0][0], aw.coords[0][1], boundsList) || inAnyBounds(aw.coords[1][0], aw.coords[1][1], boundsList),
    );
  }

  // FIR/공항 레이어는 다시 그리지 않고 항로·항행시설·픽스만 relevantFirBounds 기준으로
  // 다시 필터링한다 — FIR 클릭으로 pinnedFirIcaos가 바뀐 직후 이걸 호출하는데, renderFirs를
  // 같이 다시 그리면 방금 클릭해서 열린 팝업이 레이어 재생성으로 닫혀버린다.
  function applyBulkOverlayFilters(state) {
    const boundsList = relevantFirBounds(state);
    referenceLayers.renderAirways(filterAirwaysForBulk(state.bulk.airways, boundsList));
    referenceLayers.renderNavaids(filterNavaidsForBulk(state.bulk.navaids, boundsList));
    refreshScopedWaypoints(state); // 비동기 — 완료되면 renderWaypoints를 별도 호출
  }

  function renderForCurrentState() {
    const state = getState();
    if (state.viewMode === "focus") {
      referenceLayers.renderFirs(state.focusFirs);
      referenceLayers.renderAirways(state.focusAirways);
      referenceLayers.renderTca([]);
      referenceLayers.renderSuas([]);
      referenceLayers.renderWaypoints(state.focusWaypoints);
      referenceLayers.renderNavaids([]);
      referenceLayers.renderAirports(focusAirportsFor(state));
      referenceLayers.showFocus();
    } else if (state.bulk) {
      referenceLayers.renderFirs(state.bulk.firs);
      referenceLayers.renderTca(state.bulk.tca);
      referenceLayers.renderSuas(state.bulk.suas);
      referenceLayers.renderAirports(state.bulk.airports);
      referenceLayers.showBulk();
      applyBulkOverlayFilters(state);
    }
    updateCounts(state);
  }

  subscribe((state, event) => {
    if (event.type === "boot:error" || event.type === "od:error" || event.type === "viewmode:error") {
      toast(event.message);
    }
    if (event.type === "boot:ok") {
      // 부팅 직후 기본값: 우리나라(홈) FIR·항로·픽스를 즉시 그리고(사용자 요청,
      // 2026-07-23 — loadFocusReference가 이미 계산해 둔 focusFirs/focusAirways/
      // focusWaypoints를 렌더만 누락하고 있었음) 지도도 그 FIR 범위로 맞춰 실시간
      // 항공기(지도 중심 기준 폴링) 조회도 우리나라 상공을 향하게 한다.
      try {
        renderForCurrentState();
        const homeFir = state.derived.firByIcao.get(CONFIG.display.homeFirIcao);
        if (homeFir) {
          const [minLat, minLon, maxLat, maxLon] = boundsOfPolygons(homeFir.polygons);
          map.fitBounds([[minLat, minLon], [maxLat, maxLon]], { padding: [40, 40] });
          // 노선 미선택 결정포커스 기본 상태에서 인천FIR 실시간 항적을 계속 보여달라는
          // 요청(2026-07-23) — 지도 중심(map.getCenter()) 기준 폴링은 사용자가 패닝하면
          // 조용히 다른 지역으로 옮겨가 버리므로, 홈FIR 좌표를 별도 기준점으로 고정한다.
          const center = homeFir.label ?? { lat: (minLat + maxLat) / 2, lon: (minLon + maxLon) / 2 };
          adsb.setHomeCenter({ lat: center.lat, lon: center.lon });
        }
      } catch (err) {
        // 데이터는 이미 정상 로드됐으므로(이 블록은 boot:ok 시점) 여기서 실패해도
        // bootMinimal의 catch로 전파해 "초기 데이터 로드 실패" 토스트를 잘못 띄우지
        // 않는다 — 렌더/뷰맞춤은 장식적이라 실패해도 앱 사용에 치명적이지 않음.
        console.error("초기 화면 렌더 실패", err);
      }
    }
    if (event.type === "od:selected" || event.type === "option:selected") {
      renderForCurrentState();
      routeLayers.render(state.routeResult, state.selectedOptionIndex, state.derived.firByIcao, state.derived.airportByIcao);
      renderFirChain(state.routeResult, state.selectedOptionIndex);
      if (state.viewMode === "focus" && state.selectedOptionIndex != null) fitToSelectedRoute();
      // ADS-B 조회 기준을 지도 중심 대신 선택된 노선을 따라가도록(사용자 요청, 2026-07-23).
      // 특정 옵션이 선택됐을 때만 적용 — "전체 겹쳐보기"(옵션 여럿)는 기존처럼 지도 중심.
      if (state.selectedOptionIndex != null) {
        const opt = state.routeResult.options[state.selectedOptionIndex];
        const coords = opt.fullRouteCoords.length > 0 ? opt.fullRouteCoords : opt.trackCoords;
        adsb.setRouteCoords(coords);
        refreshSidStar(state.dep, state.arr);
        // 상층풍·연직시어·추천고도(A3, docs/13) — 선택된 경로 하나에 대해서만 의미가
        // 있어 "전체 겹쳐보기"(옵션 여럿, selectedOptionIndex===null)에서는 숨긴다.
        // A5는 A3/A4의 계산이 끝난 뒤 그 요약을 읽으므로 Promise.all로 순서를 보장한다
        // (개별 update()를 각자 fire-and-forget으로 두면 A5가 이전 경로의 stale 요약을
        // 읽을 수 있음). myBottlenecksSeq로 그 사이 다른 선택/해제가 없었는지 재확인
        // (리뷰 지적, 2026-07-24 — 빠른 선택→해제 시 이미 clear()된 패널을 뒤늦게 다시
        // 그리는 문제 방지) + windLayer/sectorPanel이 예외를 던지면 조용히 건너뜀(각
        // 모듈이 자기 실패는 이미 자체 UI로 표시하므로 여기서 추가로 알릴 필요 없음).
        const myBottlenecksSeq = ++bottlenecksSeq;
        Promise.all([windLayer.update(coords, opt.cruiseParity), sectorPanel.update(coords)])
          .then(() => {
            if (myBottlenecksSeq !== bottlenecksSeq) return;
            bottlenecksPanel.update(state.dep, state.arr, coords);
          })
          .catch(() => {});
      } else {
        adsb.setRouteCoords(null);
        // 선택 해제 시에도 세대 토큰을 증가시켜야 한다 — 안 그러면 이미 늦게 도착한
        // 이전 선택의 SID/STAR 응답이 seq 검사를 그대로 통과해 방금 지워진 레이어를
        // 다시 채워 넣는다(리뷰 지적사항, 2026-07-23).
        sidStarSeq += 1;
        bottlenecksSeq += 1; // 진행 중이던 A5 조합(Promise.all)도 폐기 대상
        routeLayers.renderSidStar([]);
        windLayer.clear();
        sectorPanel.clear();
        bottlenecksPanel.clear();
      }
    }
    if (event.type === "viewmode:changed") {
      renderForCurrentState();
    }
  });

  try {
    await bootMinimal();
  } catch (err) {
    toast(`초기 데이터 로드 실패: ${err.message}`);
  }

  // bootMinimal 이후에 시작해야 첫 폴링부터 우리나라 FIR로 맞춰진 지도 중심을 기준으로
  // 조회한다(boot:ok 핸들러가 위에서 이미 fitBounds 적용) — bootMinimal 이전에 시작하면
  // 첫 폴링은 여전히 CONFIG.map.center(세계뷰 기본값)를 기준으로 나가 버린다.
  const chipEl = document.getElementById("adsb-chip");
  adsb.start(chipEl);
  // 방어적 정리(향후 SPA 라우팅 전환 대비) — 정적 단일 페이지라 필수는 아니나 폴링 타이머를 명시적으로 멈춘다.
  window.addEventListener("beforeunload", () => adsb.stop());
}

main().catch((err) => {
  console.error(err);
  toast(`초기화 실패: ${err.message}`);
});
