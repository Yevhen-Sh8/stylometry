/* ══════════════════════════════════════════════════════════════
   Stylometric Analysis — Frontend JavaScript
   ══════════════════════════════════════════════════════════════ */

"use strict";

// ─────────────────────────────────────────────────────────────
//  STATE
// ─────────────────────────────────────────────────────────────
const state = {
  sources: [],   // [{label, tokens, type, warn}]
};

const MATH = {
  delta: '<span class="math-inline">&Delta;<sub>Burrows</sub></span>',
  thetaDelta: '<span class="math-inline">&theta;<sub>&Delta;</sub></span>',
  rDims: '<span class="math-inline">R<sub>DIMS</sub></span>',
  iContent: '<span class="math-inline">I<sub>content</sub></span>',
  iCoord: '<span class="math-inline">I<sub>coord</sub></span>',
  iDynamics: '<span class="math-inline">I<sub>dynamics</sub></span>',
  iImpact: '<span class="math-inline">I<sub>impact</sub></span>',
  iSource: '<span class="math-inline">I<sub>source</sub></span>',
};

// ─────────────────────────────────────────────────────────────
//  DOM REFS
// ─────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);

const els = {
  // Tabs
  tabBtns:      document.querySelectorAll(".tab-btn"),
  tabPanels:    document.querySelectorAll(".tab-panel"),
  // File upload
  dropzone:     $("dropzone"),
  fileInput:    $("fileInput"),
  uploadProg:   $("uploadProgress"),
  uploadFill:   $("uploadProgressFill"),
  // URL
  urlInput:     $("urlInput"),
  urlLabel:     $("urlLabel"),
  btnAddUrl:    $("btnAddUrl"),
  // Text
  textInput:    $("textInput"),
  textLabel:    $("textLabel"),
  btnAddText:   $("btnAddText"),
  // HTML
  htmlInput:    $("htmlInput"),
  htmlLabel:    $("htmlLabel"),
  htmlUrl:      $("htmlUrl"),
  btnAddHtml:   $("btnAddHtml"),
  // Sources
  sourcesList:  $("sourcesList"),
  sourcesEmpty: $("sourcesEmpty"),
  sourcesCount: $("sourcesCount"),
  // Params
  mfwSlider:    $("mfwSlider"),
  mfwInput:     $("mfwInput"),
  thrSlider:    $("thresholdSlider"),
  thrInput:     $("thresholdInput"),
  // Run
  btnAnalyze:   $("btnAnalyze"),
  runHint:      $("runHint"),
  btnAnalyzeIcon: $("btnAnalyzeIcon"),
  btnAnalyzeText: $("btnAnalyzeText"),
  btnClearAll:  $("btnClearAll"),
  // Results
  sectionResults: $("sectionResults"),
  statsGrid:    $("statsGrid"),
  flaggedQuick: $("flaggedQuick"),
  // Overlay / toast
  overlay:      $("overlay"),
  overlayText:  $("overlayText"),
  toast:        $("toast"),
};

// ─────────────────────────────────────────────────────────────
//  UTILITIES
// ─────────────────────────────────────────────────────────────
function showToast(msg, type = "info", duration = 3500) {
  const t = els.toast;
  t.textContent = msg;
  t.className = `toast ${type}`;
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.add("hidden"), duration);
}

function showOverlay(text = "Аналіз...") {
  els.overlayText.textContent = text;
  els.overlay.classList.remove("hidden");
}
function hideOverlay() { els.overlay.classList.add("hidden"); }

async function api(path, method = "GET", body = null) {
  const opts = { method, headers: {} };
  if (body && !(body instanceof FormData)) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  } else if (body) {
    opts.body = body;
  }
  const resp = await fetch(path, opts);
  return resp.json();
}

function typeIcon(type) {
  const icons = { txt: "📄", pdf: "📕", docx: "📘", rtf: "📋",
                  html: "🌐", htm: "🌐", url: "🔗", text: "✏️", "": "📄" };
  return icons[type] || "📄";
}

function sourcePrimaryText(source) {
  return escHtml(source.display_title || source.label);
}

function sourceLinkHtml(source, className = "source-link") {
  const href = source.url || source.local_text_url || "";
  const text = sourcePrimaryText(source);
  if (!href) return `<span class="${className}">${text}</span>`;
  const safeHref = escHtml(href);
  return `<a class="${className}" href="${safeHref}" target="_blank" rel="noopener noreferrer">${text}</a>`;
}

function sourceContextHtml(source) {
  const parts = [];
  if (source.domain) parts.push(escHtml(source.domain));
  if (source.original_name) parts.push(escHtml(source.original_name));
  parts.push(`${source.tokens.toLocaleString("uk")} токенів`);
  parts.push(escHtml(source.type || "txt"));
  return parts.join(" &bull; ");
}

