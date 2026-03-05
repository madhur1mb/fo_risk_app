/**
 * RiskPulse — F&O Risk Intelligence Dashboard
 * =============================================
 * Single-page application logic: handles CSV upload, API calls,
 * chart rendering, and all dynamic UI updates.
 *
 * Dependencies: Chart.js (loaded via CDN in HTML)
 */

"use strict";

// ─── Chart instances (stored to allow destroy/redraw) ─────────────
const charts = {};

// ─── State ─────────────────────────────────────────────────────────
let currentReport       = null;
let currentPositions    = [];
let aiSummaryCache      = null; // cached AI summary markdown/HTML for current report
let aiSummaryCardCreated = false;

// ─── DOM refs ──────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);

// ─── Init ───────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  startClock();
  loadSamples();
  bindEvents();
  loadMarketTicker();
  setInterval(loadMarketTicker, 30000); // refresh ticker every 30s
});

// ─── Clock ──────────────────────────────────────────────────────────
function startClock() {
  const update = () => {
    const now = new Date();
    const ist = now.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false });
    $("navTime").textContent = `IST ${ist}`;
  };
  update();
  setInterval(update, 1000);
}

// ─── Market Ticker ───────────────────────────────────────────────────
async function loadMarketTicker() {
  try {
    const res  = await fetch("/api/market/overview");
    const data = await res.json();
    const market = data.market || [];

    const map = {};
    market.forEach((m) => { map[m.underlying] = m; });

    const set = (id, underlying) => {
      const el = $(id);
      const m  = map[underlying];
      if (el && m) {
        el.textContent = formatNumber(m.spot);
        el.className = "ticker-val";
      }
    };
    set("t-nifty", "NIFTY");
    set("t-bn",    "BANKNIFTY");
    set("t-fin",   "FINNIFTY");

    // VIX approximation from NIFTY ATM IV
    const niftyIV = map["NIFTY"]?.iv_pct || 14;
    $("t-vix").textContent = niftyIV.toFixed(2);
  } catch (_) { /* silent fail */ }
}

// ─── Event Bindings ─────────────────────────────────────────────────
function bindEvents() {
  // File upload
  $("csvFile").addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (file) uploadFile(file);
  });

  // Drag-and-drop
  const uploadZone = $("uploadZone");
  uploadZone.addEventListener("dragover",  (e) => { e.preventDefault(); uploadZone.style.outline = "2px dashed var(--green)"; });
  uploadZone.addEventListener("dragleave", ()  => { uploadZone.style.outline = ""; });
  uploadZone.addEventListener("drop",      (e) => {
    e.preventDefault();
    uploadZone.style.outline = "";
    const file = e.dataTransfer.files[0];
    if (file) uploadFile(file);
  });

  // Sample button
  $("sampleBtn").addEventListener("click", () => {
    $("sampleMenu").classList.toggle("open");
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".sample-dropdown")) $("sampleMenu").classList.remove("open");
  });

  // Dashboard buttons
  $("newUploadBtn").addEventListener("click", resetToDashboard);
  $("runStressBtn").addEventListener("click", () => runStress());
  $("stressBtn").addEventListener("click",    () => runStress());
  $("runCustomBtn").addEventListener("click", runCustomStress);

  // OI chart underlying selector
  $("oiUnderlying").addEventListener("change", () => {
    const u = $("oiUnderlying").value;
    if (u) loadOIChart(u);
  });

  // Smile chart underlying selector
  $("smileUnderlying").addEventListener("change", () => {
    const u = $("smileUnderlying").value;
    if (u && currentReport) loadSmileChart(u, currentReport.iv_intelligence[u]);
  });

  // AI Summary modal interactions
  const aiModal = $("aiModal");
  const aiClose = $("aiModalClose");
  const aiSkip  = $("aiModalSkipBtn");
  const aiGen   = $("aiModalGenerateBtn");
  const aiFloat = $("aiSummaryFloatingBtn");

  if (aiClose) {
    aiClose.addEventListener("click", () => hideAIModal());
  }
  if (aiSkip) {
    aiSkip.addEventListener("click", () => hideAIModal());
  }
  if (aiGen) {
    aiGen.addEventListener("click", () => {
      if (!currentReport) {
        showToast("Load a portfolio first", "error");
        return;
      }
      requestAISummary(currentReport);
    });
  }
  if (aiFloat) {
    aiFloat.addEventListener("click", () => {
      if (!currentReport) {
        showToast("Load a portfolio first", "error");
        return;
      }
      showAIPromptModal();
    });
  }

  // Close AI modal on overlay click
  if (aiModal) {
    aiModal.addEventListener("click", (e) => {
      if (e.target === aiModal) {
        hideAIModal();
      }
    });
  }

  // Escape key closes AI modal
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && aiModal && !aiModal.classList.contains("hidden")) {
      hideAIModal();
    }
  });
}

