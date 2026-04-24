/* ══════════════════════════════════════════════════════════════
   Stylometric Analysis — Frontend JavaScript
   ══════════════════════════════════════════════════════════════ */

"use strict";

// ─────────────────────────────────────────────────────────────
//  THEME (auto/light/dark) — applied ASAP to avoid flash
// ─────────────────────────────────────────────────────────────
(function initTheme() {
  const saved = localStorage.getItem("dims-theme") || "auto";
  document.documentElement.setAttribute("data-theme", saved);
})();

function setTheme(value) {
  document.documentElement.setAttribute("data-theme", value);
  localStorage.setItem("dims-theme", value);
  document.querySelectorAll(".theme-toggle button[data-theme-value]").forEach(btn => {
    btn.setAttribute("aria-pressed", btn.dataset.themeValue === value ? "true" : "false");
  });
}

document.addEventListener("DOMContentLoaded", () => {
  const current = localStorage.getItem("dims-theme") || "auto";
  document.querySelectorAll(".theme-toggle button[data-theme-value]").forEach(btn => {
    btn.setAttribute("aria-pressed", btn.dataset.themeValue === current ? "true" : "false");
    btn.addEventListener("click", () => setTheme(btn.dataset.themeValue));
  });
  loadManifestationTypes();
  initLogDrawer();
});

// ─────────────────────────────────────────────────────────────
//  GRADE BADGE — уніфіковане подання F/B/S/SS/SSS
//  (Методика НУЗРКС МОУ № 46 від 28.11.2022).
// ─────────────────────────────────────────────────────────────
function gradeBadgeHtml(grade, opts = {}) {
  if (!grade) return "";
  const code = String(grade.grade || "F").toUpperCase();
  const size = opts.size || "md";               // sm | md | lg
  const withLabel = opts.withLabel !== false;
  const withR = opts.r_dims != null;
  const taboo = !!grade.forced_by_taboo;

  const parts = [`<span class="grade-code">${escHtml(code)}</span>`];
  if (withLabel && grade.label) {
    parts.push(`<span class="grade-meta">${escHtml(grade.label)}</span>`);
  }
  if (withR) {
    parts.push(`<span class="grade-meta">R=${Number(opts.r_dims).toFixed(3)}</span>`);
  }
  if (taboo) parts.push(`<span class="grade-flag" aria-hidden="true"></span>`);

  const cls = ["grade-badge", `is-${size}`, taboo ? "is-taboo" : ""].filter(Boolean).join(" ");
  const title = taboo
    ? "Грейд автоматично підвищено до SS згідно з Методикою (вид прояву «табу»)."
    : (grade.label || "");
  return `<span class="${cls}" data-grade="${code}" title="${escHtml(title)}">${parts.join("")}</span>`;
}

// ─────────────────────────────────────────────────────────────
//  CRITICAL ALERT BANNER — sticky попередження про SS/SSS/табу.
//  Відображається у верхній частині результатів; керує керівник,
//  не гортаючи звіт у пошуках критичного.
// ─────────────────────────────────────────────────────────────
function renderCriticalAlert(dims, flagged) {
  const slot = document.getElementById("criticalAlert");
  if (!slot) return;
  slot.innerHTML = "";
  if (!dims || !dims.grade) return;

  const code = String(dims.grade.grade || "").toUpperCase();
  const taboo = !!dims.grade.forced_by_taboo;
  const rdims = Number(dims.r_dims || 0);
  const isCritical = code === "SSS" || taboo || rdims >= 0.8;
  const isHigh = !isCritical && code === "SS";
  if (!isCritical && !isHigh) return;

  // Dismiss-per-fingerprint: не нав'язуємось при повторному рендері того ж аналізу.
  const fp = (LAST_RESULTS_FP || "") + ":" + code + ":" + (taboo ? "T" : "");
  try {
    if (sessionStorage.getItem("dims-cb-dismissed") === fp) return;
  } catch (_) { /* privacy mode */ }

  const nFlagged = Array.isArray(flagged) ? flagged.length : 0;
  const critPairs = (flagged || []).filter(f => (f.severity && f.severity.css) === "critical").length;
  const parts = [];
  if (taboo) parts.push("виявлено вид прояву «табу»");
  if (critPairs) parts.push(`${critPairs} критичних пар`);
  else if (nFlagged) parts.push(`${nFlagged} підозрілих пар`);
  if (!parts.length) parts.push(`R<sub>DIMS</sub> = ${rdims.toFixed(3)} перевищує поріг`);
  const msg = parts.join(" · ");

  const cls = isCritical ? "is-critical" : "is-high";
  const role = isCritical ? 'role="alert" aria-live="assertive"' : 'role="status" aria-live="polite"';
  const label = isCritical ? "КРИТИЧНО" : "ВИСОКИЙ РИЗИК";
  const icon = taboo ? "⚑" : "⚠";

  slot.innerHTML = `
    <div class="critical-banner ${cls}" ${role}>
      <div class="cb-icon" aria-hidden="true">${icon}</div>
      <div class="cb-body">
        <div class="cb-title">
          <span>${label} · ${escHtml(code)}</span>
          <span class="cb-rdims">R<sub>DIMS</sub> = ${rdims.toFixed(3)}</span>
        </div>
        <div class="cb-msg">${msg}</div>
      </div>
      ${nFlagged ? `<button class="cb-cta" type="button" id="cbGotoFlagged">Переглянути пари →</button>` : ""}
      <button class="cb-close" type="button" aria-label="Приховати сповіщення" id="cbClose">✕</button>
    </div>`;

  const cta = document.getElementById("cbGotoFlagged");
  if (cta) cta.addEventListener("click", () => {
    const first = document.querySelector("#flaggedQuick .flagged-item");
    if (first) {
      first.scrollIntoView({ behavior: "smooth", block: "center" });
      first.classList.add("flagged-pair-hot");
      setTimeout(() => first.classList.remove("flagged-pair-hot"), 2000);
    }
  });
  document.getElementById("cbClose").addEventListener("click", () => {
    slot.innerHTML = "";
    try { sessionStorage.setItem("dims-cb-dismissed", fp); } catch (_) {}
  });
}

