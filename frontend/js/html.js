/**
 * HTML 이스케이프 (docs/06-conventions.md §8 입력 검증/XSS 방지).
 * 외부 API(METAR/TAF/ADS-B/adsbdb)와 참조 데이터의 문자열 필드를 innerHTML·divIcon
 * html·popup/tooltip 콘텐츠에 넣기 전 반드시 이 함수를 거친다 — 신뢰 여부와 무관하게
 * 전부 이스케이프한다(방어적 코딩, 리뷰 지적사항 반영 2026-07-22).
 */
const ESCAPE_MAP = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ESCAPE_MAP[ch]);
}