function sourceBreakdownHtml(rows) {
  if (!rows || !rows.length) return "";
  return `
    <div style="margin-top:12px; background:#fff; border:1px solid #dbeafe; border-radius:8px; overflow:hidden">
      <div style="padding:10px 14px; background:#eff6ff; color:#1e3a8a; font-weight:700">Розклад ${MATH.iSource}</div>
      ${rows.map(row => `
        <div style="display:flex; justify-content:space-between; gap:12px; padding:10px 14px; border-top:1px solid #e5eefc; font-size:12px">
          <div style="min-width:0">
            ${sourceLinkHtml(row.source, "flagged-link")}<br>
            <span style="color:#64748b">${escHtml(row.source.domain || row.source.label)}</span>
          </div>
          <div style="font-weight:700; color:${row.score >= 0.85 ? "#b91c1c" : row.score >= 0.55 ? "#c2410c" : "#2563eb"}">${row.score.toFixed(3)}</div>
        </div>
      `).join("")}
    </div>`;
}

// ─────────────────────────────────────────────────────────────
//  TABS
// ─────────────────────────────────────────────────────────────
els.tabBtns.forEach(btn => {
  btn.addEventListener("click", () => {
    const target = btn.dataset.tab;
    els.tabBtns.forEach(b => b.classList.remove("active"));
    els.tabPanels.forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`tab-${target}`).classList.add("active");
  });
});

// ─────────────────────────────────────────────────────────────
//  SOURCE LIST RENDERING
// ─────────────────────────────────────────────────────────────
function renderSources() {
  const list = state.sources;
  els.sourcesCount.textContent = list.length;

  if (list.length === 0) {
    els.sourcesList.innerHTML = "";
    els.sourcesEmpty.style.display = "block";
    els.btnAnalyze.disabled = true;
    els.runHint.textContent = "Додайте мінімум 2 джерела для запуску";
    return;
  }

  els.sourcesEmpty.style.display = "none";
  els.sourcesList.innerHTML = list.map((s, i) => `
    <div class="source-item" data-label="${encodeURIComponent(s.label)}">
      <span class="source-icon">${typeIcon(s.type)}</span>
      <div class="source-info">
        <div class="source-label">${sourceLinkHtml(s)}</div>
        <div class="source-meta">
          ${sourceContextHtml(s)}
          ${s.warn ? '<span class="source-warn"> ⚠ &lt;500 токенів</span>' : ""}
        </div>
        ${s.preview ? `<div class="source-preview">${escHtml(s.preview)}</div>` : ""}
      </div>
      <button class="source-remove" title="Видалити" data-idx="${i}">✕</button>
    </div>
  `).join("");

  // Remove buttons
  els.sourcesList.querySelectorAll(".source-remove").forEach(btn => {
    btn.addEventListener("click", async () => {
      const label = state.sources[+btn.dataset.idx].label;
      await api("/api/remove", "POST", { label });
      state.sources.splice(+btn.dataset.idx, 1);
      renderSources();
    });
  });

  els.btnAnalyze.disabled = list.length < 2;
  els.runHint.textContent = list.length < 2
    ? "Ще потрібно ще одне джерело"
    : `${list.length} джерел готові до аналізу`;
}

