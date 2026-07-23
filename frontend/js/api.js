/**
 * fetch 래퍼 (docs/04-frontend-migration.md §2 api.js, docs/05-mvp-scope.md F2).
 * baseURL은 config.js에서만, 캐시(참조 레이어 벌크 fetch는 store 캐시에 맡기고 여기선
 * in-flight 중복요청만 합침), 오류는 ApiError로 통일해 호출부가 오프라인/4xx/5xx를
 * 구분해 폴백 UI를 그릴 수 있게 한다(F2 "오프라인 폴백 처리").
 */
import { getConfig } from "./config.js";

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.name = "ApiError";
    this.status = status; // 0 = 네트워크 자체 실패(오프라인 등)
  }
}

const _inflight = new Map();

function buildQuery(params) {
  const entries = Object.entries(params ?? {}).filter(([, v]) => v !== undefined && v !== null && v !== "");
  if (entries.length === 0) return "";
  const usp = new URLSearchParams();
  for (const [k, v] of entries) usp.set(k, String(v));
  return `?${usp.toString()}`;
}

async function getJson(path, params) {
  const url = `${getConfig().apiBaseUrl}${path}${buildQuery(params)}`;
  if (_inflight.has(url)) return _inflight.get(url);

  const promise = (async () => {
    let res;
    try {
      res = await fetch(url, { method: "GET" });
    } catch (err) {
      throw new ApiError(0, "네트워크 오류 — 서버에 연결할 수 없음");
    }
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const body = await res.json();
        // 백엔드 표준 에러 봉투는 {error:{code,message}}다(docs/03 §2, app/envelope.py
        // error_envelope) — body.error는 문자열이 아니라 객체라 리뷰 전에는 여기서
        // "[object Object]"로 새던 버그가 있었다(2026-07-22 수정).
        detail = body.error?.message ?? body.detail ?? detail;
      } catch {
        /* 본문이 JSON이 아님 — 상태코드만 사용 */
      }
      throw new ApiError(res.status, detail);
    }
    return res.json();
  })();

  _inflight.set(url, promise);
  try {
    return await promise;
  } finally {
    // 성공·실패 모두 제거한다 — 여기 목적은 "동시에 겹치는 요청"만 하나로 합치는 것이지
    // 결과를 영구 캐시하는 게 아니다(그건 store.js가 별도로 담당). 성공 시에도 계속
    // 남겨두면 이후 같은 URL 재요청이 최초 응답에 영구히 고정돼 갱신되지 않는다
    // (2026-07-22 완료검증 §E에서 "성공 캐싱 유지"안을 명시적으로 기각했는데 코드에는
    // 잘못 반영돼 있던 것을 바로잡음).
    _inflight.delete(url);
  }
}

export const api = {
  odPairs: () => getJson("/routes/od-pairs"),
  routes: (dep, arr) => getJson("/routes", { dep, arr }),
  firs: ({ bbox, icao } = {}) => getJson("/reference/firs", { bbox, icao }),
  tca: ({ bbox } = {}) => getJson("/reference/tca", { bbox }),
  airways: ({ bbox } = {}) => getJson("/reference/airways", { bbox }),
  airports: ({ bbox, type } = {}) => getJson("/reference/airports", { bbox, type }),
  navaids: ({ bbox } = {}) => getJson("/reference/navaids", { bbox }),
  waypoints: ({ bbox, limit } = {}) => getJson("/reference/waypoints", { bbox, limit }),
  foisDelays: ({ direction, airport, dateFrom, dateTo } = {}) =>
    getJson("/fois/delays", { direction, airport, date_from: dateFrom, date_to: dateTo }),
  flowManagement: ({ dateFrom, dateTo, fir, airway, limit, offset } = {}) =>
    getJson("/flow-management", { date_from: dateFrom, date_to: dateTo, fir, airway, limit, offset }),
};
