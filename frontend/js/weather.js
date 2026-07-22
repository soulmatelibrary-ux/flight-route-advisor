/**
 * 공항 기상 팝업 (docs/03 §공항 기상 팝업, docs/07_기상MCP서버.md §3, F7).
 * AWC 직접 호출은 브라우저 CORS로 대개 막히므로 직접→localhost:3000/proxy→공개 프록시
 * 순으로 폴백하고 성공 경로를 기억한다(문서 03/05/07). METAR 해독·위험 판정 규칙은
 * 기상 MCP 서버 문서 §3을 그대로 따른다(재구현 계약).
 */
import { getConfig } from "./config.js";
import { createFallbackFetcher } from "./net.js";
import { escapeHtml } from "./html.js";

const fetchJsonWithFallback = createFallbackFetcher();

function pad(n) {
  return String(n).padStart(2, "0");
}

function toEpochSeconds(value) {
  if (typeof value === "number") return value;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : Math.floor(parsed / 1000);
}

/** UTC epoch(초) → "HHMMZ (KST HH:MM)" (docs/06 §3.2: 표시 시에만 UTC+9 병기). */
export function kst(value) {
  const epoch = toEpochSeconds(value);
  if (epoch == null) return "-";
  const utc = new Date(epoch * 1000);
  const utcStr = `${pad(utc.getUTCHours())}${pad(utc.getUTCMinutes())}Z`;
  const kstMillis = utc.getTime() + 9 * 3600 * 1000;
  const kstDate = new Date(kstMillis);
  return `${utcStr} (KST ${pad(kstDate.getUTCHours())}:${pad(kstDate.getUTCMinutes())})`;
}

function windLine(m) {
  if (!m.wspd) return "무풍";
  const dir = m.wdir === 0 ? "VRB" : `${m.wdir}°`;
  let s = `${dir} ${m.wspd}kt`;
  if (m.wgst) s += ` 돌풍 ${m.wgst}kt`;
  return s;
}

function visibLine(visib) {
  if (visib == null) return "시정 정보 없음";
  const str = String(visib);
  const plus = str.includes("+");
  const num = parseFloat(str);
  if (Number.isNaN(num)) return "시정 정보 없음";
  const km = num * 1.609;
  return plus ? `${Math.round(km)}km 이상` : `${km.toFixed(1)}km`;
}

function ceilLine(clouds) {
  const c = (clouds ?? []).find((row) => ["BKN", "OVC", "OVX"].includes(row.cover));
  return c ? `${c.cover} ${c.base}ft` : "실링 없음";
}

/** decodeMetar(m) — 필드 → 한국어 5줄 (문서 §3). */
export function decodeMetar(m) {
  return [
    `[${m.icaoId}] ${m.name ?? ""} ${m.fltCat ?? ""}`.trim(),
    `관측: ${kst(m.obsTime)}`,
    `${windLine(m)} · ${visibLine(m.visib)} · ${ceilLine(m.clouds)}`,
    `${m.temp ?? "-"}°C/${m.dewp ?? "-"}°C · QNH ${m.altim ?? "-"}hPa`,
    m.wxString ? m.wxString : "",
    `RAW: ${m.rawOb ?? ""}`,
  ];
}

/** riskOf(m) — 위험요소 배열 (문서 §3). */
export function riskOf(m) {
  const risks = [];
  if (m.fltCat === "LIFR") risks.push("LIFR(최악 시정/운고)");
  else if (m.fltCat === "IFR") risks.push("IFR");
  else if (m.fltCat === "MVFR") risks.push("MVFR");
  if (m.wgst >= 25) risks.push("강돌풍");
  else if (m.wspd >= 20) risks.push("강풍");
  const wx = m.wxString ?? "";
  if (/TS/.test(wx)) risks.push("뇌우");
  if (/FZ/.test(wx)) risks.push("어는 강수(착빙)");
  if (/SN|BLSN/.test(wx)) risks.push("강설");
  if (/FG/.test(wx)) risks.push("안개");
  return risks;
}

/** 직접→로컬 프록시→공개 프록시 순 폴백, 성공 경로 기억(문서 03/05/07, net.js). */
async function awc(path, params) {
  const CONFIG = getConfig();
  const base = path === "metar" ? CONFIG.weather.metarUrl : CONFIG.weather.tafUrl;
  const qs = new URLSearchParams({ format: "json", ...params }).toString();
  const data = await fetchJsonWithFallback(`${base}?${qs}`);
  return data;
}

export async function getMetar(ids) {
  const data = await awc("metar", { ids });
  return Array.isArray(data) ? data : [];
}

export async function getTaf(ids) {
  const data = await awc("taf", { ids });
  return Array.isArray(data) ? data : [];
}

const CATEGORY_THRESHOLDS = { LIFR: { visib: 1.6, ceil: 500 }, IFR: { visib: 4.8, ceil: 1000 }, MVFR: { visib: 8, ceil: 3000 } };

