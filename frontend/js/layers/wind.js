/**
 * 경로 상층풍·연직시어·추천고도 (docs/13-ai-reasoning-dev-plan.md STEP A3). 완성본
 * `routeWind`/`segWindAt`/`calcFL`/`routeParity`/`drawShear`/`renderWind`을 그대로
 * 포팅했다(Open-Meteo GFS 다중 기압면, client-side, 백엔드 불필요 — doc13 대상 그대로).
 *
 * A1/A2와 달리 이건 **실시간 외부 API**라 과거 golden JSON으로 결과값을 대조 검증할 수
 * 없다 — 대신 계산 로직(벡터 보간·배풍/측풍 분해·시어·추천 정렬)을 순수함수로 분리해
 * 합성 입력으로 원본과 동일 출력을 내는지 단위 검증했다(완성본 함수를 줄 단위로 옮긴 것 —
 * 로직 변경 없음).
 */
const L = window.L;

function normLon(lon) {
  return (((lon % 360) + 540) % 360) - 180;
}

// 완성본 ptDist — 실제 nm이 아니라 위경도 기반 근사(도 단위). *60 하면 nm 근사(원본과 동일 관례).
export function ptDist(a, b) {
  const dl = normLon(b.lon - a.lon);
  const dx = dl * Math.cos(((a.lat + b.lat) * Math.PI) / 360);
  return Math.hypot(dx, b.lat - a.lat);
}

export function bearingDeg(a, b) {
  const R = Math.PI / 180;
  const la1 = a.lat * R;
  const la2 = b.lat * R;
  const dl = (b.lon - a.lon) * R;
  return (
    Math.atan2(Math.sin(dl) * Math.cos(la2), Math.cos(la1) * Math.sin(la2) - Math.sin(la1) * Math.cos(la2) * Math.cos(dl)) /
    R
  );
}

/** coords([[lat,lon],...]) → 등간격 표본점 + 총거리(nm 근사). 표본 수는 windConfig로 제어. */
export function samplePoints(coords, windConfig) {
  const f = coords.map(([lat, lon]) => ({ lat, lon }));
  if (f.length < 2) return { pts: [], totalNm: 0 };
  const cum = [0];
  for (let i = 1; i < f.length; i++) cum.push(cum[i - 1] + ptDist(f[i - 1], f[i]));
  const total = cum[cum.length - 1] || 1;
  const n = Math.min(
    windConfig.sampleMaxPoints,
    Math.max(windConfig.sampleMinPoints, Math.round(total / windConfig.sampleDegreesPerPoint)),
  );
  const pts = [];
  for (let k = 0; k < n; k++) {
    const d = (total * k) / (n - 1);
    let i = 1;
    while (i < cum.length - 1 && cum[i] < d) i++;
    const t = (d - cum[i - 1]) / (cum[i] - cum[i - 1] || 1);
    pts.push({
      lat: f[i - 1].lat + (f[i].lat - f[i - 1].lat) * t,
      lon: normLon(f[i - 1].lon + (f[i].lon - f[i - 1].lon) * t),
    });
  }
  return { pts, totalNm: total * 60 };
}

/** 인접 두 기압면 앵커 사이 벡터 보간 + 그 구간 시어(kt/1000ft). */
export function segWindAt(g, fl, levels) {
  const anchors = levels.map((l) => l.fl);
  let i = 0;
  while (i < anchors.length - 2 && anchors[i + 1] < fl) i++;
  const a = g.winds[i];
  const b = g.winds[i + 1];
  if (!a || !b) return null;
  const f0 = anchors[i];
  const f1 = anchors[i + 1];
  const t = Math.min(1, Math.max(0, (fl - f0) / (f1 - f0)));
  const R = Math.PI / 180;
  // 풍향은 '불어오는' 방향이므로 벡터는 반대 방향
  const u = -((1 - t) * a.ws * Math.sin(a.wd * R) + t * b.ws * Math.sin(b.wd * R));
  const v = -((1 - t) * a.ws * Math.cos(a.wd * R) + t * b.ws * Math.cos(b.wd * R));
  const du = b.ws * Math.sin(b.wd * R) - a.ws * Math.sin(a.wd * R);
  const dv = b.ws * Math.cos(b.wd * R) - a.ws * Math.cos(a.wd * R);
  const shear = Math.hypot(du, dv) / Math.max(1, (f1 - f0) / 10);
  return { u, v, shear };
}