// ─── Sample Portfolios ───────────────────────────────────────────────
async function loadSamples() {
  try {
    const res  = await fetch("/api/portfolio/samples");
    const data = await res.json();
    const menu = $("sampleMenu");
    menu.innerHTML = "";
    (data.samples || []).forEach((s) => {
      const item = document.createElement("div");
      item.className = "sample-item";
      item.textContent = s.replace(".csv", "").replace(/_/g, " ");
      item.addEventListener("click", () => {
        $("sampleMenu").classList.remove("open");
        loadSamplePortfolio(s);
      });
      menu.appendChild(item);
    });
  } catch (_) {}
}

async function loadSamplePortfolio(name) {
  showLoading();
  try {
    const res  = await fetch(`/api/portfolio/sample/${name}`);
    const data = await res.json();
    if (data.error) { showToast(data.error, "error"); return; }
    renderDashboard(data, name.replace(".csv", "").replace(/_/g, " "));
  } catch (e) {
    showToast("Failed to load sample: " + e.message, "error");
  } finally {
    hideLoading();
  }
}

// ─── File Upload ─────────────────────────────────────────────────────
async function uploadFile(file) {
  if (!file.name.endsWith(".csv")) {
    showToast("Please upload a .csv file", "error"); return;
  }
  showLoading();
  const fd = new FormData();
  fd.append("file", file);
  try {
    const res  = await fetch("/api/portfolio/upload", { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok) { showToast(data.error || "Upload failed", "error"); return; }
    renderDashboard(data, file.name);
  } catch (e) {
    showToast("Error: " + e.message, "error");
  } finally {
    hideLoading();
  }
}

// ─── MAIN RENDER ─────────────────────────────────────────────────────
function renderDashboard(report, title = "Portfolio") {
  currentReport    = report;
  currentPositions = report.positions || [];
  aiSummaryCache   = null;
  aiSummaryCardCreated = false;

  // Switch views
  $("uploadZone").classList.add("hidden");
  $("dashboard").classList.remove("hidden");
  $("aiSummaryFloatingBtn")?.classList.remove("hidden");

  // Title & meta
  $("dashTitle").textContent = title;
  $("posCount").textContent  = `${report.position_count} positions`;
  const badgeWrap = $("underlyingBadges");
  badgeWrap.innerHTML = "";
  (report.underlyings || []).forEach((u) => {
    const b = document.createElement("span");
    b.className = "underlying-badge";
    b.textContent = u;
    badgeWrap.appendChild(b);
  });

  // Greeks
  renderGreeks(report.greeks);

  // Exposure & PnL
  renderExposure(report);

  // Fragility
  renderFragility(report.fragility);

  // Payoff diagram
  renderPayoffChart(report.payoff_diagram);

  // IV Intelligence
  renderIVGrid(report.iv_intelligence);

  // OI Chart — load for first underlying
  const underlyings = report.underlyings || [];
  populateSelect("oiUnderlying", underlyings);
  if (underlyings.length > 0) loadOIChart(underlyings[0]);

  // Smile chart
  populateSelect("smileUnderlying", underlyings);
  if (underlyings.length > 0) loadSmileChart(underlyings[0], report.iv_intelligence[underlyings[0]]);

  // Positions table
  renderPositionsTable(currentPositions);

  // Warnings
  if ((report.parse_warnings || []).length > 0) {
    showToast("⚠️ " + report.parse_warnings[0], "error");
  } else {
    showToast("Portfolio loaded successfully ✓", "success");
  }

  // Prompt for AI summary shortly after dashboard render
  setTimeout(() => {
    // Only show prompt if a report is still loaded and no cached summary yet
    if (currentReport && !aiSummaryCache) {
      showAIPromptModal();
    }
  }, 30000);
}

// ─── Greeks ──────────────────────────────────────────────────────────
function renderGreeks(g) {
  const setVal = (id, val, decimals = 2) => {
    const el = $(id);
    if (!el) return;
    const num = parseFloat(val) || 0;
    el.textContent = formatGreek(num, decimals);
    el.className = "metric-val " + (num > 0 ? "positive" : num < 0 ? "negative" : "neutral");
  };
  setVal("val-delta", g.net_delta, 4);
  setVal("val-gamma", g.net_gamma, 6);
  setVal("val-theta", g.net_theta, 0);
  setVal("val-vega",  g.net_vega,  0);
}

function renderExposure(report) {
  const mtm = report.total_mtm_pnl || 0;
  const mtmEl = $("val-mtm");
  mtmEl.textContent = formatINR(mtm);
  mtmEl.className   = "metric-val " + (mtm >= 0 ? "positive" : "negative");

  $("val-gross").textContent = formatINRCrore(report.exposure?.gross_inr || 0);
  $("val-net").textContent   = formatINRCrore(report.exposure?.net_inr   || 0);

  const frag = report.fragility || {};
  $("val-margin").textContent  = formatINRCrore(frag.margin_used || 0);
  $("val-margin-pct").textContent = `${(frag.margin_pct || 0).toFixed(1)}% of ₹20L capital`;

  const pct = Math.min(frag.margin_pct || 0, 100);
  const bar = $("marginBar");
  bar.style.width      = pct + "%";
  bar.style.background = pct > 80 ? "var(--red)" : pct > 60 ? "var(--amber)" : "var(--green)";
}

// ─── Fragility Gauge ─────────────────────────────────────────────────
function renderFragility(frag) {
  if (!frag) return;
  const score = frag.score || 0;
  const color = frag.color || "#22c55e";

  $("fragScore").textContent   = score.toFixed(0);
  $("fragScore").style.color   = color;
  $("fragState").textContent   = frag.state || "—";
  $("fragState").style.color   = color;

  // Draw semicircle gauge
  drawGauge("fragilityGauge", score, color);

  // Component bars
  const barsEl = $("fragBars");
  barsEl.innerHTML = "";
  const comp = frag.components || {};
  const labels = { gamma: "Gamma", vega: "Vega", margin: "Margin", theta: "Theta", correlation: "Corr" };
  Object.entries(comp).forEach(([key, c]) => {
    const row = document.createElement("div");
    row.className = "frag-bar-row";
    const barColor = c.score > 70 ? "var(--red)" : c.score > 40 ? "var(--amber)" : "var(--green)";
    row.innerHTML = `
      <div class="frag-bar-label">${labels[key] || key}</div>
      <div class="frag-bar-track">
        <div class="frag-bar-fill" style="width:${c.score}%;background:${barColor}"></div>
      </div>
      <div class="frag-bar-val">${c.score.toFixed(0)}</div>
    `;
    barsEl.appendChild(row);
  });
}

function drawGauge(canvasId, score, color) {
  const canvas = $(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);

  const cx = W / 2, cy = H - 10;
  const r  = Math.min(W, H * 2) / 2 - 8;

  // Background arc
  ctx.beginPath();
  ctx.arc(cx, cy, r, Math.PI, 0, false);
  ctx.lineWidth = 10;
  ctx.strokeStyle = "#1e2d40";
  ctx.stroke();

  // Value arc
  const angle = Math.PI + (score / 100) * Math.PI;
  ctx.beginPath();
  ctx.arc(cx, cy, r, Math.PI, angle, false);
  ctx.lineWidth  = 10;
  ctx.strokeStyle = color;
  ctx.lineCap    = "round";
  ctx.shadowColor = color;
  ctx.shadowBlur  = 8;
  ctx.stroke();
  ctx.shadowBlur  = 0;
}

// ─── Payoff Chart ─────────────────────────────────────────────────────
function renderPayoffChart(payoff) {
  if (!payoff || !payoff.x) return;
  const ctx = $("payoffChart")?.getContext("2d");
  if (!ctx) return;
  if (charts.payoff) charts.payoff.destroy();

  const zeroLine = payoff.y_expiry.map(() => 0);

  charts.payoff = new Chart(ctx, {
    type: "line",
    data: {
      labels: payoff.x,
      datasets: [
        {
          label: "At Expiry",
          data:  payoff.y_expiry,
          borderColor: "#00e676",
          backgroundColor: "rgba(0,230,118,0.07)",
          borderWidth: 2,
          pointRadius: 0,
          fill: false,
          tension: 0.2,
        },
        {
          label: "Current (BSM)",
          data:  payoff.y_current,
          borderColor: "#00e5ff",
          backgroundColor: "rgba(0,229,255,0.05)",
          borderWidth: 1.5,
          borderDash: [4, 3],
          pointRadius: 0,
          fill: false,
          tension: 0.2,
        },
        {
          label: "Zero",
          data:  zeroLine,
          borderColor: "rgba(255,255,255,0.12)",
          borderWidth: 1,
          pointRadius: 0,
          fill: false,
          tension: 0,
        },
      ],
    },
    options: chartDefaults({
      xLabel: "Spot Price",
      yLabel: "P&L (₹)",
      yTickFmt: (v) => formatINRShort(v),
    }),
  });
}

// ─── OI Chart ────────────────────────────────────────────────────────
async function loadOIChart(underlying) {
  try {
    const res   = await fetch(`/api/analytics/oi-chain/${underlying}`);
    const chain = await res.json();
    renderOIChart(chain);
  } catch (_) {}
}

function renderOIChart(chain) {
  const ctx = $("oiChart")?.getContext("2d");
  if (!ctx) return;
  if (charts.oi) charts.oi.destroy();

  // Show only middle 13 strikes
  const mid  = Math.floor(chain.strikes.length / 2);
  const half = 6;
  const sl   = (arr) => arr.slice(Math.max(0, mid - half), mid + half + 1);

  charts.oi = new Chart(ctx, {
    type: "bar",
    data: {
      labels: sl(chain.strikes).map((s) => s.toLocaleString("en-IN")),
      datasets: [
        {
          label: "Call OI",
          data:  sl(chain.call_oi).map((v) => v / 1000),
          backgroundColor: "rgba(0,229,255,0.7)",
          borderColor: "rgba(0,229,255,0.9)",
          borderWidth: 1,
        },
        {
          label: "Put OI",
          data:  sl(chain.put_oi).map((v) => v / 1000),
          backgroundColor: "rgba(255,171,0,0.7)",
          borderColor: "rgba(255,171,0,0.9)",
          borderWidth: 1,
        },
      ],
    },
    options: chartDefaults({ xLabel: "Strike", yLabel: "OI (K lots)" }),
  });
}

// ─── Vol Smile Chart ─────────────────────────────────────────────────
function loadSmileChart(underlying, ivReport) {
  if (!ivReport || !ivReport.smile) return;
  const smile = ivReport.smile;
  const ctx   = $("smileChart")?.getContext("2d");
  if (!ctx) return;
  if (charts.smile) charts.smile.destroy();

  charts.smile = new Chart(ctx, {
    type: "line",
    data: {
      labels: smile.strikes.map((s) => s.toLocaleString("en-IN")),
      datasets: [
        {
          label: "Call IV %",
          data:  smile.call_ivs,
          borderColor: "#00e5ff",
          backgroundColor: "rgba(0,229,255,0.05)",
          pointRadius: 3,
          pointBackgroundColor: "#00e5ff",
          borderWidth: 2,
          tension: 0.3,
          fill: false,
        },
        {
          label: "Put IV %",
          data:  smile.put_ivs,
          borderColor: "#ffab00",
          backgroundColor: "rgba(255,171,0,0.05)",
          pointRadius: 3,
          pointBackgroundColor: "#ffab00",
          borderWidth: 2,
          tension: 0.3,
          fill: false,
        },
      ],
    },
    options: chartDefaults({ xLabel: "Strike", yLabel: "IV %" }),
  });
}

// ─── IV Grid ─────────────────────────────────────────────────────────
function renderIVGrid(ivIntel) {
  const grid = $("ivGrid");
  grid.innerHTML = "";
  Object.entries(ivIntel || {}).forEach(([underlying, report]) => {
    const ivRankColor = report.iv_rank > 70 ? "var(--red)" : report.iv_rank > 40 ? "var(--amber)" : "var(--green)";
    const spread      = report.iv_hv_spread;
    const spreadColor = spread > 0 ? "var(--amber)" : "var(--green)";

    const card = document.createElement("div");
    card.className = "iv-card";
    card.innerHTML = `
      <div class="iv-card-header">
        <div class="iv-card-name">${underlying}</div>
        <div class="iv-card-iv" style="color:${ivRankColor}">${report.current_iv}%</div>
      </div>
      <div class="iv-metrics">
        <div class="iv-metric">
          <div class="iv-metric-label">IV Rank</div>
          <div class="iv-metric-val" style="color:${ivRankColor}">${report.iv_rank}</div>
        </div>
        <div class="iv-metric">
          <div class="iv-metric-label">IV Percentile</div>
          <div class="iv-metric-val">${report.iv_percentile}</div>
        </div>
        <div class="iv-metric">
          <div class="iv-metric-label">HV 20d</div>
          <div class="iv-metric-val">${report.hv_20d}%</div>
        </div>
        <div class="iv-metric">
          <div class="iv-metric-label">IV-HV Spread</div>
          <div class="iv-metric-val" style="color:${spreadColor}">${spread > 0 ? "+" : ""}${spread}%</div>
        </div>
      </div>
      <div class="iv-rank-bar">
        <div class="iv-rank-fill" style="width:${report.iv_rank}%"></div>
      </div>
    `;
    grid.appendChild(card);
  });
}

// ─── Stress Test ─────────────────────────────────────────────────────
async function runStress() {
  if (!currentPositions.length) { showToast("Load a portfolio first", "error"); return; }
  showLoading();
  try {
    const body = JSON.stringify({ positions: rawPositionsFromReport() });
    const res  = await fetch("/api/stress/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
    const data = await res.json();
    renderStressGrid(data.scenarios || []);
    showToast("Stress scenarios computed ✓", "success");
  } catch (e) {
    showToast("Stress test failed: " + e.message, "error");
  } finally {
    hideLoading();
  }
}

async function runCustomStress() {
  if (!currentPositions.length) { showToast("Load a portfolio first", "error"); return; }
  const spot = parseFloat($("cs-spot").value) || 0;
  const vol  = parseFloat($("cs-vol").value)  || 0;
  const days = parseFloat($("cs-days").value) || 0;

  showLoading();
  try {
    const body = JSON.stringify({
      positions: rawPositionsFromReport(),
      custom:    { spot_shock_pct: spot / 100, vol_shock_abs: vol / 100, time_shock_days: days },
    });
    const res  = await fetch("/api/stress/run", {
      method: "POST", headers: { "Content-Type": "application/json" }, body,
    });
    const data = await res.json();
    if (data.custom_result) {
      const r   = data.custom_result;
      const col = r.total_pnl >= 0 ? "var(--green)" : "var(--red)";
      const resultEl = $("csfResult");
      resultEl.classList.remove("hidden");
      resultEl.innerHTML = `
        Custom Scenario P&L:
        <strong style="color:${col};font-size:1.1rem">
          ${r.total_pnl >= 0 ? "+" : ""}${formatINR(r.total_pnl)}
        </strong>
        <span style="color:var(--text-muted);font-size:0.65rem;margin-left:0.5rem">
          (Spot ${spot > 0 ? "+" : ""}${spot}% | IV ${vol > 0 ? "+" : ""}${vol}pts | ${days}d decay)
        </span>`;
    }
  } catch (e) {
    showToast("Custom stress failed: " + e.message, "error");
  } finally {
    hideLoading();
  }
}

function renderStressGrid(scenarios) {
  const grid = $("stressGrid");
  grid.innerHTML = "";
  scenarios.forEach((s) => {
    const pnl = s.total_pnl;
    const cls = pnl > 0 ? "pos" : pnl < 0 ? "neg" : "zero";
    const card = document.createElement("div");
    card.className = "stress-card";
    card.innerHTML = `
      <div class="stress-name">${s.scenario}</div>
      <div class="stress-pnl ${cls}">
        ${pnl >= 0 ? "+" : ""}${formatINR(pnl)}
      </div>`;
    grid.appendChild(card);
  });
}

// ─── Positions Table ─────────────────────────────────────────────────
function renderPositionsTable(positions) {
  const tbody = $("posTableBody");
  tbody.innerHTML = "";
  positions.forEach((p) => {
    const a    = p.analytics || {};
    const pnl  = p.mtm_pnl || 0;
    const tr   = document.createElement("tr");
    tr.innerHTML = `
      <td>${p.underlying}</td>
      <td class="type-${p.type}">${p.type}</td>
      <td>${p.strike?.toLocaleString("en-IN")}</td>
      <td>${p.expiry}</td>
      <td class="${p.qty > 0 ? "qty-long" : "qty-short"}">${p.qty > 0 ? "+" : ""}${p.qty}</td>
      <td>${formatNum(p.entry_price)}</td>
      <td>${formatNum(p.fair_value)}</td>
      <td class="${pnl >= 0 ? "pnl-pos" : "pnl-neg"}">${pnl >= 0 ? "+" : ""}${formatINR(pnl)}</td>
      <td>${formatNum(p.delta_per_unit, 3)}</td>
      <td>${formatNum(p.gamma_per_unit, 5)}</td>
      <td>${formatNum(p.theta / (p.qty * (p.lot_size || 50)), 2)}</td>
      <td>${formatNum(p.vega  / (p.qty * (p.lot_size || 50)), 2)}</td>
      <td>${p.iv ? (p.iv * 100).toFixed(1) + "%" : "—"}</td>
      <td>${a.pop ? a.pop + "%" : "—"}</td>
      <td>${a.breakeven ? a.breakeven.toLocaleString("en-IN") : "—"}</td>
    `;
    tbody.appendChild(tr);
  });
}

// ─── Helpers ─────────────────────────────────────────────────────────
function rawPositionsFromReport() {
  return (currentReport?.positions || []).map((p) => ({
    underlying:  p.underlying,
    type:        p.type,
    strike:      p.strike,
    expiry:      p.expiry,
    qty:         p.qty,
    entry_price: p.entry_price,
    iv:          p.iv,
    tte:         p.tte,
  }));
}

function populateSelect(selectId, options) {
  const sel = $(selectId);
  if (!sel) return;
  sel.innerHTML = "";
  options.forEach((o) => {
    const opt = document.createElement("option");
    opt.value = o; opt.textContent = o;
    sel.appendChild(opt);
  });
}

function formatINR(val) {
  const v = parseFloat(val) || 0;
  return "₹" + Math.abs(v).toLocaleString("en-IN", { maximumFractionDigits: 0 });
}
function formatINRShort(val) {
  const v = parseFloat(val) || 0;
  if (Math.abs(v) >= 100000) return "₹" + (v / 100000).toFixed(1) + "L";
  return "₹" + v.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}
function formatINRCrore(val) {
  const v = parseFloat(val) || 0;
  if (Math.abs(v) >= 10000000) return "₹" + (v / 10000000).toFixed(2) + "Cr";
  if (Math.abs(v) >= 100000)   return "₹" + (v / 100000).toFixed(2) + "L";
  return "₹" + v.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}
function formatNumber(val) {
  return parseFloat(val)?.toLocaleString("en-IN", { maximumFractionDigits: 2 }) || "—";
}
function formatNum(val, dec = 2) {
  return parseFloat(val)?.toFixed(dec) || "—";
}
function formatGreek(val, dec = 4) {
  return parseFloat(val)?.toFixed(dec) || "—";
}

function showLoading() { $("loadingOverlay").classList.remove("hidden"); }
function hideLoading()  { $("loadingOverlay").classList.add("hidden"); }

function showToast(msg, type = "info") {
  const t = $("toast");
  t.textContent  = msg;
  t.className    = `toast ${type}`;
  t.classList.remove("hidden");
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.add("hidden"), 4000);
}

function resetToDashboard() {
  $("uploadZone").classList.remove("hidden");
  $("dashboard").classList.add("hidden");
  currentReport    = null;
  currentPositions = [];
  $("csvFile").value = "";
  aiSummaryCache   = null;
  aiSummaryCardCreated = false;
  $("aiSummaryFloatingBtn")?.classList.add("hidden");
}

// ─── Chart Defaults (dark terminal style) ───────────────────────────
function chartDefaults({ xLabel = "", yLabel = "", yTickFmt = null } = {}) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: {
        display: true,
        labels: {
          color: "#7a8fa6",
          font: { family: "'JetBrains Mono', monospace", size: 10 },
          boxWidth: 10,
        },
      },
      tooltip: {
        backgroundColor: "#111620",
        borderColor: "#1e2d40",
        borderWidth: 1,
        titleColor: "#e8edf5",
        bodyColor: "#7a8fa6",
        titleFont: { family: "'JetBrains Mono', monospace", size: 11 },
        bodyFont:  { family: "'JetBrains Mono', monospace", size: 10 },
      },
    },
    scales: {
      x: {
        ticks: {
          color: "#3d5166",
          font: { family: "'JetBrains Mono', monospace", size: 9 },
          maxRotation: 45,
          maxTicksLimit: 8,
        },
        grid:  { color: "rgba(30,45,64,0.5)" },
        title: { display: !!xLabel, text: xLabel, color: "#3d5166", font: { size: 9 } },
      },
      y: {
        ticks: {
          color: "#3d5166",
          font: { family: "'JetBrains Mono', monospace", size: 9 },
          callback: yTickFmt || null,
        },
        grid:  { color: "rgba(30,45,64,0.5)" },
        title: { display: !!yLabel, text: yLabel, color: "#3d5166", font: { size: 9 } },
      },
    },
  };
}

