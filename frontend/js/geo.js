/**
 * 지오메트리 공용 유틸 (docs/04-frontend-migration.md 04-F 겹침 폴리곤 수정, reference.js/route.js 공유).
 * shoelace 부호 면적으로 링 방향을 판정해 통일한다 — Leaflet Canvas 기본 fillRule('evenodd')가
 * 겹치는 멀티폴리곤을 상쇄하는 문제(04-F)를 fillRule:'nonzero'와 함께 해결하는 데 쓰인다.
 */

export function signedArea(ring) {
  let sum = 0;
  for (let i = 0; i < ring.length; i++) {
    const [lat1, lon1] = ring[i];
    const [lat2, lon2] = ring[(i + 1) % ring.length];
    sum += lon1 * lat2 - lon2 * lat1;
  }
  return sum;
}

export function normalizeWinding(ring) {
  return signedArea(ring) < 0 ? ring : [...ring].reverse();
}

/** 링의 모든 점 경도에 ±360 등을 더한다 — 월드 랩 복제(reference.js/route.js 공유). */
export function shiftRing(ring, deltaLon) {
  return ring.map(([lat, lon]) => [lat, lon + deltaLon]);
}

/**
 * FIR의 polygons(링 배열들) 전체를 감싸는 bbox([minLat,minLon,maxLat,maxLon]).
 * 전세계/지역 컨텍스트에서 항로·항행시설(country 태그가 없음)을 "관련 FIR 근처만" 으로
 * 줄일 때 씀(2026-07-23) — 정확한 점-폴리곤 판정 대신 bbox만 쓰는 이유: 항로 89,555개
 * 전부에 폴리곤 판정을 돌리면(레이캐스팅) 메인 스레드가 오래 막혀 "페이지 응답 없음"이
 * 재발할 수 있다(같은 원인으로 permanent 툴팁을 없앤 전례와 동일한 성능 제약).
 * bbox는 근사치라 FIR 모양이 아닌 사각형으로 잘리지만, 이 코드베이스가 이미 쓰는
 * 단순화 패턴(regionContextBounds 등)과 일관되고 계산 비용이 훨씬 싸다.
 */
export function boundsOfPolygons(polygons) {
  let minLat = Infinity;
  let minLon = Infinity;
  let maxLat = -Infinity;
  let maxLon = -Infinity;
  for (const ring of polygons) {
    for (const [lat, lon] of ring) {
      if (lat < minLat) minLat = lat;
      if (lat > maxLat) maxLat = lat;
      if (lon < minLon) minLon = lon;
      if (lon > maxLon) maxLon = lon;
    }
  }
  return [minLat, minLon, maxLat, maxLon];
}

export function pointInBounds(lat, lon, bounds) {
  const [minLat, minLon, maxLat, maxLon] = bounds;
  return lat >= minLat && lat <= maxLat && lon >= minLon && lon <= maxLon;
}

/**
 * 점-폴리곤 판정(레이캐스팅, 완성본 `pip(lat,lon,fl)` 이식 — docs/13 STEP A4). 원본은 폴리곤을
 * flat 배열([lat0,lon0,lat1,lon1,...])로 받지만 이 코드베이스는 폴리곤을 [[lat,lon],...] 쌍
 * 배열로 다루므로(reference.js/route.js와 동일 관례) 그 형태로 인덱싱만 바꿔 이식했다 —
 * 판정 로직(교차 계산) 자체는 원본과 동일.
 */
export function pointInPolygon(lat, lon, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [yi, xi] = ring[i];
    const [yj, xj] = ring[j];
    if (yi > lat !== yj > lat && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/** 여러 bbox를 하나로 감싸는 bbox(서버에 bbox 쿼리 하나로 보낼 때 씀). */
export function unionBounds(boundsList) {
  let minLat = Infinity;
  let minLon = Infinity;
  let maxLat = -Infinity;
  let maxLon = -Infinity;
  for (const [a, b, c, d] of boundsList) {
    if (a < minLat) minLat = a;
    if (b < minLon) minLon = b;
    if (c > maxLat) maxLat = c;
    if (d > maxLon) maxLon = d;
  }
  return [minLat, minLon, maxLat, maxLon];
}

/**
 * 경도 연속화(unwrap) — 미국↔한국처럼 날짜변경선을 넘는 노선의 원시 트랙 좌표는
 * 보정 없이 그대로 저장돼 있어(예: -152.34 → 171.975로 한 번에 점프, 실측 확인
 * 2026-07-23) Leaflet이 그 두 점을 최단(태평양)이 아니라 최장(유럽 경유) 방향
 * 직선으로 그린다 — 화면에 지도 폭 전체를 가로지르는 선이 생기는 원인. 연속된
 * 두 점의 경도차가 180°를 넘으면 그 뒤 모든 점에 ±360을 누적 보정해 이어 붙인다.
 */
export function unwrapLongitudes(coords) {
  const result = [];
  let offset = 0;
  let prevLon = null;
  for (const [lat, lon] of coords) {
    let adjusted = lon + offset;
    if (prevLon !== null) {
      if (adjusted - prevLon > 180) {
        offset -= 360;
        adjusted -= 360;
      } else if (prevLon - adjusted > 180) {
        offset += 360;
        adjusted += 360;
      }
    }
    result.push([lat, adjusted]);
    prevLon = adjusted;
  }
  return result;
}
