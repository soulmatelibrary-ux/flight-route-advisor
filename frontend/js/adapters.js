/**
 * API(키 기반 JSON) → 앱 내부 구조 어댑터 (docs/04-frontend-migration.md §4, F3).
 *
 * 결정 근거(docs/04 §4.1 동기화, 2026-07-22): 원본 완성본 HTML의 렌더 로직 소스 자체가
 * 이 저장소에 없다(15MB, 열람 금지 대상이자 정답지 전용). 즉 "기존 렌더 로직을 최소
 * 수정"할 대상 코드가 없으므로, §4.1이 제시한 두 대안 중 "배열 복원(기존 코드 재사용
 * 전제)"이 아니라 "키 접근으로 새로 작성"(§4.1 두 번째 대안, docs/06 §4.1과도 합치:
 * "API 경계에서는 키 기반")을 택했다. 다만 ODR2 경로옵션은 원본 `08` 인덱스 의미가
 * 알고리즘(집계 배치·2단계 확장)과 직접 연결되므로 toOptArray()로 08 배열 형태도
 * 함께 제공해 규약을 문서화·보존한다.
 */

/** FIR(firs.json) 응답 1건 → 렌더용 정규화 객체. polygons는 이미 [[ [lat,lon],...], ...] 쌍 형태. */
export function toFir(r) {
  return { icao: r.icao, nameEn: r.name_en, polygons: r.polygons, label: r.label };
}

export function toTca(r) {
  return { name: r.name, nameKo: r.name_ko, polygon: r.polygon };
}

/** SUAS/MOA 특수공역 1건(2026-07-24 신규). EFF_TIMES(발효시간)는 응답에 없음(docs/13 STEP A7 소관). */
export function toSuas(r) {
  return {
    ident: r.ident, name: r.name, type: r.type,
    upper: r.upper, lower: r.lower, polygon: r.polygon, region: r.region,
    // 발효시간(A7, docs/13 STEP A7) — effTimesRaw는 원문 참고용, scheduleStatus는
    // "structured"|"confirm_required"|null(배치 미실행), scheduleSegments는 structured일
    // 때만 [{days,utcStart,utcEnd}, ...](세그먼트 내부 키도 camelCase로 변환).
    effTimesRaw: r.eff_times_raw,
    scheduleStatus: r.schedule_status,
    scheduleSegments: r.schedule_segments?.map((s) => ({
      days: s.days, utcStart: s.utc_start, utcEnd: s.utc_end,
    })) ?? null,
  };
}

/** 항공로 구간 1건. a/b는 이미 [lat,lon] — coords로 묶어 Leaflet 폴리라인에 바로 사용. */
export function toAirway(r) {
  return { ident: r.ident, seq: r.seq, coords: [r.a, r.b], upper: r.upper, lower: r.lower };
}

export function toAirport(r) {
  return {
    icao: r.icao,
    name: r.name,
    lat: r.lat,
    lon: r.lon,
    elevFt: r.elev_ft,
    type: r.type,
    latlng: [r.lat, r.lon],
  };
}

export function toNavaid(r) {
  return { ident: r.ident, name: r.name, type: r.type, lat: r.lat, lon: r.lon, freq: r.freq, latlng: [r.lat, r.lon] };
}

export function toWaypoint(r) {
  return { ident: r.ident, lat: r.lat, lon: r.lon, country: r.country, latlng: [r.lat, r.lon] };
}

/** SID/STAR 절차 1건(원본 문서/08 §SS: proc 1=SID, 2=STAR). coords는 이미 [[lat,lon],...]. */
export function toSidStar(r) {
  return { proc: r.proc, name: r.name, airport: r.airport, coords: r.coords };
}

export function toOdPair(r) {
  return { dep: r.dep, arr: r.arr, totalFlights: r.total_flights };
}

/** /api/routes 응답의 옵션 1건 → 내부에서 쓰는 키 기반 형태(이미 이 shape로 옴, 통과용). */
export function toRouteOption(o) {
  return {
    flights: o.flights,
    avgMin: o.avg_min,
    delayCount: o.delay_count,
    heavyCount: o.heavy_count,
    enrouteFirs: o.enroute_firs,
    incheonTrackFixes: o.incheon_track_fixes,
    trackCoords: o.track_coords,
    fullRouteCoords: o.full_route_coords,
    cruiseParity: o.cruise_parity,
    // 터미널 신호(A6, docs/13 STEP A6) — 진출입 게이트·출발 활주로 분포.
    gateIn: o.gate_in,
    gateOut: o.gate_out,
    runwayDist: o.runway_dist,
  };
}

/**
 * 원본 `08_임베드데이터_스키마.md` ODR2 옵션 배열 규약으로 되돌린다(docs/04 §4.4 예시).
 * [0:n,1:avgMin,2:delayCnt,3:heavyCnt,4:firs,5:fixes,6:track flat,7:frc flat,8:parity]
 * 현재 렌더 코드는 toRouteOption()의 키 기반 객체를 쓰므로 이 함수는 스토어 소비용이
 * 아니라 규약 문서화·향후 원본 로직 이식 시 호환을 위한 것이다.
 */
/** /api/fois/delays 응답의 원인 집계 1건 → 내부에서 쓰는 camelCase 형태(F3 어댑터 규약). */
export function toFoisCause(c) {
  return {
    causeMajor: c.cause_major,
    causeMinor: c.cause_minor,
    causeProcess: c.cause_process,
    involvedParty: c.involved_party,
    reason: c.reason,
    count: c.count,
  };
}

/** /api/flow-management 응답의 조치 1건 → 내부에서 쓰는 camelCase 형태(F3 어댑터 규약). */
export function toFlowManagementItem(r) {
  return {
    flowId: r.flow_id,
    applyStartDt: r.apply_start_dt,
    applyEndDt: r.apply_end_dt,
    applyMinutes: r.apply_minutes,
    minit: r.minit,
    mit: r.mit,
    altSpeedLimit: r.alt_speed_limit,
    targetAirport: r.target_airport,
    targetFir: r.target_fir,
    targetRoute: r.target_route,
    targetFix: r.target_fix,
    restrictionSummary: r.restriction_summary,
    qualityStatus: r.quality_status,
  };
}

/** /api/airports/{icao}/ops 응답의 출발/도착 KPI 요약 1건(F3 어댑터 규약). */
export function toAirportOpsSummary(s) {
  return {
    flights: s.flights,
    onTimeRate: s.on_time_rate,
    avgTaxiOutMin: s.avg_taxi_out_min,
    ctotAdherence: s.ctot_adherence,
    avgTaxiInMin: s.avg_taxi_in_min,
    avgFirToAppMin: s.avg_fir_to_app_min,
  };
}

/** /api/reference/acc-sectors 응답의 섹터 1건 → camelCase(F3 어댑터 규약, docs/13 STEP A4). */
export function toAccSector(r) {
  return { sectorId: r.sector_id, nameEn: r.name_en, acc: r.acc, polygon: r.polygon };
}

export function toOptArray(o) {
  const flatten = (pairs) => pairs.flat();
  return [
    o.flights,
    o.avg_min,
    o.delay_count,
    o.heavy_count,
    o.enroute_firs,
    o.incheon_track_fixes,
    flatten(o.track_coords),
    flatten(o.full_route_coords),
    o.cruise_parity,
  ];
}
