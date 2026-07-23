/**
 * 실시간 항공기(ADS-B) (docs/03 §레이어9, F8). 외부 API 직접(화이트리스트 3종, 문서 07 §4)
 * 폴링(12초, 반경 250NM 지도중심), 헤딩 방향으로 회전하는 기체 실루엣 + 편명/노선 2줄
 * 상시 라벨(완성본 PORTING_PACKAGE_ROOT 이식), 클릭 시 상세(고도/속도/정확한 노선) 조회.
 *
 * 상시 2줄 라벨(편명 + 출발→도착)은 사용자 요청(2026-07-23)으로 도입 — 이전에는 무료
 * adsbdb 부하를 이유로 편명만 상시 표시했으나(과거 결정), 완성본의 배치 조회 방식(사이클당
 * 편명 최대 `routeCodeBatchSize`개씩만 조회해 캐시를 점진 충전)을 그대로 이식해 부하를
 * 제한하면서도 상시 라벨을 지원한다: adsb.lol route API 우선 조회, 실패 시 adsbdb 폴백.
 * 캐시(`routeCodes`)는 편명당 한 번만 채우면 되므로(빈 문자열=조회 완료·노선 없음, 재조회
 * 방지) 표시 기체 수가 늘어도 폴링마다의 신규 조회량은 배치 크기로 상한이 걸린다.
 * 이 캐시는 지도 라벨(IATA/ICAO 혼용 표시)용이며, 클릭 상세 팝업·추정 경로선(ICAO 정확도
 * 필요)은 기존처럼 adsbdb를 별도 재조회한다(`showAircraftDetail`, 아래).
 *
 * 보안(리뷰 반영, 2026-07-22): 외부 API가 돌려주는 콜사인/기종/등록기호/노선 코드가
 * 클릭 없이도(permanent 툴팁) 렌더링되므로 escapeHtml 없이는 XSS 삽입 지점이 된다 —
 * 모든 외부 문자열은 innerHTML/divIcon html/bindTooltip·bindPopup에 넣기 전 이스케이프한다.
 *
 * 원본 05_트러블슈팅.md("ADS-B 전체 실패... 3연속 실패 시 30초 백오프, 마지막 데이터 유지")
 * 규칙을 그대로 이식: 연속 실패 카운터로 폴링 간격을 30초로 늘리고, 실패해도 기존 마커는
 * 지우지 않는다(성공 시 즉시 기본 간격 복귀).
 */
import { createFallbackFetcher } from "../net.js";
import { escapeHtml } from "../html.js";
import { api } from "../api.js";
import { unwrapLongitudes } from "../geo.js";

const L = window.L;
const fetchJsonWithFallback = createFallbackFetcher();
const BACKOFF_THRESHOLD = 3;
const BACKOFF_INTERVAL_MS = 30000;

// FR24 스타일 기체 실루엣(완성본 PORTING_PACKAGE_ROOT canvas path 이식). 기수가 (0,-9)를
// 향하도록(0deg=북쪽) 그려져 있어, CSS transform:rotate(track deg)를 그대로 적용하면
// 완성본의 ctx.rotate(track*PI/180)와 동일한 방향으로 회전한다.
const PLANE_PATH =
  "M0,-9 Q1.4,-7.5 1.4,-4.8 L1.4,-2.0 L8.6,3.0 L8.6,4.6 L1.4,2.6 L1.2,5.6 L3.8,7.8 L3.8,9.0 " +
  "L0.8,8.2 L0,8.6 L-0.8,8.2 L-3.8,9.0 L-3.8,7.8 L-1.2,5.6 L-1.4,2.6 L-8.6,4.6 L-8.6,3.0 " +
  "L-1.4,-2.0 L-1.4,-4.8 Q-1.4,-7.5 0,-9 Z";

function buildPointUrl(template, lat, lon, radiusNm) {
  return template.replace("{lat}", lat.toFixed(2)).replace("{lon}", lon.toFixed(2)).replace("{radiusNm}", String(radiusNm));
}

