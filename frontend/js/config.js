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
  // 외부 API fetch 공통 타임아웃(net.js) — 응답 없는 요청이 무한정 pending 상태로 남아
  // 호출부의 동시실행 가드(예: layers/adsb.js의 routeCodesBusy)를 영구히 잠그는 문제 방지
  // (리뷰 지적, 2026-07-23). 완성본 PORTING_PACKAGE_ROOT도 개별 fetch에 6000ms를 씀.
  netTimeoutMs: 8000,
  tileUrl: "https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png",
  map: {
    center: [30, 127],
    zoom: 3,
    minZoom: 2,
    maxBounds: [
      [-78, -400],
      [85, 400],
    ],
    // "지역 컨텍스트" 뷰모드(F9)의 fitBounds 범위 — 인천 FIR 인접 권역 근사(단순화,
    // docs/07-checklist.md Stage2 동기화). 하드코딩 금지 원칙상 viewmode.js가 아니라
    // 여기 config에 둔다.
    regionContextBounds: [
      [20, 110],
      [45, 145],
    ],
  },
  display: {
    waypointLimit: 800,
    labelZoom: { fir: 3, firKo: 4, tca: 7, airway: 7, fix: 7, airportIcao: 8, navaid: 8 },
    // 원본 문서(03)는 "저배율은 민간/공용만"만 규정하고 구체적 줌 임계값은 없다(docs/07-checklist.md
    // Stage1 항목이 프론트 연동 시 확정하도록 남긴 갭) — 여기서 5(대륙/월드 뷰)로 확정한다.
    airportFullTypeZoom: 5,
    airportLowZoomTypes: ["A", "B"],
    minimap: { zoom: 1 },
    // 전세계/지역 컨텍스트에서 항로/픽스/항행시설 전량을 그대로 보여주면 너무 번잡하다는
    // 피드백(2026-07-23) — 우리나라(FIR·픽스 country 코드)는 항상 보여주고, 나머지는
    // 선택된 경로의 경유 FIR 반경(bbox)에 들 때만 보여준다(main.js filterByRelevantFirs).
    homeFirIcao: "RKRR",
    homeWaypointCountry: "KS",
    // 픽스 마커 반경(px) — 자국(우리나라)과 외국을 다르게(외국은 더 작게)
    waypointRadius: { home: 1.5, foreign: 0.8 },
    // 지연율 상대비교 배지("지연 최저"/"상대적 혼잡")는 편수가 이 값 미만인 옵션에는
    // 아예 안 붙인다 — 1~2편짜리 표본에서 지연 1건이 "100%·혼잡"으로 과장돼 보이는
    // 문제(사용자 확정, 2026-07-23) 방지. route-panel.js에서 사용.
    minSampleForCongestionTag: 5,
    // 경로 1(baseline) 대비 다른 옵션이 "달라진 구간"으로 판정되는 근접 임계(NM, 사용자
    // 요청 2026-07-23 — route.js splitByBaseline). 레이더 트랙 좌표는 이름 붙은 픽스가
    // 아니라 표본점이라 정확한 경로 일치 판정 대신 근접도로 근사한다. 항로 측면 분리
    // 기준(수 NM)보다 넉넉히 잡아 트랙 표본 잡음으로 인한 오탐(공유 구간을 "다름"으로
    // 잘못 표시)을 줄인다.
    routeDiffThresholdNm: 20,
  },
  tokens: {
    ink: "#22303c",
    inkSoft: "#7a8a99",
    paper: "#fbfbf9",
    orange: "#e8590c",
    blue: "#1d5fae",
    // SID/STAR(원본 문서/08 §SS: 파랑=SID, 녹색=STAR) 전용
    green: "#2e8b57",
    // SIGMET(위험기상) 전용 — orange는 이미 경로 경유 FIR 하이라이트(route.js)·미니맵
    // 뷰포트 표시에 쓰여 위험기상을 켜면 구분이 안 된다는 피드백(2026-07-23)으로 분리.
    hazardRed: "#c92a2a",
    // 경로 1(baseline) 대비 다른 옵션이 갈라지는 구간 전용(사용자 요청, 2026-07-23) —
    // hazardRed와 같은 "경고" 계열이지만 하나는 면(SIGMET 폴리곤), 하나는 선(경로 diff)이라
    // 실제로 겹쳐 보일 일은 없다. 그래도 의미가 다르므로 별도 토큰으로 분리.
    routeDiffRed: "#e03131",
    // 항공기 실루엣(완성본 FR24 스타일 이식, PORTING_PACKAGE_ROOT 참고) 전용
    aircraftYellow: "#f7c440",
    aircraftGround: "#aeb7bf",
    aircraftOutline: "#4a5560",
    aircraftHalo: "rgba(255,255,255,0.95)",
    // 상층풍 연직시어(A3) 전용 — orange/hazardRed와 별개 토큰(2026-07-23 SIGMET 색상충돌
    // 교훈과 동일한 이유: 경로선 위에 그려지는 시어 색이 다른 레이어와 의미가 섞이면 안 됨)
    shearWeak: "#2e7d32",
    shearModerate: "#e8590c",
    shearStrong: "#d62828",
    // 근접 경고(STCA) "주의"(10NM/5,000ft) 전용 — "경고"(5NM/2,000ft)는 hazardRed 재사용
    // (완성본도 위험색 하나를 severity 구분 없이 그대로 씀, 여기선 orange와 시각 충돌
    // 방지를 위해 별도 amber 톤 신설). 동고도 조우 예측(CPA) 선택 쌍 강조는 cpaPurple
    // (완성본 ctx.strokeStyle='#8e24aa'와 동일, PORTING_PACKAGE_ROOT 이식 2026-07-23).
    stcaCaution: "#f08c00",
    cpaPurple: "#8e24aa",
  },
  adsb: {
    pollMs: 12000,
    // 지도 중심/노선 표본 지점 기준 조회 반경. 250NM은 너무 멀리까지 잡혀 노선과 무관한
    // 항공기가 다수 표시된다는 피드백(사용자 요청, 2026-07-23) — 100NM으로 축소.
    radiusNm: 100,
    // 화이트리스트(기상서버 07 문서 §4 프록시 화이트리스트와 정합) — 순서대로 폴백 시도
    endpoints: [
      "https://api.adsb.lol/v2/point/{lat}/{lon}/{radiusNm}",
      "https://opendata.adsb.fi/api/v2/point/{lat}/{lon}/{radiusNm}",
      "https://api.airplanes.live/v2/point/{lat}/{lon}/{radiusNm}",
    ],
    callsignLookupUrl: "https://api.adsbdb.com/v0/callsign/{callsign}",
    // 지도 라벨(상시 표시)용 출발→도착 코드 캐시 조회 — adsb.lol 우선, 실패 시 adsbdb 폴백
    // (완성본 PORTING_PACKAGE_ROOT의 acCodes 배치 조회 로직 이식, 사용자 요청 2026-07-23)
    routeCodeLookupUrl: "https://api.adsb.lol/api/0/route/{callsign}",
    routeCodeBatchSize: 12, // 폴링 사이클당 조회할 편명 수 상한(무료 API 부하 제한)
    routeCodeBatchDelayMs: 250, // 배치 내 요청 간 간격
    // 노선 선택 시 표본 조회 지점 수 상한(리뷰 지적으로 CONFIG.adsb 이동, 2026-07-23 —
    // 이전엔 adsb.js 모듈 상수로 하드코딩돼 있었음). layers/adsb.js의 sampleRoutePoints
    // 참고.
    routeSampleMaxPoints: 6,
    // 근접 경고(STCA)·동고도 조우 예측(CPA) 임계값 — 완성본 PORTING_PACKAGE_ROOT의
    // detectStca() 수치를 그대로 이식(2026-07-23, 사용자 요청). 하드코딩 금지 원칙상
    // layers/adsb.js에 매직넘버로 두지 않고 여기로 뺌.
    stca: {
      minAltFt: 18000, // FL180 초과 항공기만 후보(완성본과 동일)
      cautionNm: 10, // 주의: 수평 10NM 이내
      cautionAltFt: 5000, // 주의: 고도차 5,000ft 미만
      warnNm: 5, // 경고: 수평 5NM 이내
      warnAltFt: 2000, // 경고: 고도차 2,000ft 미만
      closingEpsilonNm: 0.05, // "접근 중" 판정 — 직전 폴링 대비 이 값 이상 좁혀졌으면 closing
    },
    cpa: {
      lookaheadMin: 15, // 15분 내 최근접시각(CPA)만 대상
      minLeadSec: 30, // 30초 미만은 사실상 지금 상황(STCA)이라 CPA 목록에서 제외
      maxNm: 8, // CPA 시점 수평거리 8NM 이내만 "조우"로 인정
      maxAltFt: 1000, // CPA 시점 예측 고도차 1,000ft 미만
      minGsKt: 80, // 지상속도 80kt 미만(지상 활주 등)은 제외
      minClosingKt: 10, // 상대속도 10kt 미만(거의 평행비행)은 제외
    },
  },
  weather: {
    // 지도의 AWC 호출 폴백 체인(직접 → 로컬 프록시 → 공개 프록시), 성공 경로 기억(문서 03/05/07)
    metarUrl: "https://aviationweather.gov/api/data/metar",
    tafUrl: "https://aviationweather.gov/api/data/taf",
    // SIGMET/PIREP도 같은 AWC 호스트라 CORS 사정이 동일(직접 호출 실측 시 CORS 헤더
    // 없음 확인, 2026-07-23) — metar/taf와 동일한 폴백 체인을 그대로 탄다.
    sigmetUrl: "https://aviationweather.gov/api/data/isigmet",
    pirepUrl: "https://aviationweather.gov/api/data/pirep",
    publicProxies: [
      "https://corsproxy.io/?url=",
      "https://api.allorigins.win/raw?url=",
    ],
  },
  // 기상 레이더(RainViewer, docs/10 §2.5 레이어⑤·원본 문서/01 §RainViewer). 실측 확인:
  // api.rainviewer.com/public/weather-maps.json → radar.past(과거 2시간, ~10분 간격
  // 프레임) + tilecache.rainviewer.com 둘 다 CORS `*` 허용이라 프록시 불필요.
  radar: {
    framesUrl: "https://api.rainviewer.com/public/weather-maps.json",
    // {host}{path}/{size}/{z}/{x}/{y}/{color}/{options}.png — RainViewer 공개 타일 규약.
    // color=2(범용 블루-그린-레드), options=1_1(스무딩+눈 표시), maxNativeZoom=6(원본
    // 문서/05 트러블슈팅: z7+는 "Zoom Level Not Supported").
    tileSize: 256,
    color: 2,
    options: "1_1",
    maxNativeZoom: 6,
    opacity: 0.6,
    playIntervalMs: 500,
  },
  externalApis: {},
  // 경로 상층풍·연직시어·추천고도(A3, docs/13 STEP A3) — 완성본과 동일 소스(Open-Meteo GFS).
  wind: {
    apiUrl: "https://api.open-meteo.com/v1/gfs",
    // 기압면 앵커(완성본 WLVLS/FLANCH 그대로) — 인접 두 앵커 사이는 벡터 보간.
    levels: [
      { pressure: "700hPa", fl: 100 },
      { pressure: "500hPa", fl: 180 },
      { pressure: "400hPa", fl: 240 },
      { pressure: "300hPa", fl: 300 },
      { pressure: "250hPa", fl: 340 },
      { pressure: "200hPa", fl: 390 },
    ],
    flOdd: [290, 310, 330, 350, 370, 390], // 동행(자방위 000~179°) 순항고도 후보
    flEven: [280, 300, 320, 340, 360, 380], // 서행(180~359°) 순항고도 후보
    flLow: [100, 180, 240], // 저고도(참고용, 추천 후보 아님)
    tasKt: 460, // 진대기속도 가정치(완성본과 동일 — 배풍/정풍에 따른 소요시간 변화 계산용)
    shearModerateKt1000ft: 4, // 이 값 초과면 "보통", shearStrongKt1000ft 초과면 "강함 가능"
    shearStrongKt1000ft: 7, // 추천고도 선정 시 이 값 이하만 "안전 후보"로 고려
    sampleMinPoints: 6,
    sampleMaxPoints: 16,
    sampleDegreesPerPoint: 3, // 경로 표본지점 수 = clamp(round(총거리(도)/3), min, max)
  },
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
