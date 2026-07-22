(function () {
  const content = document.getElementById("table-content");
  const tabs = Array.from(document.querySelectorAll(".subtabs .tab"));
  if (!content || !tabs.length) return;

  let currentTable = null;
  let requestToken = 0;

  function setActiveTab(name) {
    tabs.forEach((a) => a.classList.toggle("active", a.dataset.table === name));
  }

  async function loadTable(name, page, runId) {
    currentTable = name;
    setActiveTab(name);
    const token = ++requestToken;
    content.innerHTML = `
      <div class="loading-container">
        <div class="spinner"></div>
        <span>데이터를 불러오는 중입니다...</span>
      </div>
    `;

    let url = `/tables/${encodeURIComponent(name)}?partial=1&page=${encodeURIComponent(page)}`;
    if (runId) url += `&run_id=${encodeURIComponent(runId)}`;

    try {
      const res = await fetch(url);
      if (token !== requestToken) return; // 그 사이 다른 요청이 시작됨 — 이 응답은 버림
      if (!res.ok) throw new Error(String(res.status));
      content.innerHTML = await res.text();
    } catch (err) {
      if (token !== requestToken) return;
      content.innerHTML = `
        <div class="error-container">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="error-icon"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
          <span>데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.</span>
        </div>
      `;
    }
  }

  // JS가 정상 로드된 경우에만 탭 링크를 가로챈다. JS가 실패하면 href가 그대로
  // 동작해 전체 페이지(/tables/{table_name})로 이동한다(무JS 대비).
  tabs.forEach((a) => {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      loadTable(a.dataset.table, 1, null);
    });
  });

  content.addEventListener("click", (e) => {
    const link = e.target.closest("a[data-page]");
    if (!link || !currentTable) return;
    e.preventDefault();
    const pager = link.closest(".pager");
    const runId = pager ? pager.dataset.runId : "";
    loadTable(currentTable, link.dataset.page, runId || null);
  });

  loadTable(tabs[0].dataset.table, 1, null);
})();
