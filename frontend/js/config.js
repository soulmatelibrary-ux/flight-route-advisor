/**
 * 런타임 설정 (docs/04-frontend-migration.md §5, docs/06-conventions.md §1.2).
 *
 * 하드코딩 금지 원칙: 컴포넌트는 이 모듈이 내보내는 CONFIG 값만 참조하고,
 * URL/색상/줌 임계/표시 상한 리터럴을 직접 쓰지 않는다. DEFAULT_CONFIG는
 * 저장소 루트 config.example.json과 동일한 값을 유지한다(단일 진실원).
 * 배포 환경별 실제 값은 frontend/config.json(git 미추적, .env처럼 로컬 전용)으로
 * 덮어쓴다 — 없으면 DEFAULT_CONFIG 그대로 동작(로컬 개발 즉시 기동 가능).
 */

const DEFAULT_CONFIG = {
  apiBaseUrl: "/api",
  weatherProxyUrl: "http://localhost:3000/proxy",
  tileUrl: "https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png",
  map: {
    center: [30, 127],
    zoom: 3,
    minZoom: 2,
    maxBounds: [
      [-78, -400],
      [85, 400],
    ],
  },
  display: {
    waypointLimit: 800,
    labelZoom: { fir: 3, firKo: 4, tca: 7, airway: 7, fix: 7, airportIcao: 8, navaid: 8, suasWorld: 4 },
    // 원본 문서(03)는 "저배율은 민간/공용만"만 규정하고 구체적 줌 임계값은 없다(docs/07-checklist.md
    // Stage1 항목이 프론트 연동 시 확정하도록 남긴 갭) — 여기서 5(대륙/월드 뷰)로 확정한다.
    airportFullTypeZoom: 5,
    airportLowZoomTypes: ["A", "B"],
    minimap: { zoom: 1 },
  },
  tokens: {
    ink: "#22303c",
    inkSoft: "#7a8a99",
    paper: "#fbfbf9",
    orange: "#e8590c",
    blue: "#1d5fae",
  },
  adsb: {
    pollMs: 12000,
    radiusNm: 250,
    // 화이트리스트(기상서버 07 문서 §4 프록시 화이트리스트와 정합) — 순서대로 폴백 시도
    endpoints: [
      "https://api.adsb.lol/v2/point/{lat}/{lon}/{radiusNm}",
      "https://opendata.adsb.fi/api/v2/point/{lat}/{lon}/{radiusNm}",
      "https://api.airplanes.live/v2/point/{lat}/{lon}/{radiusNm}",
    ],
    callsignLookupUrl: "https://api.adsbdb.com/v0/callsign/{callsign}",
  },
  weather: {
    // 지도의 AWC 호출 폴백 체인(직접 → 로컬 프록시 → 공개 프록시), 성공 경로 기억(문서 03/05/07)
    metarUrl: "https://aviationweather.gov/api/data/metar",
    tafUrl: "https://aviationweather.gov/api/data/taf",
    publicProxies: [
      "https://corsproxy.io/?url=",
      "https://api.allorigins.win/raw?url=",
    ],
  },
  radar: {
    indexUrl: "https://api.rainviewer.com/public/weather-maps.json",
    frameCount: 13,
    maxNativeZoom: 6,
  },
  externalApis: {},
};

function isPlainObject(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function deepMerge(base, override) {
  if (!isPlainObject(base) || !isPlainObject(override)) return override ?? base;
  const result = { ...base };
  for (const key of Object.keys(override)) {
    result[key] = isPlainObject(base[key]) ? deepMerge(base[key], override[key]) : override[key];
  }
  return result;
}

let _config = null;

/** config.json(있으면)으로 DEFAULT_CONFIG를 덮어써 1회 로드한다. 없으면 기본값 그대로. */
export async function loadConfig() {
  if (_config) return _config;
  let overrides = {};
  try {
    const res = await fetch("./config.json", { cache: "no-store" });
    if (res.ok) overrides = await res.json();
  } catch {
    // config.json 없음/네트워크 오류 — 기본값으로 계속 진행(로컬 개발 편의)
  }
  _config = deepMerge(DEFAULT_CONFIG, overrides);
  return _config;
}

/** loadConfig() 완료 후에만 호출 가능. */
export function getConfig() {
  if (!_config) throw new Error("config not loaded — loadConfig()를 먼저 await 할 것");
  return _config;
}
