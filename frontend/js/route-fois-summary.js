/**
 * 노선-FOIS 라이트 연동 (2단계 1단계, docs/07-checklist.md 참고). 노선(OD)을 선택하면
 * 그 출발/도착 공항의 FOIS 지연원인 상위 항목을 "의사결정 근거" 패널에 자동으로
 * 보여준다.
 *
 * FOIS 지연원인 패널(fois-panel.js)과는 별개의 독립 위젯이다 — 그 패널은 여전히
 * 사용자가 임의 공항·기간을 수동 조회하는 범용 도구로 그대로 두고, 이 위젯은
 * store.js의 노선 선택 상태(od:selected)만 구독해 참고 맥락을 자동으로 채운다.
 *
 * ⚠ 의도적 한계: FOIS는 "노선(출발-도착 쌍)" 단위가 아니라 "공항" 단위 집계다.
 * 따라서 이 위젯은 "이 공항은 최근 이런 사유로 지연됐다"는 참고 정보만 보여줄 뿐,
 * "그래서 이 경로를 추천한다"는 인과관계로 표현하지 않는다 — 원인공정을 FIR/항공로와
 * 매칭해 실제 추천 로직에 반영하는 것은 검토 단계이며 docs/07-checklist.md "향후
 * 확장 — 계획"에 설계만 남겨뒀다(사용자 확정, 2026-07-23: 우선 1단계로 활용 양상을
 * 지켜본 뒤 착수 여부 판단).
 */
import { getState, subscribe } from "./store.js";
import { api, ApiError } from "./api.js";
import { toFoisCause } from "./adapters.js";

const TOP_N = 3;

function describeError(err) {
  if (err instanceof ApiError) {
    return err.status === 0 ? "네트워크 연결 실패" : err.message;
  }
  return String(err?.message ?? err);
}

function summaryLine(label, result) {
  if (result === null) return `${label}: 조회 실패`;
  if (result.total === 0) return `${label}: 최근 지연원인 기록 없음`;
  const top = result.causes
    .slice(0, TOP_N)
    .map(toFoisCause)
    .map((c) => `${c.causeMajor ?? "-"}(${c.count})`)
    .join(", ");
  return `${label} 총 ${result.total}건 — ${top}`;
}

export function initRouteFoisSummary() {
  const el = document.getElementById("route-fois-summary");
  if (!el) return; // 마크업이 없는 페이지(스모크 하네스 등)에서는 조용히 건너뜀

  let seq = 0;

  async function update(dep, arr) {
    const mySeq = ++seq;
    el.textContent = "노선 지연원인 조회 중…";
    const [depOutcome, arrOutcome] = await Promise.allSettled([
      api.foisDelays({ direction: "dep", airport: dep }),
      api.foisDelays({ direction: "arr", airport: arr }),
    ]);
    if (mySeq !== seq) return; // 더 최신 노선 선택이 진행 중 — 이 응답은 폐기

    if (depOutcome.status === "rejected") {
      console.error("FOIS 출발 조회 실패:", describeError(depOutcome.reason));
    }
    if (arrOutcome.status === "rejected") {
      console.error("FOIS 도착 조회 실패:", describeError(arrOutcome.reason));
    }

    el.innerHTML = "";
    const depLine = document.createElement("div");
    depLine.textContent = summaryLine(
      `출발(${dep})`,
      depOutcome.status === "fulfilled" ? depOutcome.value.data : null,
    );
    const arrLine = document.createElement("div");
    arrLine.textContent = summaryLine(
      `도착(${arr})`,
      arrOutcome.status === "fulfilled" ? arrOutcome.value.data : null,
    );
    el.append(depLine, arrLine);
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
