/**
 * ROUTE 경로 지도 표시 (docs/03 §ROUTE 패널, F6). "전체"=모든 옵션 겹쳐보기(기본),
 * 옵션 선택 시 강조 + 경유 FIR 면(오렌지 10%, nonzero) + 출발/도착 배지.
 *
 * 경로 1(최단, baseline) 대비 다른 옵션이 갈라지는 구간을 빨강으로 구분(사용자 요청,
 * 2026-07-23 — 처음엔 "이번 라운드 생략" 부가 연출로 뒀던 세그먼트 diff를 이 요청으로
 * 도입). 이름 붙은 픽스 체인은 인천FIR 구간만 있고(incheonTrackFixes) 전체 노선은
 * 레이더 트랙 좌표뿐이라, 정확한 경로 일치 판정 대신 baseline 위 어떤 점과도
 * routeDiffThresholdNm 이내인지로 근사한다(splitByBaseline).
 *
 * 명시적 단순화(docs/07-checklist.md Stage2 항목에 동기화): FIR 전환 화살표·▶비행
 * 애니메이션은 여전히 MVP DoD 밖이라 생략 — 정보 패널의 Δ소요(분) 텍스트로 대체.
 */
import { normalizeWinding, unwrapLongitudes, shiftRing } from "../geo.js";
import { escapeHtml } from "../html.js";

const L = window.L;
const EARTH_RADIUS_NM = 3440.065;

function haversineNm(lat1, lon1, lat2, lon2) {
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_NM * Math.asin(Math.sqrt(a));
}

function cumulativeDistancesNm(coords) {
  const cum = [0];
  for (let i = 1; i < coords.length; i++) {
    cum.push(cum[i - 1] + haversineNm(coords[i - 1][0], coords[i - 1][1], coords[i][0], coords[i][1]));
  }
  return cum;
}

// 30/60/90분... 경과 시점의 예상 위치(사용자 요청, 2026-07-24) — 등속(총소요시간 대비
// 누적거리 비례) 가정의 단순 버전으로, 사용자 확인 후 이렇게 먼저 진행하기로 확정.
// 실제로는 이착륙 전후 상승/강하 구간이 순항보다 느려 오차가 있을 수 있어(등속 가정의
// 한계), 라벨에 "(추정)"을 명시해 실제 위치처럼 보이지 않게 한다(허위 정보 생성 금지 원칙).
function pointAtElapsedMin(coords, cumDist, totalMin, elapsedMin) {
  const totalNm = cumDist[cumDist.length - 1];
  const targetNm = (elapsedMin / totalMin) * totalNm;
  let i = 0;
  while (i < cumDist.length - 1 && cumDist[i + 1] < targetNm) i++;
  const segStartNm = cumDist[i];
  const segEndNm = cumDist[Math.min(i + 1, cumDist.length - 1)];
  const frac = segEndNm > segStartNm ? (targetNm - segStartNm) / (segEndNm - segStartNm) : 0;
  const [la1, lo1] = coords[i];
  const [la2, lo2] = coords[Math.min(i + 1, coords.length - 1)];
  return [la1 + (la2 - la1) * frac, lo1 + (lo2 - lo1) * frac];
}

function isNearBaseline(point, baselineCoords, thresholdNm) {
  for (const [la, lo] of baselineCoords) {
    if (haversineNm(point[0], point[1], la, lo) <= thresholdNm) return true;
  }
  return false;
}

// coords를 baseline 근접 여부가 바뀌는 지점마다 잘라 [{near, points}] 런으로 반환한다.
// 경계점은 양쪽 구간에 공유시켜(current.push 후 다음 run의 시작으로도 재사용) 선이
// 끊어져 보이지 않게 한다.
function splitByBaseline(coords, baselineCoords, thresholdNm) {
  const runs = [];
  let currentNear = null;
  let current = [];
  for (const pt of coords) {
    const near = isNearBaseline(pt, baselineCoords, thresholdNm);
    if (currentNear === null) {
      currentNear = near;
      current = [pt];
    } else if (near === currentNear) {
      current.push(pt);
    } else {
      current.push(pt);
      runs.push({ near: currentNear, points: current });
      current = [pt];
      currentNear = near;
    }
  }
  if (current.length > 0) runs.push({ near: currentNear, points: current });
  return runs;
}

