/**
 * ROUTE 패널 DOM 로직 (docs/03 §ROUTE 패널, F6). 출발→도착 select, 운항 브리핑,
 * 옵션 목록(편수/평균소요/지연/HEAVY/경유FIR/인천FIR픽스체인), 클릭 강조.
 */
import { getState, subscribe, selectOd, selectOption } from "./store.js";
import { escapeHtml } from "./html.js";
import { getConfig } from "./config.js";

function groupByDep(odPairs) {
  const byDep = new Map();
  for (const { dep, arr, totalFlights } of odPairs) {
    if (!byDep.has(dep)) byDep.set(dep, []);
    byDep.get(dep).push({ arr, totalFlights });
  }
  const depTotals = new Map();
  for (const [dep, arrs] of byDep) {
    depTotals.set(
      dep,
      arrs.reduce((sum, a) => sum + a.totalFlights, 0),
    );
    arrs.sort((a, b) => b.totalFlights - a.totalFlights);
  }
  return { byDep, depOrder: [...depTotals.entries()].sort((a, b) => b[1] - a[1]).map(([dep]) => dep) };
}

function fmtMin(min) {
  return `${Math.round(min)}분`;
}

// 혼잡/지연 위험 — 과거 통계(ODR2 delay_count/heavy_count/flights)만으로 판단(사용자 요청,
// 2026-07-23). "50% 이상이면 위험" 같은 절대 임계값은 근거가 없어 정하지 않고(허위 판정
// 기준 생성 금지), 같은 OD의 후보 경로들 사이 **상대 비교**로만 "왜 이 경로를 권장하는지 /
// 어디가 상대적으로 막히는지"를 서술한다.
function delayRate(opt) {
  return opt.flights > 0 ? opt.delayCount / opt.flights : 0;
}

function heavyRate(opt) {
  return opt.flights > 0 ? opt.heavyCount / opt.flights : 0;
}

