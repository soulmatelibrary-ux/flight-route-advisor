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

const EARTH_RADIUS_NM = 3440.065;

function haversineNm(lat1, lon1, lat2, lon2) {
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_NM * Math.asin(Math.sqrt(a));
}

// 노선 선택 시 지도 중심이 아니라 경로를 따라 여러 지점을 이어붙여 조회한다(사용자 요청,
// 2026-07-23) — 노선 좌표 개수가 많아도(장거리 노선) API 호출이 과도해지지 않도록 표본
// 지점 수를 CONFIG.adsb.routeSampleMaxPoints로 제한한다. 선택된 경로가 없으면 기존처럼
// 지도 중심만 쓴다.
//
// 좌표 인덱스 기준 등간격이 아니라 실제 거리(해버사인 누적 거리) 기준 등간격으로 뽑는다
// (리뷰 지적, 2026-07-23) — 항공로 좌표는 공항 인근(터미널 픽스)엔 촘촘하고 대양 횡단
// 구간엔 성긴데, 인덱스 기준으로 뽑으면 촘촘한 구간에 표본이 몰려 성긴 구간(정작 반경이
// 좁아진 뒤 사각지대가 커지는 곳)은 조회 지점이 아예 안 걸리는 문제가 있었다.
function sampleRoutePoints(coords, maxPoints) {
  if (coords.length <= maxPoints) return coords;
  const cumDist = [0];
  for (let i = 1; i < coords.length; i++) {
    cumDist.push(cumDist[i - 1] + haversineNm(coords[i - 1][0], coords[i - 1][1], coords[i][0], coords[i][1]));
  }
  const total = cumDist[cumDist.length - 1];
  const points = [];
  let searchIdx = 0;
  for (let i = 0; i < maxPoints; i++) {
    const target = (i / (maxPoints - 1)) * total;
    while (searchIdx < cumDist.length - 1 && cumDist[searchIdx + 1] < target) searchIdx++;
    points.push(coords[searchIdx]);
  }
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
  // 노선 미선택 시 폴링 기준점(사용자 요청, 2026-07-23) — 기존엔 map.getCenter()라
  // 결정포커스 기본 상태에서도 사용자가 지도를 패닝하면 인천FIR 실시간 항적이 조용히
  // 사라졌다. main.js가 boot 시 홈FIR 좌표로 설정해 두면, 노선을 고르지 않은 기본
  // 상태에서는 지도를 어디로 옮기든 계속 이 좌표를 폴링 기준으로 쓴다.
  let homeCenter = null;
  let routeGuessSeq = 0; // 팝업을 빠르게 여러 번 열 때 오래된 응답이 늦게 도착해 최신 추정선을 덮어쓰지 않도록

  // 지도 라벨(상시 표시)용 편명→"ICN→BKK" 캐시. 값이 ''이면 조회 완료·노선 없음(재조회 방지),
  // 키가 아예 없으면 아직 조회 전(fetchRouteCodes 대상).
  const routeCodes = new Map();
  let routeCodesBusy = false;

  // 근접 경고(STCA)·동고도 조우 예측(CPA) — 완성본 PORTING_PACKAGE_ROOT detectStca() 이식
  // (사용자 요청, 2026-07-23). 레이어 컨트롤 체크박스 2개(setStcaEnabled/setCpaEnabled)로
  // 독립 토글, 기본은 둘 다 꺼짐(계산 비용·화면 혼잡 방지).
  const acByHex = new Map(); // hex → 최신 원시 ac(고도/속도/트랙 등, computeAlerts 입력)
  let stcaEnabled = false;
  let cpaEnabled = false;
  let stcaPrevDistance = new Map(); // 쌍(hex1|hex2 정렬) → 직전 사이클 수평거리(NM), "접근 중" 판정용
  let cpaSel = null; // 사용자가 조우 목록에서 클릭해 선택한 쌍(지도 강조 + 지도 이동용)
  let lastStcaPairs = [];
  let lastCpaPairs = [];
  // 근접 경고 쌍 연결선. 완성본의 show.STCA/show.AC(실시간 항공기 마커)가 서로 독립
  // 토글인 것과 동일하게, 이 레이어도 "실시간 항공기 ADS-B" 체크박스(adsb.group)와 무관하게
  // stcaEnabled만으로 켜진다(리뷰에서 지적된 부분 — 항공기 아이콘을 꺼둔 채 근접 경고만
  // 켜면 연결선만 떠 있는 상태가 되는데, 의도된 동작임을 명시). 항상 map에 addTo하고
  // 내용은 computeAlerts()가 stcaEnabled/cpaEnabled에 따라 채우거나 비운다.
  const stcaLinesGroup = L.layerGroup().addTo(map);

  /** alertLevel: null | "caution" | "warn"(근접 경고 STCA) | "cpa"(선택된 동고도 조우 쌍) —
   * 원(circle)은 회전 대칭이라 부모 div의 rotate(track)에 영향받지 않고 항상 정원으로 보인다. */
  function iconFor(track, isGround, alertLevel) {
    const fill = isGround ? CONFIG.tokens.aircraftGround : CONFIG.tokens.aircraftYellow;
    const ringColor =
      alertLevel === "cpa"
        ? CONFIG.tokens.cpaPurple
        : alertLevel === "warn"
          ? CONFIG.tokens.hazardRed
          : alertLevel === "caution"
            ? CONFIG.tokens.stcaCaution
            : null;
    const ring = ringColor ? `<circle cx="0" cy="0" r="11" fill="none" stroke="${ringColor}" stroke-width="2"/>` : "";
    const svg =
      `<svg width="28" height="28" viewBox="-14 -14 28 28">` +
      ring +
      `<path d="${PLANE_PATH}" fill="none" stroke="${CONFIG.tokens.aircraftHalo}" stroke-width="2.6" stroke-linejoin="round"/>` +
      `<path d="${PLANE_PATH}" fill="${fill}" stroke="${CONFIG.tokens.aircraftOutline}" stroke-width="1.1" stroke-linejoin="round"/>` +
      `</svg>`;
    return L.divIcon({
      className: "aircraft-icon-wrap",
      html: `<div class="aircraft-icon" style="transform:rotate(${Number(track) || 0}deg)">${svg}</div>`,
      iconSize: [28, 28],
      iconAnchor: [14, 14],
    });
  }

  /** displayText: 라벨 1행에 보일 문자열(콜사인 없으면 hex). routeLookupKey: routeCodes
   * 캐시 조회 키(콜사인이 있을 때만 전달 — hex로는 노선을 조회할 수 없음). */
  function buildLabelHtml(displayText, routeLookupKey) {
    const display = escapeHtml(displayText);
    const routeCode = routeLookupKey ? routeCodes.get(routeLookupKey) : undefined;
    if (!routeCode) return `<div class="aircraft-label-cs">${display}</div>`;
    return `<div class="aircraft-label-cs">${display}</div><div class="aircraft-label-route">${escapeHtml(routeCode)}</div>`;
  }

  /** 완성본의 acCodes 배치 조회 이식: 사이클마다 아직 캐시에 없는 편명을 최대
   * CONFIG.adsb.routeCodeBatchSize개까지만 순차 조회(adsb.lol 우선, adsbdb 폴백)해
   * 무료 API 부하를 제한한다. 채워질 때마다 해당 편명 마커의 라벨을 즉시 갱신한다. */
  async function fetchRouteCodes() {
    if (routeCodesBusy) return;
    routeCodesBusy = true;
    try {
      const need = new Set();
      for (const marker of markersByHex.values()) {
        const cs = marker._callsign;
        if (cs && !routeCodes.has(cs)) need.add(cs);
      }
      const batch = Array.from(need).slice(0, CONFIG.adsb.routeCodeBatchSize);
      for (const cs of batch) {
        let code = null;
        try {
          const data = await fetchJsonWithFallback(CONFIG.adsb.routeCodeLookupUrl.replace("{callsign}", encodeURIComponent(cs)));
          const raw = data?._airport_codes_iata || data?.airport_codes;
          if (raw && raw !== "unknown") code = raw.replace(/-/g, "→");
        } catch {
          // adsb.lol 조회 실패 — adsbdb 폴백 시도
        }
        if (!code) {
          try {
            const data = await fetchJsonWithFallback(
              CONFIG.adsb.callsignLookupUrl.replace("{callsign}", encodeURIComponent(cs)),
            );
            const route = data?.response?.flightroute;
            if (route?.origin && route?.destination) {
              code = `${route.origin.iata_code || route.origin.icao_code}→${route.destination.iata_code || route.destination.icao_code}`;
            }
          } catch {
            // adsbdb도 실패 — 아래에서 ''로 캐시(재조회 방지, 완성본과 동일한 정책)
          }
        }
        routeCodes.set(cs, code || "");
        for (const marker of markersByHex.values()) {
          if (marker._callsign === cs) marker.setTooltipContent(buildLabelHtml(cs, cs));
        }
        await new Promise((res) => setTimeout(res, CONFIG.adsb.routeCodeBatchDelayMs));
      }
    } finally {
      routeCodesBusy = false;
    }
  }

  const DEG2RAD = Math.PI / 180;

  /** 완성본 detectStca()의 수치·판정 로직을 그대로 이식(2026-07-23). FL180 초과 기체만
   * 대상으로 (1) 현재 근접(STCA: 수평/고도 임계값, "접근 중" 판정 포함) (2) 15분 내
   * 최근접시각(CPA) 예측을 계산한다. 반환값은 hex → 아이콘 링 색상용 알림 레벨
   * ("warn"|"caution"|"cpa"|undefined). stcaLinesGroup(연결선)·lastStcaPairs/lastCpaPairs
   * (패널용)도 이 함수가 갱신한다 — 부수효과가 있는 함수라 poll()과 토글 직후 양쪽에서 호출. */
  function computeAlerts(acList) {
    const levelByHex = new Map();
    stcaLinesGroup.clearLayers();
    if (!stcaEnabled && !cpaEnabled) {
      lastStcaPairs = [];
      lastCpaPairs = [];
      return levelByHex;
    }
    const stcaCfg = CONFIG.adsb.stca;
    const cpaCfg = CONFIG.adsb.cpa;
    const candidates = acList.filter((p) => typeof p.alt_baro === "number" && p.alt_baro > stcaCfg.minAltFt);
    const prevDist = stcaPrevDistance;
    const nextPrevDist = new Map();
    const stcaPairs = [];
    if (stcaEnabled) {
      for (let i = 0; i < candidates.length; i++) {
        const a = candidates[i];
        for (let j = i + 1; j < candidates.length; j++) {
          const b = candidates[j];
          const dAlt = Math.abs(a.alt_baro - b.alt_baro);
          if (dAlt >= stcaCfg.cautionAltFt) continue;
          const dLat = (a.lat - b.lat) * 60;
          const dLon = (a.lon - b.lon) * 60 * Math.cos(((a.lat + b.lat) / 2) * DEG2RAD);
          const dNm = Math.sqrt(dLat * dLat + dLon * dLon);
          if (dNm > stcaCfg.cautionNm) continue;
          const key = [a.hex, b.hex].sort().join("|");
          const closing = prevDist.has(key) ? dNm < prevDist.get(key) - stcaCfg.closingEpsilonNm : false;
          nextPrevDist.set(key, dNm);
          const sev = dNm < stcaCfg.warnNm && dAlt < stcaCfg.warnAltFt ? 2 : 1;
          stcaPairs.push({ a, b, dNm, dAlt, closing, sev, key });
        }
      }
    }
    stcaPairs.sort((x, y) => y.sev - x.sev || x.dNm - y.dNm);
    stcaPrevDistance = nextPrevDist;

    const cpaPairs = [];
    if (cpaEnabled) {
      const lookaheadH = cpaCfg.lookaheadMin / 60;
      const minLeadH = cpaCfg.minLeadSec / 3600;
      for (let i = 0; i < candidates.length; i++) {
        const a = candidates[i];
        if (a.gs == null || a.track == null || a.gs < cpaCfg.minGsKt) continue;
        for (let j = i + 1; j < candidates.length; j++) {
          const b = candidates[j];
          if (b.gs == null || b.track == null || b.gs < cpaCfg.minGsKt) continue;
          const key = [a.hex, b.hex].sort().join("|");
          // 이미 현재 근접(STCA 수준)으로 잡힌 쌍은 CPA 목록에서 제외(완성본과 동일 —
          // "지금 가까움"과 "15분 뒤 가까워짐"을 중복 보고하지 않음)
          if (nextPrevDist.has(key) && nextPrevDist.get(key) <= stcaCfg.cautionNm && Math.abs(a.alt_baro - b.alt_baro) < stcaCfg.cautionAltFt) {
            continue;
          }
          const midR = ((a.lat + b.lat) / 2) * DEG2RAD;
          const rx = (b.lon - a.lon) * 60 * Math.cos(midR);
          const ry = (b.lat - a.lat) * 60;
          const vax = a.gs * Math.sin(a.track * DEG2RAD);
          const vay = a.gs * Math.cos(a.track * DEG2RAD);
          const vbx = b.gs * Math.sin(b.track * DEG2RAD);
          const vby = b.gs * Math.cos(b.track * DEG2RAD);
          const vx = vbx - vax;
          const vy = vby - vay;
          const v2 = vx * vx + vy * vy;
          if (v2 < cpaCfg.minClosingKt ** 2) continue; // 상대속도 미달 — 거의 평행 비행
          const t = -(rx * vx + ry * vy) / v2; // CPA까지 시간(h)
          if (t <= minLeadH || t > lookaheadH) continue;
          const cx = rx + vx * t;
          const cy = ry + vy * t;
          const dCpa = Math.sqrt(cx * cx + cy * cy);
          if (dCpa > cpaCfg.maxNm) continue;
          const ra = a.baro_rate || a.geom_rate || 0;
          const rb = b.baro_rate || b.geom_rate || 0;
          const altA = a.alt_baro + ra * t * 60;
          const altB = b.alt_baro + rb * t * 60;
          const dAltC = Math.abs(altA - altB);
          if (dAltC >= cpaCfg.maxAltFt) continue;
          const pa = [a.lat + (vay * t) / 60, a.lon + (vax * t) / (60 * Math.cos(midR))];
          const pb = [b.lat + (vby * t) / 60, b.lon + (vbx * t) / (60 * Math.cos(midR))];
          cpaPairs.push({ a, b, tMin: Math.round(t * 60), dCpa, dAltC: Math.round(dAltC), pa, pb, key });
        }
      }
    }
    cpaPairs.sort((x, y) => x.tMin - y.tMin);
    // 선택된 조우 쌍이 이번 사이클에도 조건을 만족하면 유지, 아니면 선택 해제(완성본과 동일)
    if (cpaSel) cpaSel = cpaPairs.find((p) => p.key === cpaSel.key) || null;

    lastStcaPairs = stcaPairs;
    lastCpaPairs = cpaPairs;

    for (const p of stcaPairs) {
      const level = p.sev === 2 ? "warn" : "caution";
      // 한 기체가 여러 쌍에 걸리면 더 심각한 레벨(warn)이 우선(caution을 덮어씀, 그 반대는 안 함)
      if (levelByHex.get(p.a.hex) !== "warn") levelByHex.set(p.a.hex, level);
      if (levelByHex.get(p.b.hex) !== "warn") levelByHex.set(p.b.hex, level);
      L.polyline(
        [
          [p.a.lat, p.a.lon],
          [p.b.lat, p.b.lon],
        ],
        {
          color: p.sev === 2 ? CONFIG.tokens.hazardRed : CONFIG.tokens.stcaCaution,
          weight: p.sev === 2 ? 2.5 : 1.5,
          dashArray: p.sev === 2 ? null : "6,4",
          opacity: 0.85,
        },
      ).addTo(stcaLinesGroup);
    }
    // 선택된 CPA 쌍은 보라 링으로 최우선 강조(무조건 덮어씀 — 사용자가 명시적으로 클릭한 쌍)
    if (cpaSel) {
      levelByHex.set(cpaSel.a.hex, "cpa");
      levelByHex.set(cpaSel.b.hex, "cpa");
    }
    return levelByHex;
  }

  /** #stca-panel에 근접 경고/동고도 조우 목록을 렌더링(완성본 renderStcaBox() 이식).
   * 콜사인 등 외부 문자열은 전부 escapeHtml — 이 패널도 클릭 없이 상시 렌더되므로 다른
   * ADS-B 라벨과 동일한 XSS 방어 원칙을 적용한다. */
  function renderAlertPanel() {
    const panel = document.getElementById("stca-panel");
    if (!panel) return;
    let html = "";
    if (stcaEnabled && lastStcaPairs.length) {
      const cfg = CONFIG.adsb.stca;
      html +=
        `<div class="stca-panel-header">⚠ 근접 경고 — 참고용 (FL${Math.round(cfg.minAltFt / 100)}+ · ` +
        `주의 ${cfg.cautionNm}NM/${cfg.cautionAltFt}ft · 경고 ${cfg.warnNm}NM/${cfg.warnAltFt}ft)</div>`;
      html += lastStcaPairs
        .slice(0, 4)
        .map((p) => {
          const csA = escapeHtml((p.a.flight || p.a.hex).trim());
          const csB = escapeHtml((p.b.flight || p.b.hex).trim());
          return (
            `<div class="stca-row ${p.sev === 2 ? "warn" : "caution"}"><b>${csA}</b> ↔ <b>${csB}</b>` +
            `<span class="stca-meta">${p.dNm.toFixed(1)}NM / ${Math.round(p.dAlt)}ft${p.closing ? " · 접근 중" : ""}</span></div>`
          );
        })
        .join("");
    }
    if (cpaEnabled && lastCpaPairs.length) {
      const cfg = CONFIG.adsb.cpa;
      html += `<div class="stca-panel-header cpa">◇ 동고도 조우 예측 (${cfg.lookaheadMin}분 내 · CPA ${cfg.maxNm}NM/${cfg.maxAltFt}ft)</div>`;
      html += lastCpaPairs
        .slice(0, 3)
        .map((p, i) => {
          const csA = escapeHtml((p.a.flight || p.a.hex).trim());
          const csB = escapeHtml((p.b.flight || p.b.hex).trim());
          return (
            `<div class="stca-row cpa" data-cpa-idx="${i}"><b>${csA}</b> ↔ <b>${csB}</b>` +
            `<span class="stca-meta">${p.tMin}분 후 ${p.dCpa.toFixed(1)}NM / ${p.dAltC}ft</span></div>`
          );
        })
        .join("");
    }
    if (!html) {
      panel.hidden = true;
      panel.innerHTML = "";
      return;
    }
    panel.hidden = false;
    panel.innerHTML = html;
    panel.querySelectorAll(".stca-row.cpa").forEach((el) => {
      el.addEventListener("click", () => {
        const pair = lastCpaPairs[Number(el.dataset.cpaIdx)];
        if (!pair) return;
        cpaSel = pair;
        map.setView([(pair.pa[0] + pair.pb[0]) / 2, (pair.pa[1] + pair.pb[1]) / 2], Math.max(map.getZoom(), 8));
        // 다음 폴링을 기다리지 않고 즉시 보라 링 반영(완성본의 redraw() 즉시호출과 동일 취지)
        for (const hex of [pair.a.hex, pair.b.hex]) {
          const marker = markersByHex.get(hex);
          const ac = acByHex.get(hex);
          if (marker && ac) marker.setIcon(iconFor(ac.track, ac.alt_baro === "ground", "cpa"));
        }
      });
    });
  }

  /** 체크박스로 STCA/CPA를 켜고 끌 때 다음 폴링(최대 12초)을 기다리지 않고 즉시
   * 재계산·재렌더한다 — 꺼짐→링/연결선/패널 즉시 사라짐, 켜짐→즉시 표시. */
  function recomputeAlertsNow() {
    const levelByHex = computeAlerts(Array.from(acByHex.values()));
    for (const [hex, marker] of markersByHex) {
      const ac = acByHex.get(hex);
      if (!ac) continue;
      marker.setIcon(iconFor(ac.track, ac.alt_baro === "ground", levelByHex.get(hex)));
    }
    renderAlertPanel();
  }

  function setStcaEnabled(enabled) {
    stcaEnabled = enabled;
    if (!enabled) stcaPrevDistance = new Map();
    recomputeAlertsNow();
  }

  function setCpaEnabled(enabled) {
    cpaEnabled = enabled;
    if (!enabled) cpaSel = null;
    recomputeAlertsNow();
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

  function upsert(ac, alertLevel) {
    if (ac.lat == null || ac.lon == null) return;
    const callsign = ac.flight?.trim() || "";
    const isGround = ac.alt_baro === "ground";
    const labelHtml = buildLabelHtml(callsign || ac.hex, callsign || null);
    acByHex.set(ac.hex, ac);
    let marker = markersByHex.get(ac.hex);
    if (!marker) {
      marker = L.marker([ac.lat, ac.lon], { icon: iconFor(ac.track, isGround, alertLevel) });
      marker._callsign = callsign;
      marker.bindTooltip(labelHtml, { permanent: true, direction: "right", className: "aircraft-label", offset: [8, 0] });
      marker.on("click", () => showAircraftDetail(marker, ac));
      marker.addTo(group);
      markersByHex.set(ac.hex, marker);
    } else {
      marker.setLatLng([ac.lat, ac.lon]);
      marker.setIcon(iconFor(ac.track, isGround, alertLevel));
      marker._callsign = callsign;
      marker.setTooltipContent(labelHtml);
    }
  }

  function prune(seenHexes) {
    for (const [hex, marker] of markersByHex) {
      if (!seenHexes.has(hex)) {
        group.removeLayer(marker);
        markersByHex.delete(hex);
        acByHex.delete(hex);
      }
    }
  }

  function pollCenters() {
    if (routeCoords && routeCoords.length > 0) {
      return sampleRoutePoints(routeCoords, CONFIG.adsb.routeSampleMaxPoints).map(([lat, lon]) => ({ lat, lon }));
    }
    if (homeCenter) return [homeCenter];
    const c = map.getCenter();
    return [{ lat: c.lat, lon: c.lng }];
  }

  // 완전 장애(모든 엔드포인트/프록시 응답 없음)로 한 poll()이 pollMs(12초)보다 오래
  // 걸리면 setInterval이 다음 poll()을 또 발사해 여러 poll()이 겹쳐 실행되고, 서로의
  // prune(seen)이 상대방이 방금 추가한 마커를 지우는 경쟁 조건이 있었다(리뷰 지적,
  // 2026-07-23 — net.js 타임아웃 도입으로 무한 hang은 없어졌지만 "느려서 겹치는" 경우는
  // 남아 있었음). 진행 중인 poll()이 있으면 이번 tick은 건너뛴다.
  let pollInFlight = false;

  async function poll(chipEl) {
    if (pollInFlight) return;
    pollInFlight = true;
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
      const validAc = Array.from(merged.values()).filter((ac) => ac.lat != null && ac.lon != null);
      // 아이콘 링(경고 레벨)은 이번 사이클 전체 기체를 놓고 계산해야 하므로 upsert 전에 먼저 구한다.
      const alertLevels = computeAlerts(validAc);
      const seen = new Set();
      for (const ac of validAc) {
        upsert(ac, alertLevels.get(ac.hex));
        seen.add(ac.hex);
      }
      prune(seen);
      renderAlertPanel();
      fetchRouteCodes().catch(() => {}); // 백그라운드 배치 캐시 충전 — 폴링 자체를 막지 않음
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
    } finally {
      pollInFlight = false;
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

  /** main.js가 boot 시 홈FIR(인천) 좌표로 1회 설정 — 노선 미선택 기본 상태의 폴링
   * 기준점(pollCenters 참고). */
  function setHomeCenter(latlon) {
    homeCenter = latlon;
  }

  return { group, start, stop, setRouteCoords, setHomeCenter, setStcaEnabled, setCpaEnabled };
}
