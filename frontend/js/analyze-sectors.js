/**
 * 실시간 섹터 교통·수요예측 (docs/13-ai-reasoning-dev-plan.md STEP A4). 완성본 `analyzeFIR`의
 * 핵심(항공기 → ACC 섹터 배정, 속도·방향으로 +10/+40분 위치 외삽해 섹터별 미래 수요 예측)을
 * 그대로 포팅했다. 순수 계산 함수(`sectorDemand` 등)와 DOM 렌더링을 분리해 전자는 합성
 * 입력으로 단위 검증 가능하게 했다(doc13 STEP A4 수용기준 (1)).
 *
 * **범위를 좁힌 부분(정직하게 명시, docs/07-checklist.md A4 항목 참고)**: 완성본 analyzeFIR은
 * 섹터별 레이더 기상 샘플링(dBZ)·회피(avoid) 판정·유사호출부호 쌍도 함께 계산했지만, 이번
 * 포팅은 doc13 STEP A4의 수용기준 3개(섹터별 현재/예측 대수·등급, 통과 섹터 표시, ADS-B
 * 미가용 시 degrade)에 명시된 **교통량만** 다룬다. 기상 결합은 A5(세그먼트 병목 종합, A1·A3·A4를
 * 묶는 단계)로 미루고, 유사호출부호는 사용자가 이번 라운드 범위에서 명시적으로 제외한
 * 별도 항목(docs/07-checklist.md "보류" 목록)이라 포함하지 않는다.
 *
 * 섹터 데이터(`acc_sectors.json`→`/api/reference/acc-sectors`)는 한국(인천·대구 ACC) 14개만
 * 커버하는 정적 자산이라, 이 데이터 한계상 이 기능은 사실상 한국 상공을 지나는 경로에서만
 * 의미 있는 값을 낸다(다른 지역 좌표는 어떤 섹터에도 매칭되지 않아 조용히 빈 결과가 된다 —
 * 임의로 다른 지역 섹터를 지어내지 않는다, 허위 정보 생성 금지 원칙).
 */
import { api } from "./api.js";
import { pointInPolygon } from "./geo.js";
import { toAccSector } from "./adapters.js";

const EARTH_RADIUS_NM = 3440.065;

/** 완성본 extrap() 이식 — 대권(great-circle) 외삽. gs<50이거나 gs/track 결측이면 null. */
export function extrapolatePosition(ac, minutes) {
  if (ac.gs == null || ac.track == null || ac.gs < 50) return null;
  const d = (ac.gs * minutes) / 60 / EARTH_RADIUS_NM;
  const la1 = (ac.lat * Math.PI) / 180;
  const lo1 = (ac.lon * Math.PI) / 180;
  const br = (ac.track * Math.PI) / 180;
  const la2 = Math.asin(Math.sin(la1) * Math.cos(d) + Math.cos(la1) * Math.sin(d) * Math.cos(br));
  const lo2 = lo1 + Math.atan2(Math.sin(br) * Math.sin(d) * Math.cos(la1), Math.cos(d) - Math.sin(la1) * Math.sin(la2));
  return [(la2 * 180) / Math.PI, (((lo2 * 180) / Math.PI + 540) % 360) - 180];
}

/** 첫 매치 배정(완성본과 동일 — 배열 순서상 먼저 오는 섹터가 우선, GH/GL처럼 폴리곤이
 * 겹치는 섹터 쌍이 있어 순서가 결과에 영향을 준다. sectors는 서버가 seq 오름차순으로 준다). */
export function assignSector(lat, lon, sectors) {
  for (const s of sectors) {
    if (pointInPolygon(lat, lon, s.polygon)) return s.sectorId;
  }
  return null;
}

/** 완성본 trafficGrade()와 동일 임계 — [label, CONFIG.tokens 키]. */
export function trafficGrade(n, trafficThresholds) {
  const [moderateMin, heavyMin] = trafficThresholds;
  if (n >= heavyMin) return ["혼잡", "trafficHeavy"];
  if (n >= moderateMin) return ["보통", "trafficModerate"];
  return ["원활", "trafficLight"];
}

/** 경로 좌표([[lat,lon],...])가 지나는 섹터 id 목록(최초 등장 순서, 중복 제거) — 완성본
 * routeSectorIds() 이식. */
export function routeSectorIds(coords, sectors) {
  const out = [];
  for (const [lat, lon] of coords) {
    const sid = assignSector(lat, lon, sectors);
    if (sid != null && !out.includes(sid)) out.push(sid);
  }
  return out;
}

