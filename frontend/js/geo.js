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