/** 특정 고도(fl)에서 경로 전체의 배풍/측풍/시어/소요시간 델타. */
export function calcFL(wx, fl, levels, tasKt) {
  const { segs, totalNm } = wx;
  let sT = 0;
  let sC = 0;
  let sL = 0;
  let maxCross = 0;
  let maxShear = 0;
  let maxK = -1;
  const R = Math.PI / 180;
  for (let k = 0; k < segs.length; k++) {
    const g = segs[k];
    const w = segWindAt(g, fl, levels);
    if (!w) continue;
    const bx = Math.sin(g.brg * R);
    const by = Math.cos(g.brg * R);
    const tail = w.u * bx + w.v * by;
    const cross = Math.abs(-w.u * by + w.v * bx);
    sT += tail * g.L;
    sC += cross * g.L;
    sL += g.L;
    if (cross > maxCross) maxCross = cross;
    if (w.shear > maxShear) {
      maxShear = w.shear;
      maxK = k;
    }
  }
  if (!sL) return null;
  const wc = sT / sL;
  const xc = sC / sL;
  const shearFrom = maxK >= 0 ? Math.round((100 * maxK) / segs.length) : 0;
  const shearTo = maxK >= 0 ? Math.round((100 * (maxK + 1)) / segs.length) : 0;
  const dtMin = (totalNm / tasKt - totalNm / Math.max(200, tasKt + wc)) * 60;
  return { fl, wc, xc, maxCross, maxShear, shearFrom, shearTo, dtMin };
}

/** 순항고도 배정(홀/짝) — ODR2 `cruiseParity`(항공사 RFL 다수결) 우선, 없으면 진로 기반 반원 규칙. */
export function routeParity(cruiseParity, coords) {
  if (cruiseParity === "O") return { p: "O", src: "항공사 RFL 기준" };
  if (cruiseParity === "E") return { p: "E", src: "항공사 RFL 기준" };
  const [aLat, aLon] = coords[0];
  const [bLat, bLon] = coords[coords.length - 1];
  const brg = ((bearingDeg({ lat: aLat, lon: aLon }, { lat: bLat, lon: bLon }) % 360) + 360) % 360;
  return { p: brg < 180 ? "O" : "E", src: `방향 규칙(진로 ${Math.round(brg)}°)` };
}

/** 연직시어 등급 — [label, CONFIG.tokens 키]. */
export function catGrade(shear, windConfig) {
  if (shear > windConfig.shearStrongKt1000ft) return ["강함 가능", "shearStrong"];
  if (shear > windConfig.shearModerateKt1000ft) return ["보통", "shearModerate"];
  return ["약함 이하", "shearWeak"];
}

/** 추천고도: 순항고도 후보 중 시어 안전(≤ shearStrongKt1000ft) 풀에서 소요단축 최대,
 * 동률 시 시어 낮은 쪽(doc13 STEP A3 수용기준) — 안전 후보가 없으면 순항 전체, 그마저
 * 없으면 전체(FL_LOW 포함) 중에서 고른다. */
export function recommendFL(all, cruiseFLs, windConfig) {
  const cr = all.filter((c) => cruiseFLs.includes(c.fl));
  const safe = cr.filter((c) => c.maxShear <= windConfig.shearStrongKt1000ft);
  const pool = safe.length ? safe : cr.length ? cr : all;
  return [...pool].sort((a, b) => b.dtMin - a.dtMin || a.maxShear - b.maxShear)[0];
}

async function fetchWindRaw(pts, windConfig, timeoutMs) {
  const vars = windConfig.levels.flatMap((l) => [`wind_speed_${l.pressure}`, `wind_direction_${l.pressure}`]).join(",");
  const las = pts.map((p) => p.lat.toFixed(2)).join(",");
  const los = pts.map((p) => p.lon.toFixed(2)).join(",");
  const url =
    `${windConfig.apiUrl}?latitude=${las}&longitude=${los}` +
    `&hourly=${vars}&forecast_days=1&wind_speed_unit=kn&timeformat=unixtime`;
  const res = await fetch(url, { signal: AbortSignal.timeout(timeoutMs) });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const json = await res.json();
  return Array.isArray(json) ? json : [json];
}

