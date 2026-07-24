/**
 * AI 응답(D6 JSON) 검증 — 신뢰 못 할 입력 (C3, docs/13-ai-reasoning-dev-plan.md STEP C3
 * "보안 핵심"). 순수 함수 — DOM·fetch 없음, `reasoning-panel.js`(C2)가 파싱 직후 호출한다.
 *
 * 근본적으로 잘못된 타입(문자열이 아닌 why, 배열이 아닌 bottlenecks/caveats)은 전체를
 * 거부한다(C2가 원래 하던 `isValidResponseShape`을 이 함수가 대체). 그 안의 개별 항목이
 * 형태가 안 맞으면(seg/reason 누락·타입 오류·severity가 화이트리스트 밖) 그 항목만 배열에서
 * 드롭한다 — `reasoning-context.js`의 `sanitizeCausePct`/`sanitizeCauseLabels`와 동일한 관례
 * (부분 수용이 이 저장소 전반의 방식이지, 사소한 항목 하나 때문에 전체 응답을 폐기하지 않음).
 * 길이 상한(config.js `CONFIG.reasoning`)을 넘는 문자열은 개별 항목 드롭이 아니라 잘라낸다
 * (why/caveats/seg/reason 전부 "존재는 하되 과도하게 길다"는 문제라 드롭보다 절단이 사용자에게
 * 더 유용 — 반면 severity처럼 값 자체가 틀린 경우는 절단할 수 없어 드롭).
 *
 * 드롭·절단이 조용히 일어나면 사용자가 "AI가 짧게 답했다"와 "일부가 검증 실패로 잘렸다"를
 * 구분할 수 없다(리뷰 지적, 2026-07-24 — 이 기능 자체의 원칙 "불확실/일부인 것을 완전한 것처럼
 * 제시하지 않는다"와 어긋남) — `value`와 별도로 `meta`(droppedBottlenecks/droppedCaveats/truncated)를
 * 반환해 호출부(reasoning-panel.js)가 비침습적인 안내를 붙일 수 있게 한다.
 */

const ALLOWED_SEVERITY = new Set(["info", "warn"]);

// 필터 이전에 배열 길이 자체를 한 번 넉넉히 잘라 — 악의적으로 아주 큰 배열(수만 항목)을
// 넣어도 filter()가 전체를 훑는 비용이 폭발하지 않도록 한다(2차 방어, 1차는 아래
// isRawTooLong의 원문 길이 상한 — 문자 수 상한이 있으면 배열 길이도 실질적으로 제한되지만,
// 짧은 문자열을 무수히 반복하는 형태로 우회할 수 있어 배열 자체에도 상한을 둔다).
const PRE_FILTER_MULTIPLIER = 5;

/** JSON.parse 이전에 호출 — 원문이 과도하게 길면 파싱 자체를 시도하지 않는다. */
export function isRawTooLong(raw, limits) {
  return raw.length > limits.responseMaxRawLen;
}

function isPlainObject(value) {
  return value != null && typeof value === "object" && !Array.isArray(value);
}

function sanitizeBottleneck(item, limits) {
  if (!isPlainObject(item)) return null;
  if (typeof item.seg !== "string" || item.seg.trim().length === 0) return null;
  if (typeof item.reason !== "string") return null;
  if (!ALLOWED_SEVERITY.has(item.severity)) return null;
  return {
    seg: item.seg.slice(0, limits.segMaxLen),
    reason: item.reason.slice(0, limits.reasonMaxLen),
    severity: item.severity,
  };
}

/**
 * @param {unknown} parsed - `JSON.parse()` 결과(어떤 타입이든 올 수 있음 — 신뢰 못 할 입력)
 * @param {object} limits - `CONFIG.reasoning`(하드코딩 금지, 상한값은 전부 config 단일출처)
 * @returns {{ok: true, value: {why: string, bottlenecks: Array, caveats: string[]}, meta: {whyTruncated: boolean, droppedBottlenecks: number, droppedCaveats: number}} | {ok: false, error: string}}
 */
export function validateReasoningResponse(parsed, limits) {
  if (!isPlainObject(parsed)) {
    return { ok: false, error: "응답이 JSON 객체가 아닙니다." };
  }
  if (typeof parsed.why !== "string" || parsed.why.trim().length === 0) {
    return { ok: false, error: "응답 형식이 올바르지 않습니다(why 문자열이 필요합니다)." };
  }
  if (!Array.isArray(parsed.bottlenecks)) {
    return { ok: false, error: "응답 형식이 올바르지 않습니다(bottlenecks 배열이 필요합니다)." };
  }
  if (!Array.isArray(parsed.caveats)) {
    return { ok: false, error: "응답 형식이 올바르지 않습니다(caveats 배열이 필요합니다)." };
  }

  const whyTruncated = parsed.why.length > limits.whyMaxLen;
  const why = parsed.why.slice(0, limits.whyMaxLen);

  const bottlenecks = parsed.bottlenecks
    .slice(0, limits.maxBottlenecks * PRE_FILTER_MULTIPLIER)
    .map((item) => sanitizeBottleneck(item, limits))
    .filter(Boolean)
    .slice(0, limits.maxBottlenecks);
  // "드롭됨"의 정의: 원본 항목 수 대비 실제로 화면에 보여줄 항목 수의 차 — 개별 형태오류로
  // 드롭된 것과 개수상한 초과로 잘려나간 것을 굳이 구분하지 않는다(사용자 입장에선 둘 다
  // "AI가 준 것 중 일부만 표시됨"으로 동일하게 정직히 알리면 충분).
  const droppedBottlenecks = Math.max(0, parsed.bottlenecks.length - bottlenecks.length);

  const caveats = parsed.caveats
    .slice(0, limits.maxCaveats * PRE_FILTER_MULTIPLIER)
    .filter((c) => typeof c === "string" && c.trim().length > 0)
    .map((c) => c.slice(0, limits.caveatMaxLen))
    .slice(0, limits.maxCaveats);
  const droppedCaveats = Math.max(0, parsed.caveats.length - caveats.length);

  return {
    ok: true,
    value: { why, bottlenecks, caveats },
    meta: { whyTruncated, droppedBottlenecks, droppedCaveats },
  };
}