function escHtml(s) {
  return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

function addSource(meta) {
  // Replace if same label already exists
  const idx = state.sources.findIndex(s => s.label === meta.label);
  if (idx >= 0) state.sources[idx] = meta; else state.sources.push(meta);
  renderSources();
}

// ─────────────────────────────────────────────────────────────
//  FILE UPLOAD
// ─────────────────────────────────────────────────────────────
async function handleFiles(fileList) {
  if (!fileList.length) return;
  const fd = new FormData();
  [...fileList].forEach(f => fd.append("files", f));

  els.uploadProg.style.display = "block";
  els.uploadFill.style.width   = "30%";

  try {
    const data = await api("/api/upload", "POST", fd);
    els.uploadFill.style.width = "100%";
    setTimeout(() => { els.uploadProg.style.display = "none"; els.uploadFill.style.width = "0"; }, 600);

    if (!data.ok) { showToast(data.error, "error"); return; }

    data.added.forEach(s => addSource(s));
    if (data.added.length) showToast(`✅ Додано ${data.added.length} файл(ів)`, "success");
    if (data.skipped.length) showToast(`⚠ Пропущено: ${data.skipped.join(", ")}`, "error", 5000);
  } catch (e) {
    showToast("Помилка завантаження файлів", "error");
  } finally {
    // Allow selecting the same file again in the next attempt.
    els.fileInput.value = "";
  }
}

els.fileInput.addEventListener("change", e => handleFiles(e.target.files));
els.dropzone.addEventListener("click", e => {
  // Clicking the embedded label already opens the picker; avoid double-open.
  if (e.target.closest("label")) return;
  els.fileInput.click();
});
els.dropzone.addEventListener("dragover", e => { e.preventDefault(); els.dropzone.classList.add("drag-over"); });
els.dropzone.addEventListener("dragleave", () => els.dropzone.classList.remove("drag-over"));
els.dropzone.addEventListener("drop", e => {
  e.preventDefault();
  els.dropzone.classList.remove("drag-over");
  handleFiles(e.dataTransfer.files);
});

// ─────────────────────────────────────────────────────────────
//  ADD URL
// ─────────────────────────────────────────────────────────────
els.btnAddUrl.addEventListener("click", async () => {
  const url   = els.urlInput.value.trim();
  const label = els.urlLabel.value.trim();
  if (!url) { showToast("Введіть URL", "error"); return; }

  els.btnAddUrl.disabled = true;
  showOverlay("Завантажую статтю...");

  try {
    const data = await api("/api/add-url", "POST", { url, label });
    if (!data.ok) { showToast(data.error, "error"); return; }
    addSource(data.source);
    showToast(`✅ Додано: ${data.source.label}`, "success");
    els.urlInput.value = "";
    els.urlLabel.value = "";
  } catch (e) {
    showToast("Мережева помилка", "error");
  } finally {
    els.btnAddUrl.disabled = false;
    hideOverlay();
  }
});

els.urlInput.addEventListener("keydown", e => { if (e.key === "Enter") els.btnAddUrl.click(); });

// ─────────────────────────────────────────────────────────────
//  ADD TEXT
// ─────────────────────────────────────────────────────────────
els.btnAddText.addEventListener("click", async () => {
  const text  = els.textInput.value.trim();
  const label = els.textLabel.value.trim();
  if (!text) { showToast("Вставте текст", "error"); return; }

  els.btnAddText.disabled = true;
  try {
    const data = await api("/api/add-text", "POST", { text, label });
    if (!data.ok) { showToast(data.error, "error"); return; }
    addSource(data.source);
    showToast(`✅ Додано: ${data.source.label}`, "success");
    els.textInput.value = "";
    els.textLabel.value = "";
  } catch (e) {
    showToast("Помилка", "error");
  } finally {
    els.btnAddText.disabled = false;
  }
});

// ─────────────────────────────────────────────────────────────
//  ADD HTML
// ─────────────────────────────────────────────────────────────
els.btnAddHtml.addEventListener("click", async () => {
  const html = els.htmlInput.value.trim();
  const label = els.htmlLabel.value.trim();
  const url = els.htmlUrl.value.trim();
  if (!html) { showToast("Вставте HTML", "error"); return; }

  els.btnAddHtml.disabled = true;
  showOverlay("Очищаю HTML...");
  try {
    const data = await api("/api/add-html", "POST", { html, label, url });
    if (!data.ok) { showToast(data.error, "error", 6000); return; }
    addSource(data.source);
    showToast(`✅ Додано: ${data.source.display_title || data.source.label}`, "success");
    els.htmlInput.value = "";
    els.htmlLabel.value = "";
    els.htmlUrl.value = "";
  } catch (e) {
    showToast("Помилка обробки HTML", "error");
  } finally {
    els.btnAddHtml.disabled = false;
    hideOverlay();
  }
});

// ─────────────────────────────────────────────────────────────
//  CLEAR ALL
// ─────────────────────────────────────────────────────────────
els.btnClearAll.addEventListener("click", async () => {
  if (!state.sources.length) return;
  if (!confirm("Видалити всі джерела?")) return;
  await api("/api/clear", "POST");
  state.sources = [];
  els.sectionResults.classList.add("hidden");
  renderSources();
  showToast("Всі джерела видалено");
});

// ─────────────────────────────────────────────────────────────
//  PARAMETER SYNC (slider ↔ number input)
// ─────────────────────────────────────────────────────────────
function syncInputs(slider, input) {
  slider.addEventListener("input", () => { input.value = slider.value; });
  input.addEventListener("input", () => {
    const v = parseFloat(input.value);
    if (!isNaN(v)) slider.value = v;
  });
}
syncInputs(els.mfwSlider, els.mfwInput);
syncInputs(els.thrSlider,  els.thrInput);

// ─────────────────────────────────────────────────────────────
//  ANALYZE
// ─────────────────────────────────────────────────────────────
els.btnAnalyze.addEventListener("click", async () => {
  const mfw       = parseInt(els.mfwInput.value) || 100;
  const threshold = parseFloat(els.thrInput.value) || 0.8;

  els.btnAnalyze.disabled = true;
  els.btnAnalyzeIcon.textContent = "⏳";
  els.btnAnalyzeText.textContent = "Аналізую...";
  showOverlay("Запускаю стилометричний аналіз...");

  try {
    const data = await api("/api/analyze", "POST", { mfw, threshold });

    if (!data.ok) {
      showToast(data.error, "error");
      return;
    }

    renderResults(data);
    els.sectionResults.classList.remove("hidden");
    els.sectionResults.scrollIntoView({ behavior: "smooth", block: "start" });
    showToast("✅ Аналіз завершено", "success");

  } catch (e) {
    showToast("Помилка під час аналізу", "error");
  } finally {
    els.btnAnalyze.disabled = false;
    els.btnAnalyzeIcon.textContent = "🚀";
    els.btnAnalyzeText.textContent = "Запустити аналіз";
    hideOverlay();
  }
});

// ─────────────────────────────────────────────────────────────
//  RENDER RESULTS
// ─────────────────────────────────────────────────────────────
function renderResults(data) {
  // KPI cards
  const nFlagged = data.n_flagged;
  const dims = data.dims_assessment;
  els.statsGrid.innerHTML = `
    <div class="stat-card info">
      <div class="stat-value">${data.n_sources}</div>
      <div class="stat-label">Джерел</div>
    </div>
    <div class="stat-card info">
      <div class="stat-value">${data.n_pairs}</div>
      <div class="stat-label">Пар порівняно</div>
    </div>
    <div class="stat-card ${nFlagged > 0 ? "danger" : "ok"}">
      <div class="stat-value">${nFlagged}</div>
      <div class="stat-label">Підозрілих пар</div>
    </div>
    <div class="stat-card ${dims.grade.grade === "SSS" || dims.grade.grade === "SS" ? "danger" : dims.grade.grade === "S" ? "info" : "ok"}">
      <div class="stat-value">${dims.grade.grade}</div>
      <div class="stat-label">DIMS-грейд</div>
    </div>
    <div class="stat-card info">
      <div class="stat-value">${dims.r_dims.toFixed(3)}</div>
      <div class="stat-label">${MATH.rDims}</div>
    </div>
  `;

  // Flagged pairs
  const dimsSummary = `
      <div style="padding:16px; background:#eff6ff; border:1px solid #bfdbfe;
                border-radius:8px; color:#1d4ed8; font-weight:600; margin-bottom:16px">
      ${MATH.rDims} = ${dims.r_dims.toFixed(4)} &bull;
      ${MATH.iContent} = ${dims.indicators.I_content.toFixed(3)} &bull;
      ${MATH.iCoord} = ${dims.indicators.I_coord.toFixed(3)} &bull;
      ${MATH.iDynamics} = ${dims.indicators.I_dynamics.toFixed(3)} &bull;
      ${MATH.iImpact} = ${dims.indicators.I_impact.toFixed(3)} &bull;
      ${MATH.iSource} = ${dims.indicators.I_source.toFixed(3)} &bull;
      Грейд = ${dims.grade.grade} (${escHtml(dims.grade.label)})
    </div>
    ${sourceBreakdownHtml(data.source_breakdown)}`;

  if (data.flagged.length === 0) {
    els.flaggedQuick.innerHTML = `
      ${dimsSummary}
      <div style="padding:16px; background:#f0fdf4; border:1px solid #bbf7d0;
                  border-radius:8px; color:#15803d; font-weight:600; margin-bottom:16px">
        ✅ Підозрілих пар не виявлено
      </div>`;
  } else {
    els.flaggedQuick.innerHTML = `
      ${dimsSummary}
      <h3 style="font-size:14px;font-weight:700;margin-bottom:10px">
        Підозрілі пари (${MATH.delta} &lt; ${MATH.thetaDelta} = ${data.flagged[0]?.delta !== undefined ? parseFloat(els.thrInput.value) : "?"})
      </h3>
      ${data.flagged.map(f => `
        <div class="flagged-item ${f.severity.css}">
          <span class="flagged-icon">${f.severity.icon}</span>
          <div class="flagged-info">
            <div class="flagged-names">${sourceLinkHtml(f.a_meta, "flagged-link")} ↔ ${sourceLinkHtml(f.b_meta, "flagged-link")}</div>
            <div class="flagged-delta">${MATH.delta} = ${f.delta.toFixed(4)} &bull; ${f.severity.label}</div>
            <div class="flagged-context">${sourceContextHtml(f.a_meta)}<br>${sourceContextHtml(f.b_meta)}</div>
          </div>
        </div>
      `).join("")}
    `;
  }

}

// ─────────────────────────────────────────────────────────────
//  INIT
// ─────────────────────────────────────────────────────────────
renderSources();
