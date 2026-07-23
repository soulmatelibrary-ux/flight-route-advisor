/**
 * 실시간 항공기(ADS-B) (docs/03 §레이어9, F8). 외부 API 직접(화이트리스트 3종, 문서 07 §4)
 * 폴링(12초, 반경 250NM 지도중심), 노란 기체 마커+편명 라벨, 클릭 시 노선(adsbdb) 조회.
 *
 * 명시적 단순화(docs/07-checklist.md Stage2 동기화): "편명+출도착지 상시 라벨"에서 출도착지는
 * 모든 표시 기체에 대해 매 폴링마다 adsbdb를 조회하면 무료 공개 API에 과도한 부하가 되므로
 * 상시 라벨은 편명만, 출도착지는 클릭 시에만 조회(노선 팝업)한다. 인천/대구 ACC 관제량은
 * ACC 섹터 데이터가 필요한 3단계(FIR 분석 패널, docs/07 §향후확장) 소관이라 상태칩에서 제외.
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

const L = window.L;
const fetchJsonWithFallback = createFallbackFetcher();
const BACKOFF_THRESHOLD = 3;
const BACKOFF_INTERVAL_MS = 30000;

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
  const markersByHex = new Map();
  let timer = null;
  let consecutiveFailures = 0;
  let routeCoords = null;

  function iconFor(track) {
    return L.divIcon({
      className: "aircraft-icon-wrap",
      html: `<div class="aircraft-icon" style="transform:rotate(${Number(track) || 0}deg)">&#9992;</div>`,
      iconSize: [16, 16],
      iconAnchor: [8, 8],
    });
  }

  async function showAircraftDetail(marker, ac) {
    const popup = L.popup().setLatLng(marker.getLatLng()).setContent("불러오는 중…").openOn(map);
    const altText = ac.alt_baro === "ground" ? "지상" : `${escapeHtml(ac.alt_baro ?? "-")}ft`;
    let routeText = "";
    const callsign = ac.flight?.trim();
    if (callsign) {
      try {
        const data = await fetchJsonWithFallback(CONFIG.adsb.callsignLookupUrl.replace("{callsign}", encodeURIComponent(callsign)));
        const route = data?.response?.flightroute;
        if (route) {
          routeText = `<div>${escapeHtml(route.origin?.icao_code ?? "?")} → ${escapeHtml(route.destination?.icao_code ?? "?")}</div>`;
        }
      } catch {
        // adsbdb 조회 실패 — 노선 정보 없이 나머지 상세만 표시
      }
    }
    popup.setContent(
      `<div class="weather-popup">
        <div class="headline">${escapeHtml(callsign || ac.hex)}</div>
        <div>고도 ${altText} · 지상속도 ${escapeHtml(ac.gs ?? "-")}kt · 트랙 ${escapeHtml(ac.track ?? "-")}°</div>
        ${routeText}
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
