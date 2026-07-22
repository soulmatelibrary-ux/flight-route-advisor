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
  };
}

/**
 * 원본 `08_임베드데이터_스키마.md` ODR2 옵션 배열 규약으로 되돌린다(docs/04 §4.4 예시).
 * [0:n,1:avgMin,2:delayCnt,3:heavyCnt,4:firs,5:fixes,6:track flat,7:frc flat,8:parity]
 * 현재 렌더 코드는 toRouteOption()의 키 기반 객체를 쓰므로 이 함수는 스토어 소비용이
 * 아니라 규약 문서화·향후 원본 로직 이식 시 호환을 위한 것이다.
 */
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
