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
        detail = body.detail ?? body.error ?? detail;
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
};