// ─── AI Risk Summary (GPT-4o) ────────────────────────────────────────
function showAIPromptModal() {
  const overlay = $("aiModal");
  if (!overlay) return;
  overlay.classList.remove("hidden");
  overlay.setAttribute("aria-hidden", "false");

  // Reset view state
  $("aiModalInitial")?.classList.remove("hidden");
  $("aiModalLoading")?.classList.add("hidden");
  $("aiModalError")?.classList.add("hidden");
  const resultWrap = overlay.querySelector(".ai-modal-result");
  if (resultWrap) resultWrap.classList.toggle("hidden", !aiSummaryCache);

  if (aiSummaryCache) {
    // If we already have a summary, just render it directly
    const parsed = parseMarkdown(aiSummaryCache);
    const target = $("aiModalSummary");
    if (target) {
      target.innerHTML = parsed;
    }
  }
}

function hideAIModal() {
  const overlay = $("aiModal");
  if (!overlay) return;
  overlay.classList.add("hidden");
  overlay.setAttribute("aria-hidden", "true");

  // If we have a generated summary but haven't yet created the dashboard card,
  // persist the summary as a new card on the dashboard.
  if (aiSummaryCache && !aiSummaryCardCreated) {
    createAISummaryCard(aiSummaryCache);
    aiSummaryCardCreated = true;
  }
}