// ─────────────────────────────────────────────────────────────
//  DIMS INDICATOR RADAR — 5-осьовий SVG-радар.
//  Показує сирі значення I_* (заливка) та вклад у R_DIMS з урахуванням
//  ваг (пунктирний контур). Робить прозорим, який чинник тягне грейд.
// ─────────────────────────────────────────────────────────────
function renderDimsRadarSvg(indicators, weights, opts = {}) {
  if (!indicators) return "";
  const AXES = [
    { key: "I_content",  label: "I_content",  wKey: "content"  },
    { key: "I_coord",    label: "I_coord",    wKey: "coord"    },
    { key: "I_dynamics", label: "I_dynamics", wKey: "dynamics" },
    { key: "I_impact",   label: "I_impact",   wKey: "impact"   },
    { key: "I_source",   label: "I_source",   wKey: "source"   },
  ];
  const size = opts.size === "lg" ? 480 : (opts.size === "sm" ? 240 : 360);
  const cx = size / 2, cy = size / 2;
  const R = size * 0.36;  // radius for value=1.0
  const N = AXES.length;
  const angle = (i) => -Math.PI / 2 + (i * 2 * Math.PI) / N;

  const pointAt = (i, v) => {
    const r = R * Math.max(0, Math.min(1, v));
    return [cx + r * Math.cos(angle(i)), cy + r * Math.sin(angle(i))];
  };

  // Grid rings (0.25, 0.5, 0.75, 1.0)
  const rings = [0.25, 0.5, 0.75, 1.0].map(frac => {
    const pts = AXES.map((_, i) => {
      const [x, y] = pointAt(i, frac);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
    return `<polygon class="radar-grid" points="${pts}"/>`;
  }).join("");

  // Axes
  const axes = AXES.map((_, i) => {
    const [x, y] = pointAt(i, 1);
    return `<line class="radar-axis" x1="${cx}" y1="${cy}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}"/>`;
  }).join("");

  // Raw polygon
  const rawVals = AXES.map(a => Number(indicators[a.key] || 0));
  const rawPts = rawVals.map((v, i) => {
    const [x, y] = pointAt(i, v);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");

  // Weighted polygon: contribution = w * I (normalized to max contribution so shape is visible)
  let weightedPoly = "";
  if (weights) {
    const contribs = AXES.map(a => Number(weights[a.wKey] || 0) * Number(indicators[a.key] || 0));
    const maxC = Math.max(...contribs, 0.001);
    const pts = contribs.map((c, i) => {
      const [x, y] = pointAt(i, c / maxC);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
    weightedPoly = `<polygon class="radar-weighted" points="${pts}"/>`;
  }

  // Points
  const points = rawVals.map((v, i) => {
    const [x, y] = pointAt(i, v);
    return `<circle class="radar-point" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3"/>`;
  }).join("");

  // Labels + values
  const labels = AXES.map((a, i) => {
    const [lx, ly] = pointAt(i, 1.18);
    const v = rawVals[i].toFixed(2);
    const w = weights ? (weights[a.wKey] || 0).toFixed(2) : null;
    return `
      <text class="radar-label" x="${lx.toFixed(1)}" y="${ly.toFixed(1)}">${a.label}</text>
      <text class="radar-value" x="${lx.toFixed(1)}" y="${(ly + 12).toFixed(1)}">
        ${v}${w !== null ? ` · w=${w}` : ""}
      </text>`;
  }).join("");

  const sizeClass = opts.size === "lg" ? "is-lg" : (opts.size === "sm" ? "is-sm" : "");
  return `
    <div class="dims-radar-wrap">
      <div class="radar-title">Профіль індикаторів DIMS</div>
      <svg class="dims-radar ${sizeClass}" viewBox="0 0 ${size} ${size}" role="img"
           aria-label="Радар 5 індикаторів DIMS">
        ${rings}
        ${axes}
        <polygon class="radar-raw" points="${rawPts}"/>
        ${weightedPoly}
        ${points}
        ${labels}
      </svg>
      <div class="radar-legend">
        <span><span class="radar-legend-swatch raw"></span>сирі значення I</span>
        ${weights ? `<span><span class="radar-legend-swatch weighted"></span>внесок w·I у R<sub>DIMS</sub></span>` : ""}
      </div>
    </div>`;
}

// ─────────────────────────────────────────────────────────────
//  TIMELINE STRIP — стрічка активності журналу моніторингу.
//  Клік на тик → фільтрує записи за днем.
// ─────────────────────────────────────────────────────────────
let _logAllRecords = [];
let _logActiveDay = null;

function renderTimelineStrip(records) {
  const slot = document.getElementById("logTimelineStrip");
  if (!slot) return;
  if (!records.length) { slot.innerHTML = ""; return; }

  // Bucket by ISO date (YYYY-MM-DD)
  const byDay = new Map();
  for (const r of records) {
    const day = (r.timestamp || "").slice(0, 10);
    if (!day) continue;
    const entry = byDay.get(day) || { count: 0, maxGrade: "F" };
    entry.count += 1;
    const g = String(r.grade || r.dims_grade || "F").toUpperCase();
    if (gradeRank(g) > gradeRank(entry.maxGrade)) entry.maxGrade = g;
    byDay.set(day, entry);
  }

  // Last 14 days axis
  const days = [];
  const today = new Date();
  for (let i = 13; i >= 0; i--) {
    const d = new Date(today); d.setDate(today.getDate() - i);
    days.push(d.toISOString().slice(0, 10));
  }
  const maxCount = Math.max(1, ...[...byDay.values()].map(v => v.count));
  const totalShown = days.reduce((s, d) => s + ((byDay.get(d) || {}).count || 0), 0);

  const ticks = days.map(day => {
    const info = byDay.get(day);
    const h = info ? Math.max(12, (info.count / maxCount) * 100) : 8;
    const grade = info ? info.maxGrade : "";
    const activeCls = day === _logActiveDay ? " is-active" : "";
    const emptyCls = info ? "" : " is-empty";
    const title = info
      ? `${day} · ${info.count} джерел · max ${info.maxGrade}`
      : `${day} · немає даних`;
    return `<div class="timeline-tick${activeCls}${emptyCls}"
                 style="height:${h}%"
                 data-day="${day}"
                 ${grade ? `data-grade="${grade}"` : ""}
                 title="${title}"
                 role="button" tabindex="0"></div>`;
  }).join("");

  slot.innerHTML = `
    <div class="timeline-strip">
      <div class="timeline-axis">${ticks}</div>
      <div class="timeline-legend">
        <span>14 днів</span>
        <span class="timeline-summary">${records.length} записів · ${byDay.size} активних днів</span>
        <button class="timeline-clear" id="timelineClear" type="button"
                ${_logActiveDay ? "" : "hidden"}>× скинути фільтр</button>
      </div>
    </div>`;

  slot.querySelectorAll(".timeline-tick").forEach(t => {
    const handler = () => {
      const day = t.dataset.day;
      if (!byDay.has(day)) return;
      _logActiveDay = (_logActiveDay === day) ? null : day;
      renderTimelineStrip(_logAllRecords);
      renderLogTable(filterRecords(_logAllRecords));
    };
    t.addEventListener("click", handler);
    t.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); handler(); } });
  });
  const clearBtn = document.getElementById("timelineClear");
  if (clearBtn) clearBtn.addEventListener("click", () => {
    _logActiveDay = null;
    renderTimelineStrip(_logAllRecords);
    renderLogTable(filterRecords(_logAllRecords));
  });
}

function gradeRank(g) {
  return { "F": 0, "B": 1, "S": 2, "SS": 3, "SSS": 4 }[String(g).toUpperCase()] || 0;
}

function filterRecords(records) {
  if (!_logActiveDay) return records;
  return records.filter(r => (r.timestamp || "").slice(0, 10) === _logActiveDay);
}

function renderLogTable(records) {
  const body = document.getElementById("logDrawerBody");
  if (!body) return;
  if (!records.length) {
    body.innerHTML = `<p class="log-drawer-empty">${_logActiveDay
      ? "Немає записів за обраний день."
      : "Журнал порожній — джерела ще не опрацьовувалися."}</p>`;
    return;
  }
  const rows = records.slice().reverse().map(r => {
    const ts = (r.timestamp || "").replace("T", " ").slice(0, 19);
    const fp = (r.fingerprint || "").replace(/^sha256:/, "").slice(0, 10);
    const domain = r.domain || r.source_type || "—";
    return `<tr>
      <td>${escHtml(ts)}</td>
      <td class="label">${escHtml(r.label || r.display_title || "—")}</td>
      <td>${escHtml(domain)}</td>
      <td class="fp" title="${escHtml(r.fingerprint || "")}">${escHtml(fp)}…</td>
    </tr>`;
  }).join("");
  body.innerHTML = `
    <table class="log-table" aria-label="Журнал моніторингу">
      <thead><tr><th>Час</th><th>Джерело</th><th>Домен</th><th>Fingerprint</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

// ─────────────────────────────────────────────────────────────
//  MONITORING LOG DRAWER
// ─────────────────────────────────────────────────────────────
function initLogDrawer() {
  const btn = document.getElementById("btnOpenLog");
  const drawer = document.getElementById("logDrawer");
  const backdrop = document.getElementById("logDrawerBackdrop");
  const closeBtn = document.getElementById("logDrawerClose");
  if (!btn || !drawer) return;

  const open = async () => {
    drawer.hidden = false; backdrop.hidden = false;
    requestAnimationFrame(() => {
      drawer.classList.add("is-open");
      backdrop.classList.add("is-open");
    });
    drawer.setAttribute("aria-hidden", "false");
    btn.setAttribute("aria-expanded", "true");
    await loadMonitoringLog();
  };
  const close = () => {
    drawer.classList.remove("is-open");
    backdrop.classList.remove("is-open");
    drawer.setAttribute("aria-hidden", "true");
    btn.setAttribute("aria-expanded", "false");
    setTimeout(() => { drawer.hidden = true; backdrop.hidden = true; }, 220);
  };

  btn.addEventListener("click", open);
  closeBtn.addEventListener("click", close);
  backdrop.addEventListener("click", close);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && drawer.classList.contains("is-open")) close();
  });
}

async function loadMonitoringLog() {
  const body = document.getElementById("logDrawerBody");
  if (!body) return;
  body.innerHTML = `<p class="log-drawer-empty">Завантаження…</p>`;
  try {
    const resp = await fetch("/api/monitoring-log");
    const data = await resp.json();
    const records = Array.isArray(data.records) ? data.records : [];
    _logAllRecords = records;
    _logActiveDay = null;
    renderTimelineStrip(records);
    renderLogTable(records);
  } catch (err) {
    body.innerHTML = `<p class="log-drawer-empty">Не вдалося завантажити журнал: ${escHtml(String(err))}</p>`;
  }
}

// Завантаження переліку видів прояву DIMs відповідно до Методики
// НУЗРКС МОУ № 46 від 28.11.2022 (розділ 1).
async function loadManifestationTypes() {
  const select = document.getElementById("manifestationSelect");
  if (!select) return;
  try {
    const resp = await fetch("/api/manifestation-types");
    const data = await resp.json();
    if (!data.ok || !Array.isArray(data.types)) return;
    data.types.forEach(t => {
      const opt = document.createElement("option");
      opt.value = t.key;
      opt.textContent = t.key === data.taboo_key
        ? `${t.label} (автоматично → грейд SS)`
        : t.label;
      select.appendChild(opt);
    });
  } catch (err) {
    // Якщо перелік не завантажено — аналіз усе одно проходить,
    // але без класифікації виду прояву.
    console.warn("Не вдалося завантажити перелік видів прояву DIMs:", err);
  }
}

// ─────────────────────────────────────────────────────────────
//  STATE
// ─────────────────────────────────────────────────────────────
const state = {
  sources: [],   // [{label, tokens, type, warn}]
};

// Трекер «версії» останнього аналізу — для dismiss-per-fingerprint
// у CriticalAlertBanner. Оновлюється на початку renderResults().
let LAST_RESULTS_FP = "";

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
  featureType:  $("featureType"),
  charNSlider:  $("charNSlider"),
  charN:        $("charN"),
  charNRow:     $("charNRow"),
  minDocFreqSlider: $("minDocFreqSlider"),
  minDocFreq:   $("minDocFreq"),
  projectionMethod: $("projectionMethod"),
  manifestationSelect: $("manifestationSelect"),
  // Language alert
  languageAlert: $("languageAlert"),
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

function truncate(str, n = 90) {
  if (!str) return "";
  return str.length > n ? str.slice(0, n - 1) + "…" : str;
}

function sourcePrimaryText(source) {
  return escHtml(truncate(source.display_title || source.label, 90));
}

function sourceChipHtml(source, className = "source-chip") {
  const alias = source.alias || "";
  const domain = source.domain || source.label || "";
  const title = truncate(source.display_title || source.label, 80);
  const href = source.url || source.local_text_url || "";
  const safeHref = escHtml(href);
  const isSafeHref = href && !/^\s*javascript:/i.test(href);
  const tag = isSafeHref ? "a" : "span";
  const hrefAttr = isSafeHref
    ? ` href="${safeHref}" target="_blank" rel="noopener noreferrer"`
    : "";
  return `<${tag} class="${escHtml(className)}"${hrefAttr} title="${escHtml(source.display_title || "")}">
    ${alias ? `<span class="src-alias">${escHtml(alias)}</span>` : ""}
    <span class="src-domain">${escHtml(domain)}</span>
    <span class="src-title">${escHtml(title)}</span>
  </${tag}>`;
}

// Backward-compatible alias for existing call sites
function sourceLinkHtml(source, className = "source-link") {
  return sourceChipHtml(source, className === "source-link" ? "source-chip" : "source-chip flagged-chip");
}

function sourceContextHtml(source) {
  const parts = [];
  parts.push(`${source.tokens.toLocaleString("uk")} токенів`);
  parts.push(escHtml(source.type || "txt"));
  if (source.original_name) parts.push(escHtml(source.original_name));
  return parts.join(" &bull; ");
}

function scoreClass(score) {
  if (score >= 0.85) return "source-score-high";
  if (score >= 0.55) return "source-score-mid";
  return "source-score-low";
}

function sourceBreakdownHtml(rows) {
  if (!rows || !rows.length) return "";
  return `
    <div class="source-table">
      <div class="source-table-title">Розклад ${MATH.iSource}</div>
      ${rows.map(row => `
        <div class="source-table-row">
          <div class="source-table-row-main">
            ${sourceLinkHtml(row.source, "flagged-link")}
            <div class="source-table-row-meta">${escHtml(row.source.domain || row.source.label)}</div>
            ${row.components ? `<div class="source-table-row-meta">R_domain=${(row.components.domain || 0).toFixed(2)} · R_owner=${(row.components.owner || 0).toFixed(2)} · R_cred=${(row.components.cred || 0).toFixed(2)}</div>` : ""}
          </div>
          <div class="source-table-row-score ${scoreClass(row.score)}">${row.score.toFixed(3)}</div>
        </div>
      `).join("")}
    </div>`;
}

function sourceComponentHtml(components) {
  if (!components) return "";
  const rows = Object.entries(components);
  if (!rows.length) return "";
  return `
    <div class="source-table">
      <div class="source-table-title">Складові ${MATH.iSource}</div>
      ${rows.map(([label, item]) => `
        <div class="source-table-row">
          <div class="source-table-row-main">
            <div style="font-weight:600">${escHtml(label)}</div>
            <div class="source-table-row-meta">${escHtml(item.description || "")}</div>
          </div>
          <div class="source-table-row-score">
            <div>${Number(item.score || 0).toFixed(3)}</div>
            <div class="source-table-row-meta">w = ${Number(item.weight || 0).toFixed(2)}</div>
          </div>
        </div>
      `).join("")}
    </div>`;
}

// ─────────────────────────────────────────────────────────────
//  TABS
// ─────────────────────────────────────────────────────────────
function activateTab(btn) {
  const target = btn.dataset.tab;
  els.tabBtns.forEach(b => {
    const isActive = b === btn;
    b.classList.toggle("active", isActive);
    b.setAttribute("aria-selected", isActive ? "true" : "false");
    b.setAttribute("tabindex", isActive ? "0" : "-1");
  });
  els.tabPanels.forEach(p => {
    const isActive = p.id === `tab-${target}`;
    p.classList.toggle("active", isActive);
    if (isActive) p.removeAttribute("hidden"); else p.setAttribute("hidden", "");
  });
}

els.tabBtns.forEach((btn, idx, arr) => {
  btn.addEventListener("click", () => activateTab(btn));
  btn.addEventListener("keydown", e => {
    let nextIdx = null;
    if (e.key === "ArrowRight") nextIdx = (idx + 1) % arr.length;
    else if (e.key === "ArrowLeft") nextIdx = (idx - 1 + arr.length) % arr.length;
    else if (e.key === "Home") nextIdx = 0;
    else if (e.key === "End") nextIdx = arr.length - 1;
    if (nextIdx !== null) {
      e.preventDefault();
      activateTab(arr[nextIdx]);
      arr[nextIdx].focus();
    }
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
//  NEWS SEARCH
// ─────────────────────────────────────────────────────────────
const searchState = { results: [], selected: new Set() };

function updateImportButton() {
  const btn = $("btnImportSelected");
  const cnt = $("importSelectedCount");
  const n = searchState.selected.size;
  btn.disabled = n === 0;
  cnt.textContent = n ? `(${n})` : "";
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

function renderSearchResults(results) {
  const list = $("searchResultsList");
  const wrap = $("searchResults");
  const count = $("searchResultsCount");
  if (!results.length) {
    wrap.hidden = true;
    return;
  }
  wrap.hidden = false;
  searchState.selected.clear();
  count.textContent = `Знайдено ${results.length} джерел`;
  list.innerHTML = results.map((r, i) => {
    let date = "";
    if (r.published) {
      const d = new Date(r.published);
      if (!isNaN(d)) date = d.toLocaleDateString("uk-UA");
    }
    const safeUrl = /^https?:\/\//i.test(r.url) ? escapeHtml(r.url) : "#";
    const lang = /^[a-z]{2}$/i.test(r.lang || "") ? r.lang.toLowerCase() : "xx";
    return `
      <label class="search-result" data-idx="${i}">
        <input type="checkbox" data-idx="${i}" />
        <div class="search-result-body">
          <div class="search-result-title">${escapeHtml(r.title)}</div>
          <div class="search-result-meta">
            <span class="lang-tag lang-${lang}">${lang.toUpperCase()}</span>
            ${r.source ? `<span class="sr-source">${escapeHtml(r.source)}</span>` : ""}
            ${date ? `<span class="sr-date">${escapeHtml(date)}</span>` : ""}
            <a class="sr-link" href="${safeUrl}" target="_blank" rel="noopener"
               onclick="event.stopPropagation()">відкрити ↗</a>
          </div>
        </div>
      </label>`;
  }).join("");

  list.querySelectorAll('input[type="checkbox"]').forEach(cb => {
    cb.addEventListener("change", e => {
      const idx = Number(e.target.dataset.idx);
      if (e.target.checked) searchState.selected.add(idx);
      else searchState.selected.delete(idx);
      updateImportButton();
    });
  });
  updateImportButton();
}

$("btnSearchNews").addEventListener("click", async () => {
  const query = $("searchQuery").value.trim();
  if (!query) { showToast("Введіть пошуковий запит", "error"); return; }
  const langs = Array.from(document.querySelectorAll(".search-lang-row input:checked"))
    .map(i => i.value);
  if (!langs.length) { showToast("Оберіть хоча б одну мову", "error"); return; }

  const btn = $("btnSearchNews");
  const status = $("searchStatus");
  btn.disabled = true;
  status.textContent = "Пошук…";
  searchState.selected.clear();

  try {
    const data = await api("/api/search-news", "POST", { query, languages: langs, limit: 15 });
    if (!data.ok) { showToast(data.error, "error"); status.textContent = ""; return; }
    searchState.results = data.results || [];
    status.textContent = searchState.results.length
      ? ""
      : "За цим запитом нічого не знайдено.";
    renderSearchResults(searchState.results);
  } catch (e) {
    showToast("Помилка пошуку: " + e.message, "error");
    status.textContent = "";
  } finally {
    btn.disabled = false;
  }
});

$("searchQuery").addEventListener("keydown", e => {
  if (e.key === "Enter") $("btnSearchNews").click();
});

$("btnSelectAllResults").addEventListener("click", () => {
  const boxes = [...document.querySelectorAll("#searchResultsList input[type=checkbox]")];
  const allChecked = boxes.length > 0 && boxes.every(cb => cb.checked);
  boxes.forEach(cb => {
    cb.checked = !allChecked;
    const idx = Number(cb.dataset.idx);
    if (!allChecked) searchState.selected.add(idx);
    else searchState.selected.delete(idx);
  });
  updateImportButton();
});

function markResultStatus(idx, state, message) {
  const row = document.querySelector(`.search-result[data-idx="${idx}"]`);
  if (!row) return;
  row.classList.remove("is-ok", "is-err", "is-loading");
  row.classList.add("is-" + state);
  let badge = row.querySelector(".sr-status");
  if (!badge) {
    badge = document.createElement("div");
    badge.className = "sr-status";
    row.querySelector(".search-result-body").appendChild(badge);
  }
  badge.textContent = message;
}

$("btnImportSelected").addEventListener("click", async () => {
  const picks = [...searchState.selected].map(i => ({ idx: i, r: searchState.results[i] }))
    .filter(x => x.r);
  if (!picks.length) return;

  const btn = $("btnImportSelected");
  const status = $("searchStatus");
  btn.disabled = true;
  let imported = 0, failed = 0;

  for (let i = 0; i < picks.length; i++) {
    const { idx, r } = picks[i];
    markResultStatus(idx, "loading", "завантаження…");
    status.textContent = `Імпорт ${i + 1}/${picks.length}: ${r.title.slice(0, 60)}…`;
    try {
      const data = await api("/api/add-url", "POST", { url: r.url, label: "" });
      if (data.ok) {
        addSource(data.source);
        imported++;
        markResultStatus(idx, "ok", "✓ додано");
      } else {
        failed++;
        markResultStatus(idx, "err", "✗ " + (data.error || "помилка").slice(0, 120));
      }
    } catch (e) {
      failed++;
      markResultStatus(idx, "err", "✗ " + e.message.slice(0, 120));
    }
  }
  status.textContent = `Готово: імпортовано ${imported}${failed ? `, з помилкою ${failed}` : ""}. Наведіть курсор на позначки ✗, щоб побачити причину.`;
  showToast(`Імпортовано ${imported} джерел${failed ? ` (помилок: ${failed})` : ""}`,
            failed ? "warn" : "success");
  searchState.selected.clear();
  updateImportButton();
});

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
syncInputs(els.charNSlider, els.charN);
syncInputs(els.minDocFreqSlider, els.minDocFreq);

// Show/hide char-n row based on feature_type
function updateFeatureTypeUI() {
  const isChar = els.featureType.value === "char";
  els.charNRow.style.display = isChar ? "flex" : "none";
}
els.featureType.addEventListener("change", updateFeatureTypeUI);
updateFeatureTypeUI();

// ─────────────────────────────────────────────────────────────
//  ANALYZE
// ─────────────────────────────────────────────────────────────
els.btnAnalyze.addEventListener("click", async () => {
  const mfw       = parseInt(els.mfwInput.value) || 100;
  const threshold = parseFloat(els.thrInput.value) || 0.8;
  const feature_type = els.featureType.value || "word";
  const char_n = parseInt(els.charN.value) || 3;
  const min_doc_freq = parseInt(els.minDocFreq.value) || 2;
  const projection_method = els.projectionMethod.value || "pca";
  const manifestation = (els.manifestationSelect && els.manifestationSelect.value) || "";

  els.btnAnalyze.disabled = true;
  els.btnAnalyzeIcon.textContent = "⏳";
  els.btnAnalyzeText.textContent = "Аналізую...";
  showOverlay("Запускаю стилометричний аналіз...");

  try {
    const data = await api("/api/analyze", "POST", {
      mfw, threshold, feature_type, char_n, min_doc_freq,
      projection_method, manifestation,
    });

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
function renderLanguageAlert(report) {
  if (!els.languageAlert) return;
  if (!report || !report.is_mixed) { els.languageAlert.innerHTML = ""; return; }
  const scripts = (report.scripts || []).join(", ");
  els.languageAlert.innerHTML = `
    <div class="alert alert-critical" role="alert">
      <strong>⚠ Змішаний мовний корпус.</strong>
      ${escHtml(report.warning || "")} Виявлені мови/письма: <strong>${escHtml(scripts)}</strong>.
      <br><span style="font-size:13px">Значення <span class="math-inline">&Delta;<sub>Burrows</sub></span>
      на змішаному корпусі відображають мовну різницю, а не стиль. Рекомендовано розділити корпус за мовою.</span>
    </div>`;
}

function renderResults(data) {
  renderLanguageAlert(data.language_report);

  // KPI cards
  const nFlagged = data.n_flagged;
  const dims = data.dims_assessment;

  // Fingerprint цього аналізу — щоб dismiss-state банера не «тягнувся» між запусками.
  LAST_RESULTS_FP = [
    data.n_sources, data.n_pairs, data.n_flagged,
    (dims && dims.r_dims) ? dims.r_dims.toFixed(4) : "",
  ].join("|");
  renderCriticalAlert(dims, data.flagged);

  // Sensitivity range (max across indicators) — for R_DIMS metric mini-bar
  let sensRange = 0, sensMin = dims.r_dims, sensMax = dims.r_dims;
  if (dims.sensitivity) {
    if (typeof dims.sensitivity.min === "number") sensMin = dims.sensitivity.min;
    if (typeof dims.sensitivity.max === "number") sensMax = dims.sensitivity.max;
    if (typeof dims.sensitivity.range === "number") sensRange = dims.sensitivity.range;
  }
  const hasSens = sensRange > 0;
  const barMin = Math.min(sensMin, 0);
  const barMax = Math.max(sensMax, 1);
  const pct = v => ((v - barMin) / (barMax - barMin || 1) * 100).toFixed(1);
  const ciBarHtml = hasSens ? `
      <div class="ci-bar" aria-label="Діапазон чутливості">
        <div class="ci-bar-fill" style="left:${pct(sensMin)}%; width:${(pct(sensMax) - pct(sensMin)).toFixed(1)}%"></div>
        <div class="ci-bar-marker" style="left:${pct(dims.r_dims)}%"></div>
      </div>
      <div class="metric-sub">±${sensRange.toFixed(3)} (чутливість до ваг)</div>` : "";

  const gradeBadgeLg = gradeBadgeHtml(dims.grade, { size: "lg", withLabel: false });
  const gradeBadgeMd = gradeBadgeHtml(dims.grade, { size: "md" });

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
      <div class="stat-value">${gradeBadgeLg}</div>
      <div class="stat-label">DIMS-грейд</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">${MATH.rDims}</div>
      <div class="metric-value">${dims.r_dims.toFixed(3)}</div>
      ${ciBarHtml}
    </div>
  `;

  // Flagged pairs
  const radarHtml = renderDimsRadarSvg(dims.indicators, dims.weights, { size: "md" });
  const dimsSummary = `
    <div class="dims-summary">
      <strong>${MATH.rDims}</strong> = ${dims.r_dims.toFixed(4)} &bull;
      ${MATH.iContent} = ${dims.indicators.I_content.toFixed(3)} &bull;
      ${MATH.iCoord} = ${dims.indicators.I_coord.toFixed(3)} &bull;
      ${MATH.iDynamics} = ${dims.indicators.I_dynamics.toFixed(3)} &bull;
      ${MATH.iImpact} = ${dims.indicators.I_impact.toFixed(3)} &bull;
      ${MATH.iSource} = ${dims.indicators.I_source.toFixed(3)} &bull;
      Грейд ${gradeBadgeMd}
    </div>
    <div class="dims-radar-row" style="display:grid;grid-template-columns:minmax(260px,1fr) minmax(0,1.4fr);gap:var(--s-4);align-items:start;margin-bottom:var(--s-3)">
      ${radarHtml}
      <div>
        ${sourceComponentHtml(dims.source_components)}
        ${sourceBreakdownHtml(data.source_breakdown)}
      </div>
    </div>`;

  if (data.flagged.length === 0) {
    els.flaggedQuick.innerHTML = `
      ${dimsSummary}
      <div class="no-flagged-banner" role="status">
        ✅ Підозрілих пар не виявлено
      </div>`;
  } else {
    els.flaggedQuick.innerHTML = `
      ${dimsSummary}
      <h3 style="font-size:14px;font-weight:700;margin-bottom:10px">
        Підозрілі пари (${MATH.delta} &lt; ${MATH.thetaDelta} = ${data.flagged[0]?.delta !== undefined ? parseFloat(els.thrInput.value) : "?"})
      </h3>
      ${data.flagged.map(f => {
        const ci = f.ci && (f.ci.lo !== undefined)
          ? ` &bull; 95% CI [${f.ci.lo.toFixed(3)}, ${f.ci.hi.toFixed(3)}]`
          : "";
        return `
        <div class="flagged-item ${escHtml(f.severity.css || "")}">
          <span class="flagged-icon" aria-hidden="true">${escHtml(f.severity.icon || "")}</span>
          <div class="flagged-info">
            <div class="flagged-names">${sourceLinkHtml(f.a_meta, "flagged-link")} ↔ ${sourceLinkHtml(f.b_meta, "flagged-link")}</div>
            <div class="flagged-delta">${MATH.delta} = ${f.delta.toFixed(4)}${ci} &bull; ${escHtml(f.severity.label || "")}</div>
            <div class="flagged-context">${sourceContextHtml(f.a_meta)}<br>${sourceContextHtml(f.b_meta)}</div>
          </div>
        </div>`;
      }).join("")}
    `;
  }

}

// ─────────────────────────────────────────────────────────────
//  INIT
// ─────────────────────────────────────────────────────────────
renderSources();
