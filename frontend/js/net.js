/**
 * 외부 API 호출 폴백 체인(직접→localhost:3000/proxy→공개 프록시), 성공 경로 기억
 * (docs/03/05/07 공통 규약). weather.js·layers/adsb.js가 각자 독립된 fetcher를 만들어
 * 쓴다(호스트마다 CORS 사정이 달라 성공 경로를 따로 기억해야 함).
 */
import { getConfig } from "./config.js";

export function createFallbackFetcher() {
  let successPath = null;

  function buildAttempts(directUrl) {
    const CONFIG = getConfig();
    const list = [
      ["direct", directUrl],
      ["local", `${CONFIG.weatherProxyUrl}?url=${encodeURIComponent(directUrl)}`],
      ...CONFIG.weather.publicProxies.map((proxy, i) => [`public:${i}`, `${proxy}${encodeURIComponent(directUrl)}`]),
    ];
    if (successPath) {
      const idx = list.findIndex(([name]) => name === successPath);
      if (idx > 0) list.unshift(list.splice(idx, 1)[0]);
    }
    return list;
  }

  return async function fetchJsonWithFallback(directUrl) {
    let lastErr;
    for (const [name, url] of buildAttempts(directUrl)) {
      try {
        const res = await fetch(url, { signal: AbortSignal.timeout(getConfig().netTimeoutMs) });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        successPath = name;
        return data;
      } catch (err) {
        lastErr = err;
      }
    }
    throw lastErr ?? new Error("요청 실패 — 모든 경로 실패");
  };
}
