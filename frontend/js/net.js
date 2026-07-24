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
        if (!res.ok) {
          const err = new Error(`HTTP ${res.status}`);
          err.isHttpStatusError = true;
          throw err;
        }
        const data = await res.json();
        successPath = name;
        return data;
      } catch (err) {
        lastErr = err;
        // "direct" 시도가 실제 HTTP 에러 상태로 응답했다면(=브라우저 CORS 차단이 아니라
        // 원본 서비스 자체 장애/오류, fetch가 throw하지 않고 res까지 도달했다는 뜻) 같은
        // directUrl을 targeting하는 local/public 프록시로 재시도해도 같은 에러가 반복될
        // 뿐이므로 즉시 중단한다(의미없는 재시도로 경로마다 최대 netTimeoutMs 낭비 방지,
        // 2026-07-24 — adsb.lol 노선조회 서브경로 503 장애 때 편명당 최대 3개 프록시 ×
        // netTimeoutMs가 낭비돼 ADS-B 색상 분류가 몇 분씩 정체됐음).
        //
        // local/public 프록시 자체의 HTTP 에러 상태는 여기서 중단하지 않는다(리뷰 지적,
        // 2026-07-24) — weather.js의 AWC 호출은 direct가 CORS로 항상 실패해(config.js
        // 실측 기록) local/public 체인이 사실상 유일한 성공 경로인데, 프록시가 자기
        // 업스트림 연결 실패를 502/503으로 반환하는 경우와 원본의 실제 장애를 구분할 방법이
        // 없어 여기서 조기 중단하면 원래 성공했을 다음 프록시 시도까지 막아버리는 회귀가
        // 생긴다. fetch 자체가 throw하는 CORS/네트워크 실패, 그리고 direct 외 경로의 HTTP
        // 에러는 기존처럼 다음 경로로 계속 시도한다.
        if (err.isHttpStatusError && name === "direct") break;
      }
    }
    throw lastErr ?? new Error("요청 실패 — 모든 경로 실패");
  };
}