// SID/STAR 전용 pane(사용자 제보, 2026-07-23) — 기본 pane 구성상 마커(markerPane,
// zIndex 600)·상시 툴팁(tooltipPane, 650)이 벡터 레이어(overlayPane, 400)보다 항상 위에
// 그려진다. 인천처럼 실시간 ADS-B 항공기가 밀집한 공항에서는 그 마커/라벨 더미가 바로
// 밑에 깔린 SID/STAR 선을 완전히 가려 "안 보인다"는 제보로 이어졌다(Playwright로 실측 —
// 선 자체는 정상 렌더링되고 있었음). 마커·상시 툴팁보다 더 높은 zIndex를 줘서 실시간
// 항공기가 몰려 있어도 SID/STAR 선이 항상 보이게 한다.
const SIDSTAR_PANE = "sidstarPane";
const SIDSTAR_PANE_Z_INDEX = 660; // markerPane(600)·tooltipPane(650)보다 위

export function createRouteLayers(map, CONFIG) {
  const group = L.layerGroup().addTo(map);
  const firHighlight = L.layerGroup().addTo(map);
  if (!map.getPane(SIDSTAR_PANE)) {
    map.createPane(SIDSTAR_PANE);
    map.getPane(SIDSTAR_PANE).style.zIndex = SIDSTAR_PANE_Z_INDEX;
  }
  // 우리나라 공항: 출발이면 SID(파랑), 도착이면 STAR(녹색) — 경로 선택 시 함께 표시
  // (사용자 요청, 2026-07-23; 원본 문서/08 §SS 색상 규약). main.js가 비동기로 채운다.
  // 레이어 컨트롤에서 SID·STAR를 독립적으로 켜고 끌 수 있어야 한다는 요청(2026-07-23,
  // 참고 완성본의 레이어 목록 "SID 출발절차"/"STAR 도착절차" 분리와 동일)으로 레이어그룹을
  // 둘로 나눔 — 완성본과 동일하게 기본은 꺼짐(map에 addTo하지 않음), main.js의 그룹형
  // 레이어 컨트롤 체크박스가 켜질 때만 map.addLayer로 표시한다.
  const sidGroup = L.layerGroup();
  const starGroup = L.layerGroup();

  function clear() {
    group.clearLayers();
    firHighlight.clearLayers();
    sidGroup.clearLayers();
    starGroup.clearLayers();
  }

  function renderSidStar(rows) {
    sidGroup.clearLayers();
    starGroup.clearLayers();
    for (const proc of rows) {
      const isSid = proc.proc === 1;
      const color = isSid ? CONFIG.tokens.blue : CONFIG.tokens.green;
      const target = isSid ? sidGroup : starGroup;
      L.polyline(proc.coords, { color, weight: 2, opacity: 0.85, pane: SIDSTAR_PANE })
        .bindPopup(escapeHtml(proc.name))
        .addTo(target);
      const start = proc.coords[0];
      if (start) {
        L.circleMarker(start, { radius: 3, color, weight: 1, fillColor: color, fillOpacity: 1, pane: SIDSTAR_PANE }).addTo(
          target,
        );
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

  // baselineCoords가 없으면(경로 1 자신) 항상 기존 단색 스타일. 있으면(경로 2+) baseline
  // 근접 여부로 잘라, 겹치는 구간은 기존 스타일 그대로·갈라지는 구간만 routeDiffRed로 그린다.
  function drawOption(opt, emphasize, routeResult, airportByIcao, baselineCoords) {
    const coords = coordsWithAirports(opt, routeResult, airportByIcao);
    if (!baselineCoords || baselineCoords.length === 0) {
      L.polyline(coords, {
        color: emphasize ? CONFIG.tokens.blue : CONFIG.tokens.inkSoft,
        weight: emphasize ? 4 : 2,
        opacity: emphasize ? 0.95 : 0.45,
      }).addTo(group);
      return;
    }
    const runs = splitByBaseline(coords, baselineCoords, CONFIG.display.routeDiffThresholdNm);
    for (const run of runs) {
      if (run.points.length < 2) continue;
      L.polyline(run.points, {
        color: run.near ? (emphasize ? CONFIG.tokens.blue : CONFIG.tokens.inkSoft) : CONFIG.tokens.routeDiffRed,
        weight: emphasize ? 4 : 2,
        opacity: run.near ? (emphasize ? 0.95 : 0.45) : 0.9,
      }).addTo(group);
    }
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

  // 등속 가정 보간이라 좌표 간격이 너무 성기면(장거리 구간) 오차가 커진다 — coords 자체는
  // 이미 레이더 트랙 표본이라 대개 충분히 촘촘하므로 추가 표본화는 하지 않는다(단순 버전).
  //
  // coords[0]=출발/coords[last]=도착·avgMin=총소요시간이라는 전제는 store.js의
  // selectOd()가 ensureAirportsLoaded()를 od:selected 통지 전에 await하는 순서에
  // 암묵적으로 의존한다(리뷰 지적, 2026-07-24) — 이 순서가 깨지면 coordsWithAirports가
  // 공항 좌표 대신 레이더 최초 포착 지점(이착륙 도중일 수 있음)을 t=0 기준으로 써 "N분
  // 후" 라벨이 실제와 다른 지점을 가리키게 된다. 현재 흐름에서는 재현 안 됨(추적 확인),
  // 향후 store.js 리팩터 시 이 가정이 깨지지 않는지 함께 확인할 것.
  const MAX_TIME_MARKERS = 50; // 설정값 오기입(예: stepMin이 지나치게 작음)으로 마커가
  // 과도하게 생성되는 것 방지(리뷰 지적, 2026-07-24) — 장거리 노선이라도 이 이상은 라벨이
  // 겹쳐 어차피 못 읽으므로 상한을 둔다.
  function renderTimeMarkers(opt, coords) {
    const totalMin = Number(opt.avgMin);
    const stepMin = Number(CONFIG.display.routeTimeMarkerStepMin);
    // Infinity는 `> 0`을 통과하므로(리뷰 지적, 2026-07-24 — 브라우저 행 유발 가능한
    // 무한루프) Number.isFinite로 명시적으로 걸러낸다.
    if (!Number.isFinite(totalMin) || totalMin <= 0 || !Number.isFinite(stepMin) || stepMin <= 0 || coords.length < 2) {
      return;
    }
    const cumDist = cumulativeDistancesNm(coords);
    let count = 0;
    for (let t = stepMin; t < totalMin && count < MAX_TIME_MARKERS; t += stepMin, count++) {
      const [lat, lon] = pointAtElapsedMin(coords, cumDist, totalMin, t);
      L.circleMarker([lat, lon], {
        radius: 5,
        color: CONFIG.tokens.ink,
        weight: 1.5,
        fillColor: CONFIG.tokens.paper,
        fillOpacity: 1,
      })
        .bindTooltip(`${t}분 후(추정)`, {
          permanent: true,
          direction: "top",
          offset: [0, -6],
          className: "route-time-marker-label",
        })
        .addTo(group);
    }
  }

  /** routeResult 전체를 selectedIndex(없으면 전체 겹쳐보기)에 맞춰 다시 그린다.
   * airportByIcao가 있으면 실제 공항 좌표까지 선을 이어 붙인다(위 coordsWithAirports). */
  function render(routeResult, selectedIndex, firByIcao, airportByIcao) {
    clear();
    if (!routeResult) return null;
    const options = routeResult.options;
    // 경로 1(항상 baseline)은 그대로, 나머지는 경로 1 대비 갈라지는 구간만 빨강으로
    // 구분(drawOption 참고) — idx===0에는 baselineCoords로 null을 넘겨 diff 대상에서 뺀다.
    const baselineCoords = options.length > 1 ? coordsWithAirports(options[0], routeResult, airportByIcao) : null;
    if (selectedIndex === null || selectedIndex === undefined) {
      options.forEach((opt, idx) => drawOption(opt, false, routeResult, airportByIcao, idx === 0 ? null : baselineCoords));
      return null;
    }
    const selected = options[selectedIndex];
    options.forEach((opt, idx) =>
      drawOption(opt, idx === selectedIndex, routeResult, airportByIcao, idx === 0 ? null : baselineCoords),
    );
    highlightFirs(selected.enrouteFirs, firByIcao);
    addEndpointBadges(selected, routeResult, airportByIcao);
    renderTimeMarkers(selected, coordsWithAirports(selected, routeResult, airportByIcao));
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

  return { group, firHighlight, sidGroup, starGroup, render, clear, renderSidStar, boundsFor };
}