async function requestAISummary(report) {
  const initial = $("aiModalInitial");
  const loading = $("aiModalLoading");
  const errorEl = $("aiModalError");
  const resultWrap = document.querySelector(".ai-modal-result");
  const summaryEl = $("aiModalSummary");

  if (initial) initial.classList.add("hidden");
  if (errorEl) {
    errorEl.classList.add("hidden");
    errorEl.textContent = "";
  }
  if (resultWrap) resultWrap.classList.add("hidden");
  if (loading) loading.classList.remove("hidden");

  try {
    const res = await fetch("/api/ai/summary", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(report),
    });

    const data = await res.json();
    if (!res.ok || !data.summary) {
      const msg =
        data.error ||
        "Could not generate summary. Check your OPENAI_API_KEY in .env and try again.";
      if (errorEl) {
        errorEl.textContent = msg;
        errorEl.classList.remove("hidden");
      }
      return;
    }

    aiSummaryCache = data.summary;
    if (summaryEl && resultWrap) {
      const html = parseMarkdown(data.summary);
      summaryEl.innerHTML = html;
      resultWrap.classList.remove("hidden");
    }
  } catch (e) {
    const msg =
      "Could not generate summary. Check your OPENAI_API_KEY in .env and try again.";
    if (errorEl) {
      errorEl.textContent = msg;
      errorEl.classList.remove("hidden");
    }
  } finally {
    if (loading) loading.classList.add("hidden");
  }
}