/**
 * 섹터별 현재/+10분/+40분 수요 + 등급 + 추세(순수 함수, 부수효과 없음 — 단위 테스트 대상).
 * aircraft: adsb.js가 주는 원시 ac 배열([{lat,lon,gs,track,alt_baro},...]). null이면(ADS-B
 * 미가용) 호출부(createSectorPanel)가 별도로 처리하므로 이 함수에는 항상 배열만 들어온다.
 */
export function sectorDemand(aircraft, sectors, sectorsConfig) {
  const [min1, min2] = sectorsConfig.forecastMinutes;
  const current = new Map(sectors.map((s) => [s.sectorId, 0]));
  const future1 = new Map(sectors.map((s) => [s.sectorId, 0]));
  const future2 = new Map(sectors.map((s) => [s.sectorId, 0]));

  for (const ac of aircraft) {
    if (ac.alt_baro === "ground" || ac.lat == null || ac.lon == null) continue;
    const sid = assignSector(ac.lat, ac.lon, sectors);
    if (sid != null) current.set(sid, current.get(sid) + 1);

    const p1 = extrapolatePosition(ac, min1);
    if (p1) {
      const sid1 = assignSector(p1[0], p1[1], sectors);
      if (sid1 != null) future1.set(sid1, future1.get(sid1) + 1);
    }
    const p2 = extrapolatePosition(ac, min2);
    if (p2) {
      const sid2 = assignSector(p2[0], p2[1], sectors);
      if (sid2 != null) future2.set(sid2, future2.get(sid2) + 1);
    }
  }

  return sectors.map((s) => {
    const n = current.get(s.sectorId);
    const f1 = future1.get(s.sectorId);
    const f2 = future2.get(s.sectorId);
    let trend = "flat";
    if (f1 > n + sectorsConfig.trendDelta) trend = "up";
    else if (f1 < n - sectorsConfig.trendDelta) trend = "down";
    return {
      sectorId: s.sectorId,
      nameEn: s.nameEn,
      acc: s.acc,
      current: n,
      future10: f1,
      future40: f2,
      trend,
      grade: trafficGrade(n, sectorsConfig.trafficThresholds),
    };
  });
}

function line(text, cls) {
  const div = document.createElement("div");
  div.textContent = text;
  if (cls) div.className = cls;
  return div;
}

const TREND_ARROW = { up: "▲", down: "▼", flat: "" };

/** 지도와 무관하게 패널(#sector-panel)만 관리 — 완성본과 달리 섹터 폴리곤 자체는 지도에
 * 그리지 않는다(결정 중심 원칙, 통과 섹터의 수치만 필요). main.js가 store 이벤트로 호출. */
