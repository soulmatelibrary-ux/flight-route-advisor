/**
 * 노선-흐름관리 영향률 위젯 (docs/13-ai-reasoning-dev-plan.md STEP A1). route-fois-summary.js/
 * route-ops-summary.js와 동일한 패턴(store.js의 od:selected만 구독하는 독립 위젯, seq 토큰으로
 * 경쟁 조건 방지) — `GET /api/routes/flow`를 호출해 이 노선이 흐름관리에 얼마나 영향받는지
 * 요약해 보여준다.
 *
 * ⚠ 표시하는 수치의 성격을 정확히 구분한다(docs/13 STEP A1 배치 docstring 참고):
 * - 영향률(impact_pct)·주 사유·주요 제한·시간대별 영향률: `SOURCE_PROJECT_ROOT`의
 *   흐름관리 전처리 스킬(`integrate_flights()`) 판정 로직을 그대로 포팅해 계산한 값 —
 *   완성본 flow.json의 알려진 OD 3건과 실측 대조로 검증됨(정확히 일치).
 * - 정시율/지연 비교(on_time_affected 등): 아직 미구현(null) — 검증된 계산식을 확정하지
 *   못해 값을 내보내지 않는다. 화면에는 "준비 중"으로만 표시하고 숫자를 지어내지 않는다.
 */
import { getState, subscribe } from "./store.js";
import { api, ApiError } from "./api.js";

function describeError(err) {
  if (err instanceof ApiError) {
    return err.status === 0 ? "네트워크 연결 실패" : err.message;
  }
  return String(err?.message ?? err);
}

function line(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div;
}

function render(el, data) {
  el.innerHTML = "";
  if (!data.found) {
    el.append(line("이 노선은 이번 달 흐름관리 영향 기록이 충분치 않습니다."));
    return;
  }
  el.append(line(`흐름관리 영향률 ${data.impact_pct}% (총 ${data.total_flights}편 중 ${data.affected_flights}편, 추정치)`));
  if (data.main_causes?.length) {
    const text = data.main_causes.map(([code, pct]) => `${code} ${pct}%`).join(" · ");
    el.append(line(`주 사유코드: ${text}`));
  }
  if (data.main_limits?.length) {
    el.append(line(`주요 제한: ${data.main_limits.join(" / ")}`));
  }
  el.append(line("정시율·지연 비교: 검증된 계산식 미확정으로 준비 중"));
}

export function initRouteFlowSummary() {
  const el = document.getElementById("route-flow-summary");
  if (!el) return; // 마크업이 없는 페이지(스모크 하네스 등)에서는 조용히 건너뜀

  let seq = 0;

  async function update(dep, arr) {
    const mySeq = ++seq;
    el.textContent = "흐름관리 영향률 조회 중…";
    let outcome;
    try {
      const res = await api.routeFlow(dep, arr);
      outcome = { status: "fulfilled", value: res };
    } catch (err) {
      outcome = { status: "rejected", reason: err };
    }
    if (mySeq !== seq) return; // 더 최신 노선 선택이 진행 중 — 이 응답은 폐기

    if (outcome.status === "rejected") {
      el.textContent = `흐름관리 영향률 조회 실패 — ${describeError(outcome.reason)}`;
      return;
    }
    render(el, outcome.value.data);
  }

  function clear() {
    seq += 1; // 진행 중이던 조회는 이제 폐기 대상
    el.textContent = "";
  }

  subscribe((state, event) => {
    if (event.type === "od:selecting") clear();
    if (event.type === "od:selected" && state.dep && state.arr) {
      update(state.dep, state.arr);
    }
    if (event.type === "od:error") clear();
  });

  const initial = getState();
  if (initial.dep && initial.arr && initial.routeResult) {
    update(initial.dep, initial.arr);
  }
}