export function initRoutePanel() {
  const depSelect = document.getElementById("dep-select");
  const arrSelect = document.getElementById("arr-select");
  const briefingEl = document.getElementById("route-briefing");
  const listEl = document.getElementById("route-options");
  const errorEl = document.getElementById("route-error");

  let grouping = { byDep: new Map(), depOrder: [] };

  function showError(message) {
    errorEl.textContent = message;
    errorEl.hidden = !message;
  }

  function populateDepSelect(odPairs) {
    grouping = groupByDep(odPairs);
    depSelect.innerHTML = '<option value="">선택…</option>';
    for (const dep of grouping.depOrder) {
      const opt = document.createElement("option");
      opt.value = dep;
      opt.textContent = dep;
      depSelect.appendChild(opt);
    }
  }

  function populateArrSelect(dep) {
    const arrs = grouping.byDep.get(dep) ?? [];
    arrSelect.innerHTML = '<option value="">선택…</option>';
    for (const { arr, totalFlights } of arrs) {
      const opt = document.createElement("option");
      opt.value = arr;
      opt.textContent = `${arr} (${totalFlights}편)`;
      arrSelect.appendChild(opt);
    }
    arrSelect.disabled = arrs.length === 0;
  }

  function renderBriefing(routeResult) {
    if (!routeResult) {
      briefingEl.textContent = "";
      return;
    }
    const { totalFlights, options } = routeResult;
    const heavyTotal = options.reduce((s, o) => s + o.heavyCount, 0);
    const best = options.reduce((a, b) => (b.flights > a.flights ? b : a), options[0]);
    const bestIdx = options.indexOf(best);
    const bestShare = totalFlights > 0 ? Math.round((best.flights / totalFlights) * 100) : 0;

    // "왜 이 경로를 권장하는지" 근거를 후보 간 상대 비교로 명시(사용자 요청, 2026-07-23).
    // 편수가 극히 적은 옵션(예: 1편)은 지연 1건만으로 지연율이 0%/100%로 튀어 비교 기준을
    // 왜곡하므로 minSampleForCongestionTag 미만은 비교 대상에서 제외(사용자 확정, 2026-07-23).
    const MIN_SAMPLE = getConfig().display.minSampleForCongestionTag;
    const reliableRates = options.filter((o) => o.flights >= MIN_SAMPLE).map(delayRate);
    const bestRatePct = Math.round(delayRate(best) * 100);
    const reasons = [`실제 운항의 ${bestShare}%가 이 경로를 이용(가장 많이 쓰인 경로)`];
    if (reliableRates.length > 1 && best.flights >= MIN_SAMPLE) {
      const minRate = Math.min(...reliableRates);
      reasons.push(
        delayRate(best) === minRate
          ? `지연율도 후보 중 가장 낮음(${bestRatePct}%)`
          : `지연율 ${bestRatePct}%(후보 중 최저는 ${Math.round(minRate * 100)}%)`,
      );
    }

    briefingEl.textContent =
      `총 ${totalFlights}편 · HEAVY ${heavyTotal}대 · 후보 ${options.length}개\n` +
      `경로 ${bestIdx + 1} 권장 — ${reasons.join(" · ")}`;
  }

  function renderOptions(routeResult, selectedIndex) {
    listEl.innerHTML = "";
    if (!routeResult) return;
    const { options, totalFlights } = routeResult;
    const shortest = options.reduce((a, b) => (b.avgMin < a.avgMin ? b : a), options[0]);
    // 후보 간 지연율 상대 비교로 "어디가 상대적으로 막히는지" 배지 표시(사용자 요청,
    // 2026-07-23) — 절대 임계값 없이, 이 OD의 후보들 안에서 최저/최고만 표시. 편수가
    // minSampleForCongestionTag 미만인 옵션은 비교 대상·배지 부착 모두에서 제외한다
    // (1편 지연 1건 = "100%·상대적 혼잡"으로 과장돼 보이던 문제, 사용자 확정 2026-07-23).
    const MIN_SAMPLE = getConfig().display.minSampleForCongestionTag;
    const reliableRates = options.filter((o) => o.flights >= MIN_SAMPLE).map(delayRate);
    const minRate = reliableRates.length > 0 ? Math.min(...reliableRates) : null;
    const maxRate = reliableRates.length > 0 ? Math.max(...reliableRates) : null;

    const allLi = document.createElement("li");
    allLi.textContent = "전체 겹쳐보기";
    allLi.className = selectedIndex === null ? "selected" : "";
    allLi.addEventListener("click", () => selectOption(null));
    listEl.appendChild(allLi);

    options.forEach((opt, idx) => {
      const li = document.createElement("li");
      li.className = idx === selectedIndex ? "selected" : "";
      const share = totalFlights > 0 ? Math.round((opt.flights / totalFlights) * 100) : 0;
      const delta = opt.avgMin - shortest.avgMin;
      const row1 = document.createElement("div");
      row1.className = "row1";
      row1.innerHTML = `<span>경로 ${idx + 1}${opt === shortest ? " [최단]" : ""}</span><span>${fmtMin(opt.avgMin)}${
        delta > 0 ? ` <span class="delta-red">(+${Math.round(delta)}분)</span>` : ""
      }</span>`;
      const rate = delayRate(opt);
      const ratePct = Math.round(rate * 100);
      let congestionTag = "";
      if (opt.flights >= MIN_SAMPLE && minRate !== null && maxRate > minRate) {
        if (rate === minRate) congestionTag = ` <span class="tag-good">지연 최저</span>`;
        else if (rate === maxRate) congestionTag = ` <span class="tag-warn">상대적 혼잡</span>`;
      }
      const row2 = document.createElement("div");
      row2.className = "row2";
      row2.innerHTML =
        `운항 ${share}% · 지연율 ${ratePct}%(${opt.delayCount}건) · HEAVY ${opt.heavyCount}(${Math.round(heavyRate(opt) * 100)}%) · ` +
        `${escapeHtml(opt.enrouteFirs.join(" → "))}${congestionTag}`;
      li.append(row1, row2);
      // 터미널 신호(A6, docs/13 STEP A6 — 완성본 odInfo/ext 이식): 진출입 게이트·출발
      // 활주로 분포. 둘 다 결측(entry_fir/exit_fir 값이 없거나 ACDM 매칭이 안 된
      // 소수 OD)이면 조용히 생략 — 없는 값을 지어내지 않는다.
      if (opt.gateIn || opt.gateOut || opt.runwayDist?.length) {
        const row3 = document.createElement("div");
        row3.className = "row2";
        // row3는 textContent만 쓰므로(아래) escapeHtml 불필요(innerHTML이 아님 — wind.js
        // 리뷰에서 이미 지적된 것과 동일한 이유로 여기선 처음부터 안 넣음).
        const parts = [];
        if (opt.gateIn || opt.gateOut) {
          parts.push(`인천 진출입 : 진입 ${opt.gateIn || "—"} → 진출 ${opt.gateOut || "—"}`);
        }
        if (opt.runwayDist?.length) {
          parts.push(`출발 활주로 ${opt.runwayDist.map(([rw, pct]) => `${rw} ${pct}%`).join(" · ")}`);
        }
        row3.textContent = parts.join(" · ");
        li.append(row3);
      }
      li.addEventListener("click", () => selectOption(idx));
      listEl.appendChild(li);
    });
  }

  depSelect.addEventListener("change", () => {
    const dep = depSelect.value;
    populateArrSelect(dep);
    listEl.innerHTML = "";
    briefingEl.textContent = "";
    showError("");
  });

  arrSelect.addEventListener("change", async () => {
    const dep = depSelect.value;
    const arr = arrSelect.value;
    if (!dep || !arr) return;
    showError("");
    try {
      await selectOd(dep, arr);
    } catch {
      // store가 od:error를 notify — 아래 subscribe에서 표시
    }
  });

  subscribe((state, event) => {
    if (event.type === "boot:ok") populateDepSelect(state.odPairs);
    if (event.type === "od:error" || event.type === "viewmode:error") showError(event.message);
    if (event.type === "od:selected") {
      showError("");
      renderBriefing(state.routeResult);
      renderOptions(state.routeResult, state.selectedOptionIndex);
    }
    if (event.type === "option:selected") {
      renderOptions(state.routeResult, state.selectedOptionIndex);
    }
  });

  const initial = getState();
  if (initial.odPairs.length > 0) populateDepSelect(initial.odPairs);
}
