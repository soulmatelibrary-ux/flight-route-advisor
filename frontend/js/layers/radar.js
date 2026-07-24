/**
 * 기상 레이더(RainViewer) 토글 + 재생 바 (docs/10-ui-and-realtime.md §2.5 레이어⑤).
 * 결정 포커스 기본 OFF, 온디맨드 로드(레이어 컨트롤에서 켤 때만 프레임 메타 fetch) —
 * 원본 문서/01 §RainViewer·문서/05_트러블슈팅.md(maxNativeZoom 6) 그대로 이식.
 *
 * 실측 확인(2026-07-23, WebFetch/curl 직접): `api.rainviewer.com/public/weather-maps.json`
 * → `radar.past`(과거 2시간, ~10분 간격 프레임) + `tilecache.rainviewer.com` 둘 다
 * `Access-Control-Allow-Origin: *` — 프록시 불필요, `fetch()` 직접 호출.
 *
 * 체크박스로 켜면(overlayadd) 프레임 로드 직후 자동으로 무한재생 시작(사용자 요청,
 * 2026-07-24) — 이전엔 로드만 하고 사용자가 재생 버튼을 눌러야 움직였다. 껐다 켤 때도
 * resetFrames()가 playTimer를 정지시켜 두므로(overlayremove→pause) 매번 재생 안 된
 * 상태에서 시작해 정상적으로 play()가 토글이 아니라 "시작"으로 동작한다.
 */
const L = window.L;

function kstLabel(epochSeconds) {
  const d = new Date(epochSeconds * 1000 + 9 * 3600 * 1000);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${hh}:${mm} KST`;
}

export function createRadarLayer(map, CONFIG) {
  const group = L.layerGroup();
  let frames = []; // [{time, tileLayer}]
  let frameIndex = -1;
  let loaded = false;
  let loading = null;
  let playTimer = null;

  const barEl = document.getElementById("radar-bar");
  const sliderEl = document.getElementById("radar-slider");
  const labelEl = document.getElementById("radar-time");
  const playBtn = document.getElementById("radar-play-btn");

  function showBar(show) {
    if (barEl) barEl.hidden = !show;
  }

  function setFrame(index) {
    if (frames.length === 0) return;
    frameIndex = Math.max(0, Math.min(index, frames.length - 1));
    for (let i = 0; i < frames.length; i++) {
      frames[i].tileLayer.setOpacity(i === frameIndex ? CONFIG.radar.opacity : 0);
    }
    if (sliderEl) sliderEl.value = String(frameIndex);
    if (labelEl) labelEl.textContent = kstLabel(frames[frameIndex].time);
  }

  // loaded는 "이번에 켜진 동안 유효한" 캐시일 뿐 영구 캐시가 아니다(리뷰 지적사항,
  // 2026-07-23) — RainViewer 프레임은 ~10분마다 갱신되는데 loaded를 리셋하지 않으면
  // 껐다 켜도 최초 로드 시점의 오래된 프레임에 계속 머문다. overlayremove에서 리셋해
  // 다음 켤 때 항상 최신 프레임을 다시 받아온다(hazards.js의 "토글 재클릭으로 갱신"과
  // 동일 원칙으로 통일).
  function resetFrames() {
    group.clearLayers();
    frames = [];
    frameIndex = -1;
    loaded = false;
  }

  async function ensureLoaded() {
    if (loaded) return;
    if (loading) return loading;
    loading = (async () => {
      const res = await fetch(CONFIG.radar.framesUrl);
      if (!res.ok) throw new Error(`RainViewer HTTP ${res.status}`);
      const meta = await res.json();
      const past = Array.isArray(meta?.radar?.past) ? meta.radar.past : [];
      frames = past.map((frame) => ({
        time: frame.time,
        tileLayer: L.tileLayer(`${meta.host}${frame.path}/${CONFIG.radar.tileSize}/{z}/{x}/{y}/${CONFIG.radar.color}/${CONFIG.radar.options}.png`, {
          maxNativeZoom: CONFIG.radar.maxNativeZoom,
          opacity: 0,
        }).addTo(group),
      }));
      loaded = true;
      if (sliderEl) sliderEl.max = String(Math.max(0, frames.length - 1));
      if (frames.length > 0) setFrame(frames.length - 1); // 최신 프레임부터(원본 04_핵심알고리즘 "최신부터")
    })();
    try {
      await loading;
    } finally {
      loading = null;
    }
  }

  function pause() {
    if (playTimer) {
      clearInterval(playTimer);
      playTimer = null;
    }
    if (playBtn) playBtn.textContent = "▶";
  }

  function play() {
    if (frames.length === 0) return;
    if (playTimer) {
      pause();
      return;
    }
    if (playBtn) playBtn.textContent = "⏸";
    playTimer = setInterval(() => {
      setFrame((frameIndex + 1) % frames.length);
    }, CONFIG.radar.playIntervalMs);
  }

  map.on("overlayadd", async (e) => {
    if (e.layer !== group) return;
    showBar(true);
    if (labelEl) labelEl.textContent = "불러오는 중…";
    if (sliderEl) sliderEl.disabled = true;
    try {
      await ensureLoaded();
      if (sliderEl) sliderEl.disabled = false;
      play(); // 체크 즉시 무한재생(사용자 요청, 2026-07-24) — 이전엔 재생 버튼을 눌러야 시작했음
    } catch {
      // 프레임 메타 조회 실패 — 재생바는 그대로 보이되 실패 상태를 명시(리뷰 지적사항,
      // 2026-07-23: 이전엔 무반응 컨트롤만 남아 사용자가 고장인지 구분할 수 없었음)
      if (labelEl) labelEl.textContent = "레이더 로드 실패";
    }
  });
  map.on("overlayremove", (e) => {
    if (e.layer !== group) return;
    showBar(false);
    pause();
    resetFrames();
  });

  sliderEl?.addEventListener("input", () => {
    pause();
    setFrame(Number(sliderEl.value));
  });
  playBtn?.addEventListener("click", play);

  return { group };
}
