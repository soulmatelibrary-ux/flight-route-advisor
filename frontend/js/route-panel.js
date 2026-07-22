/**
 * ROUTE 패널 DOM 로직 (docs/03 §ROUTE 패널, F6). 출발→도착 select, 운항 브리핑,
 * 옵션 목록(편수/평균소요/지연/HEAVY/경유FIR/인천FIR픽스체인), 클릭 강조.
 */
import { getState, subscribe, selectOd, selectOption } from "./store.js";

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
    briefingEl.textContent =
      `총 ${totalFlights}편 · HEAVY ${heavyTotal}대 · 후보 ${options.length}개\n` +
      `경로 ${bestIdx + 1} 권장 — 운항 ${bestShare}%`;
  }

  function renderOptions(routeResult, selectedIndex) {
    listEl.innerHTML = "";
    if (!routeResult) return;
    const { options, totalFlights } = routeResult;
    const shortest = options.reduce((a, b) => (b.avgMin < a.avgMin ? b : a), options[0]);

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
      const row2 = document.createElement("div");
      row2.className = "row2";
      row2.textContent = `운항 ${share}% · 지연 ${opt.delayCount} · HEAVY ${opt.heavyCount} · ${opt.enrouteFirs.join(" → ")}`;
      li.append(row1, row2);
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