/** 경로 좌표 → 표본지점 조회 → 구간별(표본점 간) 방위·거리·기압면별 바람 원시자료. */
export async function buildRouteWind(coords, windConfig, timeoutMs) {
  const { pts, totalNm } = samplePoints(coords, windConfig);
  if (pts.length < 2) return null;
  const raw = await fetchWindRaw(pts, windConfig, timeoutMs);
  const nowS = Date.now() / 1000;
  const segs = [];
  for (let k = 0; k < pts.length - 1; k++) {
    const h = raw[k] && raw[k].hourly;
    if (!h || !h.time) continue;
    let idx = 0;
    for (let t = 0; t < h.time.length; t++) if (h.time[t] <= nowS) idx = t;
    const brg = bearingDeg(pts[k], pts[k + 1]);
    const winds = windConfig.levels.map((l) => {
      const ws = h[`wind_speed_${l.pressure}`];
      const wd = h[`wind_direction_${l.pressure}`];
      return ws && wd && ws[idx] != null && wd[idx] != null ? { ws: ws[idx], wd: wd[idx] } : null;
    });
    segs.push({ brg, L: ptDist(pts[k], pts[k + 1]), winds });
  }
  if (!segs.length) return null;
  return { segs, totalNm, pts };
}

function fmtDelta(dtMin) {
  if (dtMin >= 0.5) return { text: `▼ ${Math.round(Math.abs(dtMin))}분 단축`, cls: "wind-good" };
  if (dtMin <= -0.5) return { text: `▲ ${Math.round(Math.abs(dtMin))}분 증가`, cls: "wind-bad" };
  return { text: "변화 없음", cls: "" };
}

function line(text, cls) {
  const div = document.createElement("div");
  div.textContent = text;
  if (cls) div.className = cls;
  return div;
}