function parseMarkdown(text) {
  if (!text) return "";

  const lines = text.split(/\r?\n/);
  const htmlParts = [];
  let inList = false;

  const flushList = () => {
    if (inList) {
      htmlParts.push("</ul>");
      inList = false;
    }
  };

  for (let raw of lines) {
    const line = raw.trimEnd();
    if (!line) {
      flushList();
      continue;
    }

    // Headings: ## Title -> <h4>
    if (line.startsWith("## ")) {
      flushList();
      const content = escapeHtml(line.replace(/^##\s+/, ""));
      htmlParts.push(`<h4>${content}</h4>`);
      continue;
    }

    // List items: - item -> <li>
    if (line.startsWith("- ")) {
      if (!inList) {
        htmlParts.push("<ul>");
        inList = true;
      }
      const item = line.replace(/^-+\s*/, "");
      htmlParts.push(`<li>${inlineMarkdown(item)}</li>`);
      continue;
    }

    // Paragraph
    flushList();
    htmlParts.push(`<p>${inlineMarkdown(line)}</p>`);
  }

  flushList();
  return htmlParts.join("");
}

function inlineMarkdown(text) {
  // basic **bold** handling
  const escaped = escapeHtml(text);
  return escaped.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

function escapeHtml(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function typewriterRender(el, html) {
  const chars = Array.from(html);
  let idx = 0;
  const step = () => {
    if (idx >= chars.length) return;
    el.innerHTML += chars[idx];
    idx += 1;
    if (idx < chars.length) {
      window.requestAnimationFrame(step);
    }
  };
  step();
}

function createAISummaryCard(summary) {
  const dashboard = $("dashboard");
  if (!dashboard) return;

  const card = document.createElement("div");
  card.className = "dashboard-card ai-summary-card";

  const header = document.createElement("div");
  header.className = "card-header";
  header.textContent = "⚡ AI Risk Summary";

  const body = document.createElement("div");
  body.className = "card-body";
  body.innerHTML = parseMarkdown(summary);

  card.appendChild(header);
  card.appendChild(body);

  dashboard.appendChild(card);
}
