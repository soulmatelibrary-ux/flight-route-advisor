/**
 * 위험기상(SIGMET/PIREP) 토글 레이어 (docs/10-ui-and-realtime.md §2.5 레이어④, 2단계).
 * AWC 실제 응답 스키마는 WebFetch/curl로 직접 확인 후 구현(허위 필드 생성 금지 원칙):
 * SIGMET(`isigmet`) `coords`는 geom="AREA"면 `[{lat,lon},...]`, geom="AREAS"(복수)면
 * `[[{lat,lon},...], ...]` — 배열의 배열 여부가 다르다. PIREP은 `lat`/`lon` 단일 점 +
 * `tbInt1/tbType1`(난류)·`icgInt1/icgType1`(착빙)·`wxString`.
 *
 * 의도적 축소 범위(2026-07-23, docs/10 §2.5 ④ 원안 대비): "루트 교차 시 지도 경고
 * 마커 + 근거 패널 칩(TS·ICE·TURB)"의 교차 판정 로직(경로-폴리곤 intersection, 근접
 * 임계 등)은 이번 라운드에 포함하지 않음 — 원본 어디에도 그 판정 알고리즘이 없어
 * 발명하지 않고, 우선 지도에 SIGMET 폴리곤·PIREP 마커를 토글로 그려 존재 자체를
 * 확인할 수 있게 한다(사용자 확인 후 후속 작업 여부 결정, docs/07-checklist.md 참고).
 */
import { escapeHtml } from "../html.js";

const L = window.L;

function ringOf(coordsGroup) {
  // AREA: [{lat,lon}] / AREAS: [[{lat,lon}], ...] — 둘 다 "링의 배열"로 통일한다.
  const isMultiRing = Array.isArray(coordsGroup[0]);
  const rings = isMultiRing ? coordsGroup : [coordsGroup];
  return rings
    .map((ring) => ring.filter((p) => p && typeof p.lat === "number" && typeof p.lon === "number").map((p) => [p.lat, p.lon]))
    .filter((ring) => ring.length >= 3);
}

function sigmetPopupHtml(s) {
  const lines = [
    `<b>${escapeHtml(s.firId ?? "?")} ${escapeHtml(s.firName ?? "")}</b>`,
    `${escapeHtml(s.hazard ?? "")} ${escapeHtml(s.qualifier ?? "")}`.trim(),
    s.base != null || s.top != null ? `FL${escapeHtml(s.base ?? "SFC")}–FL${escapeHtml(s.top ?? "?")}` : "",
    `<div class="muted">${escapeHtml(s.rawSigmet ?? "")}</div>`,
  ].filter(Boolean);
  return lines.join("<br>");
}

function pirepPopupHtml(p) {
  const parts = [`${escapeHtml(p.acType ?? "?")} FL${escapeHtml(p.fltLvl ?? "?")}`];
  if (p.tbInt1) parts.push(`난류 ${escapeHtml(p.tbInt1)}${p.tbType1 ? " " + escapeHtml(p.tbType1) : ""}`);
  if (p.icgInt1) parts.push(`착빙 ${escapeHtml(p.icgInt1)}${p.icgType1 ? " " + escapeHtml(p.icgType1) : ""}`);
  if (p.wxString) parts.push(escapeHtml(p.wxString));
  return `<b>${escapeHtml(p.icaoId ?? "PIREP")}</b><br>${parts.join(" · ")}<br><div class="muted">${escapeHtml(p.rawOb ?? "")}</div>`;
}

export function createHazardLayers(CONFIG) {
  const sigmetGroup = L.layerGroup();
  const pirepGroup = L.layerGroup();

  function renderSigmets(sigmets) {
    sigmetGroup.clearLayers();
    for (const s of sigmets) {
      if (!Array.isArray(s.coords)) continue;
      const rings = ringOf(s.coords);
      if (rings.length === 0) continue;
      L.polygon(rings, {
        color: CONFIG.tokens.orange,
        weight: 1.5,
        fillOpacity: 0.15,
        fillColor: CONFIG.tokens.orange,
      })
        .bindPopup(sigmetPopupHtml(s))
        .addTo(sigmetGroup);
    }
  }

  function renderPireps(pireps) {
    pirepGroup.clearLayers();
    for (const p of pireps) {
      if (typeof p.lat !== "number" || typeof p.lon !== "number") continue;
      L.circleMarker([p.lat, p.lon], {
        radius: 5,
        color: CONFIG.tokens.blue,
        weight: 2,
        fillColor: CONFIG.tokens.blue,
        fillOpacity: 0.5,
      })
        .bindPopup(pirepPopupHtml(p))
        .addTo(pirepGroup);
    }
  }

  return { sigmetGroup, pirepGroup, renderSigmets, renderPireps };
}