/** 지도 시어 오버레이(레이어그룹) + 정보 패널을 함께 관리한다(main.js가 store 이벤트로 호출). */
export function createWindLayer(map, CONFIG) {
  const shearLayer = L.layerGroup().addTo(map);
  const panelEl = document.getElementById("route-wind");
  const windConfig = CONFIG.wind;

  let seq = 0;
  let manualFL = null; // null=추천 자동 선택
  let cached = null; // { wx, all, rec, parity, cruiseFLs }

  function clearPanel() {
    if (panelEl) {
      panelEl.hidden = true;
      panelEl.innerHTML = "";
      panelEl.classList.remove("route-wind-warn");
    }
  }

  function clear() {
    seq += 1; // 진행 중이던 조회는 폐기 대상
    manualFL = null;
    cached = null;
    shearLayer.clearLayers();
    clearPanel();
  }

  function drawShear(wx, fl) {
    shearLayer.clearLayers();
    for (let k = 0; k < wx.segs.length && k + 1 < wx.pts.length; k++) {
      const w = segWindAt(wx.segs[k], fl, windConfig.levels);
      if (!w) continue;
      const [, tokenKey] = catGrade(w.shear, windConfig);
      L.polyline(
        [
          [wx.pts[k].lat, wx.pts[k].lon],
          [wx.pts[k + 1].lat, wx.pts[k + 1].lon],
        ],
        { color: CONFIG.tokens[tokenKey], weight: 9, opacity: 0.32, interactive: false },
      ).addTo(shearLayer);
    }
  }

  function renderPanel() {
    if (!panelEl || !cached) return;
    const { all, rec, parity } = cached;
    const curFL = manualFL != null && all.some((c) => c.fl === manualFL) ? manualFL : rec.fl;
    const c = all.find((x) => x.fl === curFL);
    const [gradeLabel, gradeKey] = catGrade(c.maxShear, windConfig);
    const [recLabel] = catGrade(rec.maxShear, windConfig);

    panelEl.hidden = false;
    panelEl.innerHTML = "";
    // 완성본 renderWind()의 #rp-wind.hw(정풍이거나 시어가 강함 임계 초과 시 경고 배경) 이식.
    panelEl.classList.toggle("route-wind-warn", c.wc < 0 || c.maxShear > windConfig.shearStrongKt1000ft);
    panelEl.append(line(`경로 상층풍·연직시어 (GFS) — 고도 배정: ${parity.p === "O" ? "홀수" : "짝수"}(${parity.src})`));

    const recWind = fmtDelta(rec.dtMin);
    panelEl.append(
      line(
        `★ 추천 순항고도 FL${rec.fl} — ${rec.wc >= 0 ? "배풍" : "정풍"} ${Math.abs(Math.round(rec.wc))}kt · ` +
          `${recWind.text} · 난류 ${recLabel}`,
        recWind.cls,
      ),
    );

    const btnRow = document.createElement("div");
    btnRow.className = "wind-fl-buttons";
    for (const x of all) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = `FL${x.fl}`;
      btn.title = `배풍 ${Math.round(x.wc)}kt · 시어 ${x.maxShear.toFixed(1)}kt/1000ft`;
      btn.className = "wlvl-btn" + (x.fl === curFL ? " on" : "") + (x.fl === rec.fl ? " rec" : "");
      btn.addEventListener("click", () => {
        manualFL = x.fl;
        renderPanel(); // drawShear()까지 다시 호출함(아래) — 여기서 중복 호출하지 않음
      });
      btnRow.append(btn);
    }
    panelEl.append(btnRow);

    const curWind = fmtDelta(c.dtMin);
    const detail = document.createElement("div");
    detail.append(
      document.createTextNode(
        `FL${c.fl}: ${c.wc >= 0 ? "배풍" : "정풍"} ${Math.abs(Math.round(c.wc))}kt · 측풍 평균 ${Math.round(c.xc)}kt ` +
          `(최대 ${Math.round(c.maxCross)}kt) · 오늘 상층풍 효과 `,
      ),
    );
    const deltaSpan = document.createElement("span");
    deltaSpan.textContent = curWind.text;
    if (curWind.cls) deltaSpan.className = curWind.cls;
    detail.append(deltaSpan);
    panelEl.append(detail);

    const gradeLine = document.createElement("div");
    gradeLine.append(document.createTextNode("CAT 추정(연직시어): "));
    const gradeBadge = document.createElement("span");
    gradeBadge.textContent = gradeLabel;
    gradeBadge.className = "wind-grade";
    gradeBadge.style.backgroundColor = CONFIG.tokens[gradeKey];
    gradeLine.append(gradeBadge);
    gradeLine.append(
      document.createTextNode(
        ` 최대 ${c.maxShear.toFixed(1)}kt/1000ft` +
          (c.maxShear > windConfig.shearModerateKt1000ft ? ` (경로 ${c.shearFrom}~${c.shearTo}% 구간)` : ""),
      ),
    );
    panelEl.append(gradeLine);

    function curFLFor() {
      return manualFL != null && all.some((cc) => cc.fl === manualFL) ? manualFL : rec.fl;
    }
    drawShear(cached.wx, curFLFor());
  }

  /** 선택된 경로 옵션이 바뀔 때 호출 — coords는 [[lat,lon],...], cruiseParity는 'O'/'E'/null. */
  async function update(coords, cruiseParity) {
    const mySeq = ++seq;
    manualFL = null;
    shearLayer.clearLayers();
    if (panelEl) {
      panelEl.hidden = false;
      panelEl.innerHTML = "";
      panelEl.append(line("경로 상층풍·연직시어 분석 중… (기압면 6종 일괄 조회)"));
    }
    let wx;
    try {
      wx = await buildRouteWind(coords, windConfig, CONFIG.netTimeoutMs);
    } catch (err) {
      if (mySeq !== seq) return;
      clearPanel();
      if (panelEl) {
        panelEl.hidden = false;
        panelEl.append(line(`경로 상층풍 데이터 조회 실패 — ${String(err?.message ?? err)}`));
      }
      return;
    }
    if (mySeq !== seq) return; // 더 최신 선택이 진행 중 — 이 응답은 폐기
    if (!wx) {
      clearPanel();
      if (panelEl) {
        panelEl.hidden = false;
        panelEl.append(line("경로 상층풍 데이터 없음"));
      }
      return;
    }
    const parity = routeParity(cruiseParity, coords);
    const cruiseFLs = parity.p === "O" ? windConfig.flOdd : windConfig.flEven;
    const flCandidates = [...windConfig.flLow, ...cruiseFLs];
    const all = flCandidates.map((fl) => calcFL(wx, fl, windConfig.levels, windConfig.tasKt)).filter(Boolean);
    if (!all.length) {
      clearPanel();
      if (panelEl) {
        panelEl.hidden = false;
        panelEl.append(line("경로 상층풍 데이터 없음"));
      }
      return;
    }
    const rec = recommendFL(all, cruiseFLs, windConfig);
    cached = { wx, all, rec, parity, cruiseFLs };
    renderPanel();
  }

  /** 세그먼트 병목 종합(A5, docs/13 STEP A5)이 읽는 최소 요약 — 추천 고도의 배풍/시어만
   * 노출한다(전체 `cached` 내부 구조는 이 위젯 소관이라 캡슐화 유지). 아직 조회 전/실패/
   * 데이터 없음이면 null — 호출부가 "신호 없음"으로 자연스럽게 취급. */
  function getRecommendation() {
    return cached ? cached.rec : null;
  }

  return { shearLayer, update, clear, getRecommendation };
}