async function fetchAircraft(lat, lon, radiusNm, endpoints) {
  let lastErr;
  for (const template of endpoints) {
    try {
      const data = await fetchJsonWithFallback(buildPointUrl(template, lat, lon, radiusNm));
      return data.ac ?? [];
    } catch (err) {
      lastErr = err;
    }
  }
  throw lastErr ?? new Error("ADS-B 데이터를 가져올 수 없음");
}

// 노선 선택 시 지도 중심이 아니라 경로를 따라 여러 지점을 250NM씩 이어붙여 조회한다
// (사용자 요청, 2026-07-23) — 노선 좌표 개수가 많아도(장거리 노선) API 호출이 과도해지지
// 않도록 표본 지점 수를 상한(6)으로 제한한다. 선택된 경로가 없으면 기존처럼 지도 중심만 쓴다.
const MAX_ROUTE_SAMPLE_POINTS = 6;

function sampleRoutePoints(coords, maxPoints) {
  if (coords.length <= maxPoints) return coords;
  const step = (coords.length - 1) / (maxPoints - 1);
  const points = [];
  for (let i = 0; i < maxPoints; i++) points.push(coords[Math.round(i * step)]);
  return points;
}

export function createAdsbLayer(map, CONFIG) {
  const group = L.layerGroup();
  // 항공기 클릭 시 "지나온/도착 예상" 경로 추정선 전용 레이어(사용자 요청, 2026-07-23).
  // 실제 비행계획(필드 플랜) 웨이포인트는 무료 ADS-B API(adsb.lol/adsbdb) 어디서도 안 준다
  // (둘 다 출발/도착 공항 코드까지만 조회됨, 완성본 참고자산도 동일) — 그래서 실제 항로
  // 대신 이 앱 백엔드의 경로추천(ODR2) 데이터(advisor DB에 있는 OD 쌍이면)를 재활용해
  // 현재 위치 기준으로 지나온 구간(실선)·도착 구간(점선)으로 나눠 근사치로 그린다(사용자
  // 확인 후 결정 — 허위 정보 생성 금지 원칙상 팝업에 "추정" 임을 명시한다).
  const routeGuessGroup = L.layerGroup().addTo(map);
  const markersByHex = new Map();
  let timer = null;
  let consecutiveFailures = 0;
  let routeCoords = null;
  let routeGuessSeq = 0; // 팝업을 빠르게 여러 번 열 때 오래된 응답이 늦게 도착해 최신 추정선을 덮어쓰지 않도록

  function iconFor(track) {
    return L.divIcon({
      className: "aircraft-icon-wrap",
      html: `<div class="aircraft-icon" style="transform:rotate(${Number(track) || 0}deg)">&#9992;</div>`,
      iconSize: [16, 16],
      iconAnchor: [8, 8],
    });
  }

  function nearestIndex(coords, lat, lon) {
    let bestIdx = 0;
    let bestDist = Infinity;
    coords.forEach(([la, lo], i) => {
      const d = (la - lat) ** 2 + (lo - lon) ** 2;
      if (d < bestDist) {
        bestDist = d;
        bestIdx = i;
      }
    });
    return bestIdx;
  }

  /** advisor 백엔드의 경로추천(ODR2) 데이터로 depIcao→arrIcao 구간을 조회해, 현재 위치에서
   * 가장 가까운 지점을 기준으로 지나온 구간(실선)·도착 예상 구간(점선)을 그린다. advisor DB에
   * 없는 OD 쌍(세계 임의 항공편)이면 조용히 생략 — 실제 항로가 아니므로 지어내지 않는다. */
  async function renderGuessedRoute(depIcao, arrIcao, currentLatLng) {
    const seq = ++routeGuessSeq;
    routeGuessGroup.clearLayers();
    if (!depIcao || !arrIcao) return false;
    try {
      const res = await api.routes(depIcao, arrIcao);
      if (seq !== routeGuessSeq) return false; // 더 최신 클릭이 진행 중 — 폐기
      const opt = res.data.options?.[0];
      const raw = opt && (opt.full_route_coords?.length > 0 ? opt.full_route_coords : opt.track_coords);
      if (!raw || raw.length < 2) return false;
      // nearestIndex는 반드시 언랩 전(raw) 좌표로 계산한다 — currentLatLng는 ADS-B 원시
      // 경도(-180~180)라 unwrapLongitudes로 이미 ±360 보정된 coords와 직접 비교하면 날짜
      // 변경선을 넘는 노선(한국↔미국 등, 이 파일이 unwrapLongitudes를 쓰는 바로 그 이유)
      // 에서 분할 지점이 노선 반대쪽 끝으로 튀는 버그가 있었다(리뷰 지적, 2026-07-23).
      const splitIdx = nearestIndex(raw, currentLatLng.lat, currentLatLng.lng);
      const coords = unwrapLongitudes(raw);
      const flown = coords.slice(0, splitIdx + 1);
      const remaining = coords.slice(splitIdx);
      if (flown.length > 1) {
        L.polyline(flown, { color: CONFIG.tokens.blue, weight: 3, opacity: 0.85 }).addTo(routeGuessGroup);
      }
      if (remaining.length > 1) {
        L.polyline(remaining, { color: CONFIG.tokens.blue, weight: 3, opacity: 0.85, dashArray: "6,6" }).addTo(
          routeGuessGroup,
        );
      }
      return flown.length > 1 || remaining.length > 1;
    } catch {
      // advisor DB에 해당 OD 쌍이 없거나(대부분 세계 임의 항공편) 조회 실패 — 추정선 없이 진행
      if (seq === routeGuessSeq) routeGuessGroup.clearLayers();
      return false;
    }
  }

  async function showAircraftDetail(marker, ac) {
    const popup = L.popup().setLatLng(marker.getLatLng()).setContent("불러오는 중…").openOn(map);
    // 팝업이 닫히면 이 항공기 전용으로 그린 추정 경로선도 함께 지운다. seq도 함께 무효화해야
    // 한다 — 안 그러면 팝업을 닫은 뒤(다른 항공기도 안 눌러서 routeGuessSeq가 그대로인 채)
    // 진행 중이던 조회가 뒤늦게 도착해 seq 검사를 통과, 이미 닫혀 설명(추정치 안내)도 없는
    // 팝업 없이 경로선만 지도에 남는 문제가 있었다(리뷰 지적, 2026-07-23).
    popup.on("remove", () => {
      routeGuessSeq += 1;
      routeGuessGroup.clearLayers();
    });
    const altText = ac.alt_baro === "ground" ? "지상" : `${escapeHtml(ac.alt_baro ?? "-")}ft`;
    let routeText = "";
    const callsign = ac.flight?.trim();
    let depIcao = null;
    let arrIcao = null;
    if (callsign) {
      try {
        const data = await fetchJsonWithFallback(CONFIG.adsb.callsignLookupUrl.replace("{callsign}", encodeURIComponent(callsign)));
        const route = data?.response?.flightroute;
        if (route) {
          depIcao = route.origin?.icao_code ?? null;
          arrIcao = route.destination?.icao_code ?? null;
          routeText = `<div>${escapeHtml(depIcao ?? "?")} → ${escapeHtml(arrIcao ?? "?")}</div>`;
        }
      } catch {
        // adsbdb 조회 실패 — 노선 정보 없이 나머지 상세만 표시
      }
    }
    const drewGuessedRoute = await renderGuessedRoute(depIcao, arrIcao, marker.getLatLng());
    const guessNote = drewGuessedRoute
      ? '<div class="muted">지도에 지나온 구간(실선)·도착 예상 구간(점선) 표시 — 실제 항로가 아니라 경로추천 데이터 기반 추정치</div>'
      : "";
    popup.setContent(
      `<div class="weather-popup">
        <div class="headline">${escapeHtml(callsign || ac.hex)}</div>
        <div>고도 ${altText} · 지상속도 ${escapeHtml(ac.gs ?? "-")}kt · 트랙 ${escapeHtml(ac.track ?? "-")}°</div>
        ${routeText}
        ${guessNote}
        <div class="muted">${escapeHtml(ac.t ?? "")} ${escapeHtml(ac.r ?? "")}</div>
      </div>`,
    );
  }

  function upsert(ac) {
    if (ac.lat == null || ac.lon == null) return;
    const label = escapeHtml(ac.flight?.trim() || ac.hex);
    let marker = markersByHex.get(ac.hex);
    if (!marker) {
      marker = L.marker([ac.lat, ac.lon], { icon: iconFor(ac.track) });
      marker.bindTooltip(label, { permanent: true, direction: "right", className: "aircraft-label", offset: [8, 0] });
      marker.on("click", () => showAircraftDetail(marker, ac));
      marker.addTo(group);
      markersByHex.set(ac.hex, marker);
    } else {
      marker.setLatLng([ac.lat, ac.lon]);
      marker.setIcon(iconFor(ac.track));
      marker.setTooltipContent(label);
    }
  }

  function prune(seenHexes) {
    for (const [hex, marker] of markersByHex) {
      if (!seenHexes.has(hex)) {
        group.removeLayer(marker);
        markersByHex.delete(hex);
      }
    }
  }

  function pollCenters() {
    if (routeCoords && routeCoords.length > 0) {
      return sampleRoutePoints(routeCoords, MAX_ROUTE_SAMPLE_POINTS).map(([lat, lon]) => ({ lat, lon }));
    }
    const c = map.getCenter();
    return [{ lat: c.lat, lon: c.lng }];
  }

  async function poll(chipEl) {
    try {
      const centers = pollCenters();
      const settled = await Promise.allSettled(
        centers.map((c) => fetchAircraft(c.lat, c.lon, CONFIG.adsb.radiusNm, CONFIG.adsb.endpoints)),
      );
      // 표본 지점 중 일부만 실패해도(예: 한 지점만 레이트리밋) 성공한 지점의 항공기는
      // 그대로 보여준다 — 전부 실패했을 때만 전체 폴링 실패로 취급한다.
      const merged = new Map();
      let anySuccess = false;
      let lastError;
      for (const r of settled) {
        if (r.status === "fulfilled") {
          anySuccess = true;
          for (const ac of r.value) if (ac.hex) merged.set(ac.hex, ac);
        } else {
          lastError = r.reason;
        }
      }
      if (!anySuccess) throw lastError ?? new Error("모든 조회 지점 실패");
      consecutiveFailures = 0;
      const seen = new Set();
      for (const ac of merged.values()) {
        if (ac.lat != null && ac.lon != null) {
          upsert(ac);
          seen.add(ac.hex);
        }
      }
      prune(seen);
      if (chipEl) {
        const time = new Date().toLocaleTimeString("ko-KR", { hour12: false });
        chipEl.textContent = `ADS-B ${seen.size}대 · ${time}`;
      }
      rescheduleIfNeeded(chipEl);
    } catch (err) {
      consecutiveFailures += 1;
      // 마지막으로 받은 데이터(마커)는 그대로 유지 — 실패라고 지도를 비우지 않는다(05_트러블슈팅.md).
      if (chipEl) chipEl.textContent = `ADS-B 조회 실패(${consecutiveFailures}회) — ${err.message ?? "알 수 없는 오류"}`;
      rescheduleIfNeeded(chipEl);
    }
  }

  function currentIntervalMs() {
    return consecutiveFailures >= BACKOFF_THRESHOLD ? BACKOFF_INTERVAL_MS : CONFIG.adsb.pollMs;
  }

  function rescheduleIfNeeded(chipEl) {
    if (!timer) return; // stop() 이후에는 재예약하지 않음
    clearInterval(timer);
    timer = setInterval(() => poll(chipEl), currentIntervalMs());
  }

  function start(chipEl) {
    poll(chipEl);
    timer = setInterval(() => poll(chipEl), CONFIG.adsb.pollMs);
  }

  function stop() {
    if (timer) clearInterval(timer);
    timer = null;
  }

  /** 노선 선택/해제 시 main.js가 호출 — coords가 있으면 그 경로를 따라 표본 지점으로
   * 폴링하고, null/빈 배열이면 지도 중심 기준(기존 동작)으로 되돌아간다. */
  function setRouteCoords(coords) {
    routeCoords = coords && coords.length > 0 ? coords : null;
  }

  return { group, start, stop, setRouteCoords };
}
