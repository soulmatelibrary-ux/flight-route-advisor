/**
 * 실시간 항공기(ADS-B) (docs/03 §레이어9, F8). 외부 API 직접(화이트리스트 3종, 문서 07 §4)
 * 폴링(12초, 반경 250NM 지도중심), 노란 기체 마커+편명 라벨, 클릭 시 노선(adsbdb) 조회.
 *
 * 명시적 단순화(docs/07-checklist.md Stage2 동기화): "편명+출도착지 상시 라벨"에서 출도착지는
 * 모든 표시 기체에 대해 매 폴링마다 adsbdb를 조회하면 무료 공개 API에 과도한 부하가 되므로
 * 상시 라벨은 편명만, 출도착지는 클릭 시에만 조회(노선 팝업)한다. 인천/대구 ACC 관제량은
 * ACC 섹터 데이터가 필요한 3단계(FIR 분석 패널, docs/07 §향후확장) 소관이라 상태칩에서 제외.
 */
import { createFallbackFetcher } from "../net.js";

const L = window.L;
const fetchJsonWithFallback = createFallbackFetcher();

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

export function createAdsbLayer(map, CONFIG) {
  const group = L.layerGroup();
  const markersByHex = new Map();
  let timer = null;

  function iconFor(track) {
    return L.divIcon({
      className: "aircraft-icon-wrap",
      html: `<div class="aircraft-icon" style="transform:rotate(${track ?? 0}deg)">&#9992;</div>`,
      iconSize: [16, 16],
      iconAnchor: [8, 8],
    });
  }

  async function showAircraftDetail(marker, ac) {
    const popup = L.popup().setLatLng(marker.getLatLng()).setContent("불러오는 중…").openOn(map);
    const altText = ac.alt_baro === "ground" ? "지상" : `${ac.alt_baro ?? "-"}ft`;
    let routeText = "";
    const callsign = ac.flight?.trim();
    if (callsign) {
      try {
        const data = await fetchJsonWithFallback(CONFIG.adsb.callsignLookupUrl.replace("{callsign}", encodeURIComponent(callsign)));
        const route = data?.response?.flightroute;
        if (route) routeText = `<div>${route.origin?.icao_code ?? "?"} → ${route.destination?.icao_code ?? "?"}</div>`;
      } catch {
        // adsbdb 조회 실패 — 노선 정보 없이 나머지 상세만 표시
      }
    }
    popup.setContent(
      `<div class="weather-popup">
        <div class="headline">${callsign || ac.hex}</div>
        <div>고도 ${altText} · 지상속도 ${ac.gs ?? "-"}kt · 트랙 ${ac.track ?? "-"}°</div>
        ${routeText}
        <div class="muted">${ac.t ?? ""} ${ac.r ?? ""}</div>
      </div>`,
    );
  }

  function upsert(ac) {
    if (ac.lat == null || ac.lon == null) return;
    const label = ac.flight?.trim() || ac.hex;
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

  async function poll(chipEl) {
    try {
      const center = map.getCenter();
      const list = await fetchAircraft(center.lat, center.lng, CONFIG.adsb.radiusNm, CONFIG.adsb.endpoints);
      const seen = new Set();
      for (const ac of list) {
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
    } catch {
      if (chipEl) chipEl.textContent = "ADS-B 조회 실패";
    }
  }

  function start(chipEl) {
    poll(chipEl);
    timer = setInterval(() => poll(chipEl), CONFIG.adsb.pollMs);
  }

  function stop() {
    if (timer) clearInterval(timer);
    timer = null;
  }

  return { group, start, stop };
}