function categoryOf(visibKm, ceilingFt) {
  if (visibKm == null && ceilingFt == null) return null;
  for (const cat of ["LIFR", "IFR", "MVFR"]) {
    const t = CATEGORY_THRESHOLDS[cat];
    if ((visibKm != null && visibKm < t.visib) || (ceilingFt != null && ceilingFt < t.ceil)) return cat;
  }
  return "VFR";
}

/**
 * TAF 타임라인 (docs/04-frontend-migration.md §7 04-G): BECMG/FM만 기저 상태 갱신,
 * TEMPO/PROB는 일시적 오버레이로 표시하되 기저를 바꾸지 않는다.
 */
export function buildTafTimeline(fcsts) {
  const base = { visibKm: null, ceilingFt: null };
  const rows = [];
  for (const p of fcsts ?? []) {
    const visibKm = p.visib != null ? parseFloat(String(p.visib).replace("+", "")) * 1.609 : null;
    const ceilingFt = ceilLineValue(p.clouds);
    const change = p.fcstChange ?? "BASE";
    const isTempo = /TEMPO/.test(change);
    const isProb = /PROB/.test(change);
    if (!isTempo && !isProb) {
      if (visibKm != null) base.visibKm = visibKm;
      if (ceilingFt != null) base.ceilingFt = ceilingFt;
    }
    const category = categoryOf(visibKm ?? base.visibKm, ceilingFt ?? base.ceilingFt);
    rows.push({
      timeFrom: p.timeFrom,
      change,
      tempo: isTempo,
      prob: p.probability ?? null,
      wxString: p.wxString ?? "",
      category,
    });
  }
  return rows;
}

function ceilLineValue(clouds) {
  const c = (clouds ?? []).find((row) => ["BKN", "OVC", "OVX"].includes(row.cover));
  return c ? c.base : null;
}

// 이 아래(tafHtml, renderAirportWeatherInto)는 innerHTML 삽입 경계다 — decodeMetar/
// buildTafTimeline이 반환하는 값은 METAR/TAF rawOb/rawTAF/wxString 등 외부 API 원문을
// 그대로 담고 있으므로, 여기서 반드시 escapeHtml을 거친다(리뷰 지적사항, 2026-07-22).
function tafHtml(taf) {
  const rows = buildTafTimeline(taf.fcsts);
  const rowsHtml = rows
    .map(
      (r) => `<div class="taf-row${r.tempo ? " tempo" : ""}">
        <span>${escapeHtml(kst(r.timeFrom))}</span>
        <span>${escapeHtml(r.change)}${r.prob ? ` PROB${escapeHtml(r.prob)}` : ""}</span>
        <span${/LIFR|IFR/.test(r.category ?? "") ? ' class="risk"' : ""}>${escapeHtml(r.category ?? "")}</span>
        ${r.wxString ? `<span class="risk">${escapeHtml(r.wxString)}</span>` : ""}
      </div>`,
    )
    .join("");
  return `<details><summary>예보 추이 (TAF)</summary>${rowsHtml}<details><summary>TAF 원문</summary>${escapeHtml(taf.rawTAF ?? "")}</details></details>`;
}

/** 공항 클릭 → "공항 기상" 버튼 → 팝업(docs/03 §공항 기상 팝업). */
export async function renderAirportWeatherInto(container, icao) {
  container.textContent = "불러오는 중…";
  try {
    const [metars, tafs] = await Promise.all([getMetar(icao), getTaf(icao)]);
    const m = metars[0];
    if (!m) {
      container.textContent = `METAR 없음: ${icao} (관측 미실시 공항일 수 있음)`;
      return;
    }
    const lines = decodeMetar(m).map(escapeHtml);
    const risks = riskOf(m).map(escapeHtml);
    const taf = tafs[0];
    container.innerHTML = `
      <div class="headline">${lines[0]}</div>
      ${risks.length ? `<div class="risk">${risks.join(", ")}</div>` : ""}
      <div>${lines[1]}</div>
      <div>${lines[2]}</div>
      <div>${lines[3]}</div>
      ${lines[4] ? `<div class="risk">${lines[4]}</div>` : ""}
      <details><summary>METAR 원문</summary>${lines[5]}</details>
      ${taf ? tafHtml(taf) : ""}
    `;
  } catch (err) {
    container.innerHTML = `<div class="error">기상 조회 실패: ${escapeHtml(err.message)}</div>`;
  }
}

export function bindAirportWeatherButtons(map) {
  map.on("popupopen", (e) => {
    const btn = e.popup.getElement()?.querySelector("[data-weather-icao]");
    if (!btn) return;
    btn.addEventListener("click", () => {
      const icao = btn.dataset.weatherIcao;
      const container = document.createElement("div");
      container.className = "weather-popup";
      e.popup.setContent(container);
      renderAirportWeatherInto(container, icao);
    });
  });
}