export function createSectorPanel(CONFIG) {
  const panelEl = document.getElementById("sector-panel");
  const sectorsConfig = CONFIG.sectors;

  let sectorsPromise = null;
  let seq = 0;
  let currentSectorIds = null; // 선택된 경로가 지나는 섹터 id 목록(null=선택 없음)
  let lastAircraft = undefined; // undefined=아직 스냅샷 없음, null=ADS-B 미가용, []=0대
  let lastDemand = null; // 통과 섹터로 필터링된 마지막 sectorDemand 결과 — getDemand()가 노출(A5 소비용)

  function loadSectors() {
    if (!sectorsPromise) {
      sectorsPromise = api.accSectors().then((res) => res.data.sectors.map(toAccSector));
      // 실패한 조회 결과는 캐시하지 않는다 — 안 그러면 일시적 503/네트워크 오류 한 번으로
      // 이 세션 내내(페이지 새로고침 전까지) 섹터 패널이 영구 고장 상태가 된다(리뷰 지적,
      // 2026-07-24). 다음 update()/recompute() 호출이 자연스럽게 재시도하도록 초기화.
      sectorsPromise.catch(() => {
        sectorsPromise = null;
      });
    }
    return sectorsPromise;
  }

  function clearPanel() {
    if (panelEl) {
      panelEl.hidden = true;
      panelEl.innerHTML = "";
    }
  }

  function renderRows(sectors, demand) {
    if (!panelEl) return;
    panelEl.hidden = false;
    panelEl.innerHTML = "";
    panelEl.append(line("선택 경로 통과 섹터 — 실시간 교통(ADS-B)"));

    if (lastAircraft === null) {
      panelEl.append(line("실시간 교통 데이터 없음(ADS-B 미가용)"));
      return;
    }
    if (!currentSectorIds || currentSectorIds.length === 0) {
      panelEl.append(line("경로가 지나는 섹터 데이터 없음(한국 인천·대구 ACC 권역만 커버)"));
      return;
    }
    const bySid = new Map(demand.map((d) => [d.sectorId, d]));
    for (const sid of currentSectorIds) {
      const d = bySid.get(sid);
      if (!d) continue;
      const [gradeLabel, gradeKey] = d.grade;
      const row = document.createElement("div");
      row.className = "sector-row";
      const nameSpan = document.createElement("span");
      nameSpan.textContent = `${d.nameEn ?? d.sectorId} (${d.sectorId})`;
      row.append(nameSpan);
      const badge = document.createElement("span");
      badge.className = "sector-grade";
      badge.style.backgroundColor = CONFIG.tokens[gradeKey];
      badge.textContent = `${d.current} · ${gradeLabel}`;
      row.append(badge);
      const trendSpan = document.createElement("span");
      trendSpan.textContent = `+${sectorsConfig.forecastMinutes[0]}분 ${d.future10} ${TREND_ARROW[d.trend]}`;
      row.append(trendSpan);
      panelEl.append(row);
    }
  }

  /** async — A5(route-bottlenecks.js)가 update() 완료 후 getDemand()를 안정적으로 읽을 수
   * 있도록 update()가 이 프로미스를 await한다(내부 fire-and-forget으로 두면 renderRows/
   * lastDemand 반영이 update()의 반환보다 늦게 끝나는 마이크로태스크 순서 문제가 있었음). */
  async function recompute() {
    if (!currentSectorIds) return; // 선택된 경로 없음 — clear()가 이미 패널을 숨김
    if (lastAircraft === undefined) return; // 아직 첫 ADS-B 스냅샷을 못 받음 — 다음 스냅샷 대기
    const sectors = await loadSectors();
    if (!currentSectorIds) return; // 대기 중 선택 해제됨
    const demand = lastAircraft === null ? [] : sectorDemand(lastAircraft, sectors, sectorsConfig);
    lastDemand = lastAircraft === null ? null : demand.filter((d) => currentSectorIds.includes(d.sectorId));
    renderRows(sectors, demand);
  }

  /** adsb.js의 onSnapshot 콜백 — 매 폴링 사이클(성공 시 배열, 실패 시 null)마다 호출.
   * recompute()의 프로미스를 그대로 반환한다(리뷰 지적, 2026-07-24) — main.js가 이 호출
   * 직후 동기적으로 bottlenecksPanel.refreshSectorSignal()을 불러 getDemand()를 읽는데,
   * 예전엔 여기서 fire-and-forget으로 두어(await 없이 recompute() 호출) refreshSectorSignal이
   * recompute()가 lastDemand를 갱신하기 *전* 값을 읽어 병목 패널의 섹터 신호가 매번 한
   * 폴링 주기만큼 뒤처졌다. */
  function onAircraftUpdate(aircraft) {
    lastAircraft = aircraft;
    return recompute();
  }

  /** 세그먼트 병목 종합(A5)이 읽는 요약 — 현재 선택된 경로가 지나는 섹터로만 필터링된
   * sectorDemand 결과. 아직 계산 전/ADS-B 미가용/선택된 경로 없음이면 null. */
  function getDemand() {
    return lastDemand;
  }

  /** 선택된 경로 옵션이 바뀔 때 호출(main.js, windLayer.update()와 동일 지점). */
  async function update(coords) {
    const mySeq = ++seq;
    // 이전 경로의 섹터 목록을 즉시 무효화한다 — 안 그러면 loadSectors() await 도중 도착하는
    // ADS-B 스냅샷(onAircraftUpdate→recompute)이 아직 이전 경로의 currentSectorIds로 렌더해
    // 잠깐(새 경로 데이터로 덮어써지기 전까지) 엉뚱한 경로의 교통량을 보여줄 수 있었다
    // (리뷰 지적, 2026-07-24).
    currentSectorIds = null;
    if (panelEl) {
      panelEl.hidden = false;
      panelEl.innerHTML = "";
      panelEl.append(line("경로 통과 섹터 계산 중…"));
    }
    let sectors;
    try {
      sectors = await loadSectors();
    } catch (err) {
      if (mySeq !== seq) return;
      clearPanel();
      if (panelEl) {
        panelEl.hidden = false;
        panelEl.append(line(`섹터 참조 데이터 조회 실패 — ${String(err?.message ?? err)}`));
      }
      return;
    }
    if (mySeq !== seq) return; // 더 최신 선택이 진행 중 — 이 응답은 폐기
    currentSectorIds = routeSectorIds(coords, sectors);
    await recompute();
  }

  function clear() {
    seq += 1;
    currentSectorIds = null;
    lastDemand = null;
    clearPanel();
  }

  return { update, clear, onAircraftUpdate, getDemand };
}
