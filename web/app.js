const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

let settings = null;
let statusSnapshot = null;
let lastQr = "";
let lastScanAlertKey = "";
let scannerScans = [];
let scannerConfig = { com_port: "COM3", baudrate: 115200 };
let datasetsTransform = { zoom: 1.0, rotate: 0, panX: 0, panY: 0 };
let datasetsTransformBase = { width: 0, height: 0 };
const ZOOM_STEP = 0.1;
const ZOOM_MIN = 1.0;
const ZOOM_MAX = 4.0;
const PAN_STEP = 20;
const EXPOSURE_DEFAULT = 10000;
const MAX_PRODUCTS = Number.POSITIVE_INFINITY;
const MAX_PERSONNEL = Number.POSITIVE_INFINITY;
const DEFAULT_QR_RULE = "^[A-Za-z0-9_.-]{6,80}$";
const LAYOUT_STORAGE_KEY = "hmi_production_layout_v6";
const PRODUCT_GRID_WIDTHS_KEY = "hmi_product_grid_widths_v1";
const CARD_MIN_WIDTH = 200;
const CARD_MIN_HEIGHT = 120;
const CARD_GAP = 8;
const PRODUCT_GRID_DEFAULTS = { model: 100, rule: 100 };
const CAMERA_FEED_INTERVAL_MS = 250;
const STATUS_POLL_INTERVAL_MS = 500;
const CAMERA_POLL_LEASE_KEY = "hmi_camera_poll_lease_v1";
const CAMERA_POLL_LEASE_MS = CAMERA_FEED_INTERVAL_MS * 3;
const CAMERA_POLL_TAB_ID = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
let productGridResizeState = null;

const DEFAULT_LAYOUT = {
  "operator-panel":    { x: 0.00, y: 0.00, w: 0.18, h: 0.12 },
  "plc-panel":         { x: 0.00, y: 0.13, w: 0.18, h: 0.57 },
  "camera-panel":      { x: 0.19, y: 0.00, w: 0.57, h: 0.70 },
  "tightening-panel":  { x: 0.77, y: 0.00, w: 0.23, h: 0.26 },
  "scan-panel":        { x: 0.77, y: 0.27, w: 0.23, h: 0.43 },
  "recent-panel":      { x: 0.00, y: 0.71, w: 1.00, h: 0.29 },
};

function clampProductGridWidth(column, value) {
  const limits = column === "model"
    ? { min: 60, max: 200 }
    : { min: 60, max: 320 };
  return Math.max(limits.min, Math.min(limits.max, Math.round(value)));
}

function loadProductGridWidths() {
  try {
    const saved = JSON.parse(localStorage.getItem(PRODUCT_GRID_WIDTHS_KEY) || "{}");
    return {
      model: clampProductGridWidth("model", Number(saved.model) || PRODUCT_GRID_DEFAULTS.model),
      rule: clampProductGridWidth("rule", Number(saved.rule) || PRODUCT_GRID_DEFAULTS.rule),
    };
  } catch (error) {
    return { ...PRODUCT_GRID_DEFAULTS };
  }
}

function applyProductGridWidths(widths = loadProductGridWidths()) {
  const safe = {
    model: clampProductGridWidth("model", widths.model),
    rule: clampProductGridWidth("rule", widths.rule),
  };
  document.documentElement.style.setProperty("--product-model-col", `${safe.model}px`);
  document.documentElement.style.setProperty("--product-rule-col", `${safe.rule}px`);
  document.documentElement.style.setProperty("--product-model-col-sm", `${Math.max(48, safe.model - 6)}px`);
  document.documentElement.style.setProperty("--product-rule-col-sm", `${Math.max(84, safe.rule - 12)}px`);
  return safe;
}

function syncProductWidthControls(widths = loadProductGridWidths()) {
  const safe = applyProductGridWidths(widths);
  for (const column of ["model", "rule"]) {
    const input = document.querySelector(`[data-width-col="${column}"]`);
    const output = document.querySelector(`[data-width-output="${column}"]`);
    if (input) input.value = safe[column];
    if (output) output.textContent = `${safe[column]}px`;
  }
  return safe;
}

function saveProductGridWidths(widths) {
  const safe = applyProductGridWidths(widths);
  try {
    localStorage.setItem(PRODUCT_GRID_WIDTHS_KEY, JSON.stringify(safe));
  } catch (error) {
    // Ignore storage failures and keep the current session width.
  }
  syncProductWidthControls(safe);
}

function stopProductGridResize() {
  if (!productGridResizeState) return;
  saveProductGridWidths(productGridResizeState.widths);
  productGridResizeState = null;
  document.body.classList.remove("is-resizing-columns");
  window.removeEventListener("pointermove", onProductGridResizeMove);
  window.removeEventListener("pointerup", stopProductGridResize);
  window.removeEventListener("pointercancel", stopProductGridResize);
}

function onProductGridResizeMove(event) {
  if (!productGridResizeState) return;
  const delta = event.clientX - productGridResizeState.startX;
  const nextWidths = { ...productGridResizeState.widths };
  nextWidths[productGridResizeState.column] = clampProductGridWidth(
    productGridResizeState.column,
    productGridResizeState.startWidth + delta,
  );
  productGridResizeState.widths = applyProductGridWidths(nextWidths);
}

function bindProductGridResizers() {
  const table = $("#productRows");
  if (!table) return;
  table.querySelectorAll("[data-resize-col]").forEach((handle) => {
    handle.addEventListener("pointerdown", (event) => {
      if (event.pointerType === "mouse" && event.button !== 0) return;
      event.preventDefault();
      event.stopPropagation();
      const column = handle.dataset.resizeCol;
      const widths = loadProductGridWidths();
      productGridResizeState = {
        column,
        startX: event.clientX,
        startWidth: widths[column],
        widths,
      };
      document.body.classList.add("is-resizing-columns");
      window.addEventListener("pointermove", onProductGridResizeMove);
      window.addEventListener("pointerup", stopProductGridResize);
      window.addEventListener("pointercancel", stopProductGridResize);
    });
  });
}

function bindProductWidthControls() {
  const tools = $("#productWidthTools");
  if (!tools) return;
  tools.querySelectorAll("[data-width-col]").forEach((input) => {
    input.addEventListener("input", () => {
      const widths = loadProductGridWidths();
      widths[input.dataset.widthCol] = Number(input.value);
      saveProductGridWidths(widths);
    });
  });
  const reset = tools.querySelector("[data-reset-product-widths]");
  if (reset) {
    reset.addEventListener("click", () => {
      saveProductGridWidths(PRODUCT_GRID_DEFAULTS);
      syncProductWidthControls(PRODUCT_GRID_DEFAULTS);
    });
  }
}

class LayoutManager {
  constructor(container) {
    this.container = container;
    this.cards = new Map();
    this.layout = {};
    this.dragState = null;
    this.resizeState = null;
    this.summaryEl = null;
    this._boundPointerMove = this._onPointerMove.bind(this);
    this._boundPointerUp = this._onPointerUp.bind(this);
  }

  init() {
    this.summaryEl = this.container.querySelector(".production-summary");
    const panels = this.container.querySelectorAll(".panel");
    const panelClasses = [
      "operator-panel", "camera-panel", "plc-panel",
      "tightening-panel", "scan-panel", "recent-panel",
    ];
    for (const panel of panels) {
      for (const cls of panelClasses) {
        if (panel.classList.contains(cls)) {
          this.cards.set(cls, panel);
          break;
        }
      }
    }
    this.layout = this._loadLayout();
    this.applyLayout();
    this._bindDragHandlers();
    this._bindResizeHandlers();
    this._bindResizeObserver();
    if (this.summaryEl) {
      const ro = new ResizeObserver(() => this.applyLayout());
      ro.observe(this.summaryEl);
    }
  }

  _loadLayout() {
    try {
      const saved = localStorage.getItem(LAYOUT_STORAGE_KEY);
      if (saved) {
        const data = JSON.parse(saved);
        const allPresent = [...this.cards.keys()].every((id) => data[id]);
        if (allPresent) return data;
      }
    } catch (e) { /* ignore */ }
    return JSON.parse(JSON.stringify(DEFAULT_LAYOUT));
  }

  _saveLayout() {
    try {
      localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify(this.layout));
    } catch (e) { /* ignore */ }
  }

  _getCanvas() {
    const containerRect = this.container.getBoundingClientRect();
    const summaryHeight = this.summaryEl
      ? this.summaryEl.getBoundingClientRect().height +
        parseFloat(getComputedStyle(this.summaryEl).marginBottom || 0)
      : 0;
    return {
      x: 0,
      y: summaryHeight,
      w: containerRect.width,
      h: containerRect.height - summaryHeight,
    };
  }

  applyLayout() {
    const canvas = this._getCanvas();
    if (canvas.w <= 0 || canvas.h <= 0) return;
    for (const [cardId, panel] of this.cards) {
      const pos = this.layout[cardId];
      if (!pos) continue;
      const gapW = (1 - pos.w) > 0.001 ? CARD_GAP : 0;
      const gapH = (1 - pos.h) > 0.001 ? CARD_GAP : 0;
      panel.style.left   = `${canvas.x + pos.x * canvas.w}px`;
      panel.style.top    = `${canvas.y + pos.y * canvas.h}px`;
      panel.style.width  = `${pos.w * canvas.w - gapW}px`;
      panel.style.height = `${pos.h * canvas.h - gapH}px`;
    }
  }

  _bindDragHandlers() {
    for (const [cardId, panel] of this.cards) {
      const handle = panel.querySelector("[data-drag-handle]");
      if (!handle) continue;
      handle.addEventListener("pointerdown", (e) => {
        if (e.pointerType === "mouse" && e.button !== 0) return;
        e.preventDefault();
        e.stopPropagation();
        handle.setPointerCapture(e.pointerId);
        const containerRect = this.container.getBoundingClientRect();
        const panelRect = panel.getBoundingClientRect();
        this.dragState = {
          cardId,
          panel,
          startX: e.clientX,
          startY: e.clientY,
          origLeft: panelRect.left - containerRect.left,
          origTop: panelRect.top - containerRect.top,
          pointerId: e.pointerId,
        };
        panel.style.transition = "none";
        panel.style.zIndex = "100";
        window.addEventListener("pointermove", this._boundPointerMove);
        window.addEventListener("pointerup", this._boundPointerUp);
        window.addEventListener("pointercancel", this._boundPointerUp);
      });
      handle.addEventListener("selectstart", (e) => e.preventDefault());
    }
  }

  _bindResizeHandlers() {
    for (const [cardId, panel] of this.cards) {
      const grip = panel.querySelector(".resize-grip");
      if (!grip) continue;
      grip.addEventListener("pointerdown", (e) => {
        if (e.pointerType === "mouse" && e.button !== 0) return;
        e.preventDefault();
        e.stopPropagation();
        grip.setPointerCapture(e.pointerId);
        const containerRect = this.container.getBoundingClientRect();
        const panelRect = panel.getBoundingClientRect();
        this.resizeState = {
          cardId,
          panel,
          startX: e.clientX,
          startY: e.clientY,
          origLeft: panelRect.left - containerRect.left,
          origTop: panelRect.top - containerRect.top,
          origWidth: panelRect.width,
          origHeight: panelRect.height,
          pointerId: e.pointerId,
        };
        panel.style.transition = "none";
        window.addEventListener("pointermove", this._boundPointerMove);
        window.addEventListener("pointerup", this._boundPointerUp);
        window.addEventListener("pointercancel", this._boundPointerUp);
      });
    }
  }

  _onPointerMove(e) {
    if (this.dragState && e.pointerId === this.dragState.pointerId) {
      e.preventDefault();
      const ds = this.dragState;
      const dx = e.clientX - ds.startX;
      const dy = e.clientY - ds.startY;
      const containerRect = this.container.getBoundingClientRect();
      const panelW = ds.panel.getBoundingClientRect().width;
      const panelH = ds.panel.getBoundingClientRect().height;
      let newLeft = ds.origLeft + dx;
      let newTop  = ds.origTop + dy;
      newLeft = Math.max(0, Math.min(newLeft, containerRect.width - Math.max(panelW, CARD_MIN_WIDTH) * 0.3));
      newTop  = Math.max(0, Math.min(newTop, containerRect.height - Math.max(panelH, CARD_MIN_HEIGHT) * 0.3));
      ds.panel.style.left = `${newLeft}px`;
      ds.panel.style.top  = `${newTop}px`;
    } else if (this.resizeState && e.pointerId === this.resizeState.pointerId) {
      e.preventDefault();
      const rs = this.resizeState;
      const dx = e.clientX - rs.startX;
      const dy = e.clientY - rs.startY;
      const containerRect = this.container.getBoundingClientRect();
      let newW = rs.origWidth + dx;
      let newH = rs.origHeight + dy;
      newW = Math.max(CARD_MIN_WIDTH, newW);
      newH = Math.max(CARD_MIN_HEIGHT, newH);
      newW = Math.min(newW, containerRect.width - rs.origLeft);
      newH = Math.min(newH, containerRect.height - rs.origTop);
      rs.panel.style.width  = `${newW}px`;
      rs.panel.style.height = `${newH}px`;
    }
  }

  _onPointerUp(e) {
    window.removeEventListener("pointermove", this._boundPointerMove);
    window.removeEventListener("pointerup", this._boundPointerUp);
    window.removeEventListener("pointercancel", this._boundPointerUp);
    if (this.dragState) {
      const panel = this.dragState.panel;
      panel.style.transition = "";
      panel.style.zIndex = "";
      try { panel.releasePointerCapture(this.dragState.pointerId); } catch (ex) { /* */ }
      this.dragState = null;
      this._syncLayoutFromDOM();
      this._saveLayout();
    }
    if (this.resizeState) {
      this.resizeState.panel.style.transition = "";
      this.resizeState = null;
      this._syncLayoutFromDOM();
      this._saveLayout();
    }
  }

  _syncLayoutFromDOM() {
    const canvas = this._getCanvas();
    if (canvas.w <= 0 || canvas.h <= 0) return;
    for (const [cardId, panel] of this.cards) {
      const rect = panel.getBoundingClientRect();
      const containerRect = this.container.getBoundingClientRect();
      this.layout[cardId] = {
        x: (rect.left - containerRect.left) / canvas.w,
        y: (rect.top - containerRect.top - canvas.y) / canvas.h,
        w: rect.width / canvas.w,
        h: rect.height / canvas.h,
      };
    }
  }

  _bindResizeObserver() {
    if (typeof ResizeObserver !== "undefined") {
      const ro = new ResizeObserver(() => this.applyLayout());
      ro.observe(this.container);
    } else {
      let resizeTimer;
      window.addEventListener("resize", () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => this.applyLayout(), 100);
      });
    }
  }

  resetLayout() {
    this.layout = JSON.parse(JSON.stringify(DEFAULT_LAYOUT));
    this._saveLayout();
    this.applyLayout();
  }
}

async function api(path, body = null) {
  const options = body
    ? {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }
    : {};
  const response = await fetch(path, options);
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `璇锋眰澶辫触锛?{path}`);
  }
  return payload;
}

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("show");
  clearTimeout(window.__toastTimer);
  window.__toastTimer = setTimeout(() => node.classList.remove("show"), 2800);
}

function asFixed(value) {
  if (value === null || value === undefined || value === "") return "--";
  return Number(value).toFixed(2);
}

function badgeClass(value) {
  if (["OK", "BOUND", "COMPLETED", true].includes(value)) return "badge good";
  if (["NG", "DUPLICATE", "RULE_NG", false].includes(value)) return "badge bad";
  return "badge warn";
}

function setBadge(selector, text, value = text) {
  const node = $(selector);
  node.textContent = text;
  node.className = badgeClass(value);
}

// ---------------------------------------------------------------------------
// Scanner live feedback
// ---------------------------------------------------------------------------

function updateScannerBadge() {
  const port = scannerConfig.com_port || "COM3";
  const baud = scannerConfig.baudrate || 115200;
  if (lastQr) {
    setBadge("#scannerBadge", `\u626b\u7801\u67aa ${port} \u2713`, true);
  } else {
    setBadge("#scannerBadge", `\u626b\u7801\u67aa ${port}`, "warn");
  }
  // Also update the live bar status
  const liveBar = $("#scannerLiveBar");
  if (liveBar && scannerScans.length === 0) {
    liveBar.style.display = "none";
  }
}

function onScannerScan(code) {
  const now = new Date();
  const timeStr = now.toLocaleTimeString();

  // Show live bar
  const liveBar = $("#scannerLiveBar");
  liveBar.style.display = "flex";
  $("#scannerLiveCode").textContent = code;
  $("#scannerLiveTime").textContent = timeStr;

  // Flash effect
  liveBar.style.background = "#0a2a0a";
  setTimeout(() => { liveBar.style.background = "#1a2a1a"; }, 150);

  // Auto-fill QR input
  $("#qrInput").value = code;

  // History
  scannerScans.unshift({ code, time: timeStr });
  if (scannerScans.length > 15) scannerScans.pop();
  renderScannerHistory();

  // Update badge
  updateScannerBadge();
}

async function submitQrBinding(code, okMessage = "\u4e8c\u7ef4\u7801\u7ed1\u5b9a\u5b8c\u6210") {
  const payload = await api("/api/scan", { qr_code: code });
  await loadStatus();
  const alarm = payload?.alarm || {};
  const qrStatus = payload?.current_record?.qr_bind_status || "";
  if (alarm.code === "QR_DUP" || qrStatus === "DUPLICATE") {
    toast(alarm.message || "\u4e8c\u7ef4\u7801\u91cd\u590d\uff0c\u8bf7\u7ee7\u7eed\u626b\u7801");
    return payload;
  }
  if (alarm.code === "QR_RULE_NG" || qrStatus === "RULE_NG") {
    toast(alarm.message || "\u4e8c\u7ef4\u7801\u4e0d\u7b26\u5408\u5f53\u524d\u89c4\u5219");
    return payload;
  }
  toast(okMessage);
  return payload;
}

function renderScannerHistory() {
  const historyDiv = $("#scannerHistory");
  const itemsDiv = $("#scannerHistoryItems");
  if (scannerScans.length === 0) {
    historyDiv.style.display = "none";
    return;
  }
  historyDiv.style.display = "block";
  itemsDiv.innerHTML = scannerScans.map((s) =>
    `<div style="display:flex;justify-content:space-between;padding:0.15rem 0;font-size:0.72rem;border-bottom:1px solid rgba(255,255,255,.04);">
      <span style="font-family:Consolas,monospace;color:var(--ink);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:70%;">${escapeHtml(s.code)}</span>
      <span style="color:var(--muted);flex-shrink:0;">${s.time}</span>
    </div>`
  ).join("");
}

// ---------------------------------------------------------------------------
// Datasets page -- camera live view + transform controls + exposure
// ---------------------------------------------------------------------------

const CAMERA_SETTINGS_KEY = "datasets_camera_settings_v1";

function normalizeCameraTransformState(rawTransform) {
  const next = {
    zoom: Number(rawTransform?.zoom ?? 1.0),
    rotate: Number(rawTransform?.rotate ?? 0),
    panX: Number(rawTransform?.panX ?? 0),
    panY: Number(rawTransform?.panY ?? 0),
  };
  const hasFiniteValues = [next.zoom, next.rotate, next.panX, next.panY].every(Number.isFinite);
  if (!hasFiniteValues || next.zoom < 1.0 || next.zoom > ZOOM_MAX) {
    return { zoom: 1.0, rotate: 0, panX: 0, panY: 0 };
  }
  return {
    zoom: Math.max(1.0, Math.min(ZOOM_MAX, next.zoom)),
    rotate: next.rotate,
    panX: next.zoom <= 1.0 ? 0 : next.panX,
    panY: next.zoom <= 1.0 ? 0 : next.panY,
  };
}

function loadSavedCameraSettings() {
  try {
    const saved = JSON.parse(localStorage.getItem(CAMERA_SETTINGS_KEY) || "{}");
    if (saved.transform) {
      const normalized = normalizeCameraTransformState(saved.transform);
      datasetsTransform = normalized;
      if (JSON.stringify(normalized) !== JSON.stringify(saved.transform)) {
        saved.transform = normalized;
        localStorage.setItem(CAMERA_SETTINGS_KEY, JSON.stringify(saved));
      }
    }
    if (saved.transformBase && Number(saved.transformBase.width) > 0 && Number(saved.transformBase.height) > 0) {
      datasetsTransformBase = {
        width: Number(saved.transformBase.width),
        height: Number(saved.transformBase.height),
      };
    }
    return saved;
  } catch (e) {
    return {};
  }
}

function refreshTransformBaseFromDatasets() {
  const dsImg = document.getElementById("datasetsCameraFeed");
  if (!dsImg) return;
  const width = Number(dsImg.clientWidth || 0);
  const height = Number(dsImg.clientHeight || 0);
  if (width > 0 && height > 0) {
    datasetsTransformBase = { width, height };
    try {
      const raw = localStorage.getItem(CAMERA_SETTINGS_KEY);
      if (!raw) return;
      const saved = JSON.parse(raw);
      const savedWidth = Number(saved.transformBase?.width || 0);
      const savedHeight = Number(saved.transformBase?.height || 0);
      if (savedWidth === width && savedHeight === height) return;
      saved.transform = { ...datasetsTransform };
      saved.transformBase = { ...datasetsTransformBase };
      localStorage.setItem(CAMERA_SETTINGS_KEY, JSON.stringify(saved));
    } catch (e) {
      // ignore
    }
  }
}

function saveCameraSettings() {
  refreshTransformBaseFromDatasets();
  const settings = {
    transform: { ...datasetsTransform },
    transformBase: { ...datasetsTransformBase },
    exposure_us: Number(document.getElementById("exposureSlider")?.value || EXPOSURE_DEFAULT),
    saved_at: new Date().toISOString(),
  };
  try {
    localStorage.setItem(CAMERA_SETTINGS_KEY, JSON.stringify(settings));
  } catch (e) {
    // ignore
  }
}

function clampCameraTransformForElement(element, transform) {
  if (!element) return { ...transform };
  const width = Number(element.clientWidth || 0);
  const height = Number(element.clientHeight || 0);
  const zoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, Number(transform.zoom || 1.0)));
  const rotate = Number(transform.rotate || 0);
  if (width <= 0 || height <= 0) {
    return {
      zoom,
      rotate,
      panX: Number(transform.panX || 0),
      panY: Number(transform.panY || 0),
    };
  }

  const overflowX = Math.max(0, ((zoom - 1) * width) / 2);
  const overflowY = Math.max(0, ((zoom - 1) * height) / 2);
  const slackX = zoom <= 1.0 ? 0 : Math.max(36, width * 0.12);
  const slackY = zoom <= 1.0 ? 0 : Math.max(28, height * 0.12);
  const maxPanX = overflowX + slackX;
  const maxPanY = overflowY + slackY;

  return {
    zoom,
    rotate,
    panX: Math.max(-maxPanX, Math.min(maxPanX, Number(transform.panX || 0))),
    panY: Math.max(-maxPanY, Math.min(maxPanY, Number(transform.panY || 0))),
  };
}

function applyDatasetsTransform() {
  const normalized = clampCameraTransformForElement(
    document.getElementById("datasetsCameraFeed") || document.getElementById("cameraFeed"),
    datasetsTransform,
  );
  datasetsTransform = normalized;
  const { zoom, rotate, panX, panY } = normalized;
  // Apply to datasets camera feed
  const dsImg = document.getElementById("datasetsCameraFeed");
  if (dsImg) {
    const dsTransform = clampCameraTransformForElement(dsImg, normalized);
    dsImg.style.transform = `translate(${dsTransform.panX}px, ${dsTransform.panY}px) rotate(${rotate}deg) scale(${zoom})`;
    refreshTransformBaseFromDatasets();
  }
  // Apply to production camera feed
  const prodImg = document.getElementById("cameraFeed");
  if (prodImg) {
    const baseWidth = Number(datasetsTransformBase.width || 0);
    const baseHeight = Number(datasetsTransformBase.height || 0);
    const widthRatio = baseWidth > 0 ? Number(prodImg.clientWidth || 0) / baseWidth : 1;
    const heightRatio = baseHeight > 0 ? Number(prodImg.clientHeight || 0) / baseHeight : 1;
    const syncedPanX = panX * (widthRatio > 0 ? widthRatio : 1);
    const syncedPanY = panY * (heightRatio > 0 ? heightRatio : 1);
    const prodTransform = clampCameraTransformForElement(prodImg, {
      zoom,
      rotate,
      panX: syncedPanX,
      panY: syncedPanY,
    });
    prodImg.style.transform = `translate(${prodTransform.panX}px, ${prodTransform.panY}px) rotate(${rotate}deg) scale(${zoom})`;
    prodImg.style.transformOrigin = "center center";
    prodImg.style.transition = "transform 0.12s ease";
  }
  const parts = [];
  if (zoom !== 1.0) parts.push(`${zoom.toFixed(1)}x`);
  if (rotate !== 0) parts.push(`${rotate}掳`);
  if (panX !== 0 || panY !== 0) parts.push(`(${panX},${panY})px`);
  const badgeText = parts.join(" ");
  for (const badge of [document.getElementById("transformBadge"), document.getElementById("productionTransformBadge")]) {
    if (!badge) continue;
    badge.textContent = badgeText;
    badge.style.display = badgeText ? "" : "none";
  }
  return;
  // Update badge
  const badge = document.getElementById("transformBadge");
  if (badge) {
    const parts = [];
    if (zoom !== 1.0) parts.push(`${zoom.toFixed(1)}x`);
    if (rotate !== 0) parts.push(`${rotate}掳`);
    if (panX !== 0 || panY !== 0) parts.push(`(${panX},${panY})px`);
    badge.textContent = parts.length > 0 ? parts.join(" ") : "";
    badge.style.display = parts.length > 0 ? "" : "none";
  }
}

function startDatasetsFeed() {
  if (window.__datasetsFeedTimer) clearInterval(window.__datasetsFeedTimer);
  const feedTimer = setInterval(() => {
    const img = document.getElementById("datasetsCameraFeed");
    if (!img) return;
    img.onerror = () => {
      const badge = document.getElementById("captureCameraBadge");
      if (badge) { badge.textContent = "相机未连接"; badge.className = "badge bad"; }
    };
    img.onload = () => {
      const badge = document.getElementById("captureCameraBadge");
      if (badge) { badge.textContent = "实时画面"; badge.className = "badge good"; }
    };
    img.src = "/api/vision/latest-frame?t=" + Date.now();
  }, 200);
  window.__datasetsFeedTimer = feedTimer;
}

function readCameraPollLease() {
  try {
    const raw = localStorage.getItem(CAMERA_POLL_LEASE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (_) {
    return null;
  }
}

function writeCameraPollLease(expiresAt) {
  try {
    localStorage.setItem(
      CAMERA_POLL_LEASE_KEY,
      JSON.stringify({ tabId: CAMERA_POLL_TAB_ID, expiresAt }),
    );
  } catch (_) {
    // Ignore storage failures; polling still works in a single tab.
  }
}

function releaseCameraPollLease() {
  try {
    const lease = readCameraPollLease();
    if (lease?.tabId === CAMERA_POLL_TAB_ID) {
      localStorage.removeItem(CAMERA_POLL_LEASE_KEY);
    }
  } catch (_) {
    // Ignore storage failures.
  }
}

function tryClaimCameraPollLease() {
  if (document.hidden) {
    releaseCameraPollLease();
    return false;
  }
  const now = Date.now();
  const lease = readCameraPollLease();
  if (!lease || lease.tabId === CAMERA_POLL_TAB_ID || Number(lease.expiresAt || 0) <= now) {
    writeCameraPollLease(now + CAMERA_POLL_LEASE_MS);
  }
  return readCameraPollLease()?.tabId === CAMERA_POLL_TAB_ID;
}

function getActiveMainTab() {
  return document.querySelector(".tab-btn.active")?.dataset.tab || "production";
}

function refreshCameraFeeds(force = false) {
  if (!force && document.hidden) return;
  const activeTab = getActiveMainTab();
  const frameUrl = "/api/vision/latest-frame?t=" + Date.now();

  if (activeTab === "datasets") {
    const img = document.getElementById("datasetsCameraFeed");
    if (!img) return;
    img.onerror = () => {
      const badge = document.getElementById("captureCameraBadge");
      if (badge) {
        badge.textContent = "相机未连接";
        badge.className = "badge bad";
      }
    };
    img.onload = () => {
      const badge = document.getElementById("captureCameraBadge");
      if (badge) {
        badge.textContent = "实时画面";
        badge.className = "badge good";
      }
      applyDatasetsTransform();
    };
    img.src = frameUrl;
    return;
  }

  const img = document.getElementById("cameraFeed");
  if (!img) return;
  img.onerror = () => {
    const status = document.getElementById("cameraStatus");
    if (status) status.textContent = "相机未连接";
  };
  img.onload = () => {
    const status = document.getElementById("cameraStatus");
    if (status) status.textContent = "实时画面";
    applyDatasetsTransform();
  };
  img.src = frameUrl;
}

function startCameraFeedPolling() {
  if (window.__cameraFeedTimer) clearInterval(window.__cameraFeedTimer);
  if (tryClaimCameraPollLease()) {
    refreshCameraFeeds(true);
  }
  window.__cameraFeedTimer = setInterval(() => {
    if (tryClaimCameraPollLease()) {
      refreshCameraFeeds(false);
    }
  }, CAMERA_FEED_INTERVAL_MS);
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && tryClaimCameraPollLease()) {
    refreshCameraFeeds(true);
    return;
  }
  releaseCameraPollLease();
});

window.addEventListener("storage", (event) => {
  if (event.key === CAMERA_POLL_LEASE_KEY && tryClaimCameraPollLease()) {
    refreshCameraFeeds(true);
  }
});

async function autoConnectAndRestore() {
  // Try to connect camera
  try {
    const payload = await api("/api/camera/connect", {});
    if (payload.connected && !payload.is_mock) {
      const badge = document.getElementById("captureCameraBadge");
      if (badge) { badge.textContent = "实时画面"; badge.className = "badge good"; }
    } else if (payload.is_mock) {
      const badge = document.getElementById("captureCameraBadge");
      if (badge) { badge.textContent = "相机未连接"; badge.className = "badge bad"; }
    }
  } catch (e) {
    // Camera might already be connected, feed will show status
  }
  // Restore saved exposure
  try {
    await loadCameraExposure();
  } catch (e) {
    // not critical
  }
  // Restore saved transform
  loadSavedCameraSettings();
  applyDatasetsTransform();
}

async function loadCameraExposure() {
  try {
    const payload = await api("/api/camera/exposure");
    const val = payload.exposure_us || EXPOSURE_DEFAULT;
    const slider = document.getElementById("exposureSlider");
    const label = document.getElementById("exposureValue");
    if (slider) slider.value = val;
    if (label) label.textContent = `${Math.round(val)} us`;
  } catch (e) {
    // Camera not ready, leave defaults
  }
}

async function setCameraExposure(valueUs) {
  try {
    const payload = await api("/api/camera/exposure", { exposure_us: Number(valueUs) });
    const label = document.getElementById("exposureValue");
    if (label && payload.exposure_us != null) {
      label.textContent = `${Math.round(payload.exposure_us)} us`;
    }
    if (payload.ok) {
      // Auto-save to server already done by API
    }
  } catch (e) {
    toast(`鏇濆厜璁剧疆澶辫触: ${e.message}`);
  }
}

async function autoLoginAndStart() {
  // Ensure product/operator lists are populated before proceeding
  if (!settings || !settings.products) {
    await loadSettings();
  }
  // Auto-login with default operator
  try {
    await api("/api/login", {
      operator: document.getElementById("operatorInput")?.value || "OP001",
      shift: "鐧界彮",
    });
  } catch (e) { /* ignore */ }

  // Write Kilews params for current product
  try {
    const product = document.getElementById("productSelect")?.value;
    if (product) {
      await api("/api/kilews/write-params", { product_model: product });
    }
  } catch (e) { /* ignore */ }

}

async function loadSettings() {
  settings = await api("/api/settings");
  if (window.__selectedProduct && !getProductConfigByModel(window.__selectedProduct)) {
    window.__selectedProduct = "";
  }
  scannerConfig = settings.scanner || scannerConfig;
  updateScannerBadge();
  renderSettings();
  renderProductOptions();
  renderProductSummary(statusSnapshot);
}

async function loadStatus() {
  statusSnapshot = await api("/api/status");
  setBadge("#connectionBadge", "本机在线", true);
  renderStatus(statusSnapshot);

  // Scanner: detect new scan
  const qr = statusSnapshot.last_qr || "";
  if (qr && qr !== lastQr) {
    lastQr = qr;
    onScannerScan(qr);
  }
  const alarm = statusSnapshot.alarm || {};
  const qrStatus = statusSnapshot.current_record?.qr_bind_status || "";
  const scanAlertKey = [alarm.code || "", alarm.message || "", statusSnapshot.last_qr || "", qrStatus].join("|");
  if (
    scanAlertKey &&
    scanAlertKey !== lastScanAlertKey &&
    (alarm.code === "QR_DUP" || alarm.code === "QR_RULE_NG" || qrStatus === "DUPLICATE" || qrStatus === "RULE_NG")
  ) {
    lastScanAlertKey = scanAlertKey;
    toast(alarm.message || (alarm.code === "QR_DUP" ? "\u4e8c\u7ef4\u7801\u91cd\u590d\uff0c\u8bf7\u7ee7\u7eed\u626b\u7801" : "\u4e8c\u7ef4\u7801\u4e0d\u7b26\u5408\u5f53\u524d\u89c4\u5219"));
  } else if (!alarm.code && qrStatus !== "DUPLICATE" && qrStatus !== "RULE_NG") {
    lastScanAlertKey = "";
  }
  updateScannerBadge();
}

function startStatusPolling() {
  if (window.__statusPollTimer) clearInterval(window.__statusPollTimer);
  window.__statusPollTimer = setInterval(() => {
    if (document.hidden) return;
    loadStatus().catch(() => setBadge("#connectionBadge", "连接异常", false));
  }, STATUS_POLL_INTERVAL_MS);
}

function renderProductOptions() {
  const select = $("#productSelect");
  select.innerHTML = "";
  const products = (settings.products || []).filter((product) => product.enabled !== false);
  const preferredProduct = window.__selectedProduct || settings.station.active_product_model || "";
  for (const product of products) {
    const option = document.createElement("option");
    option.value = product.product_model;
    option.textContent = product.product_model;
    option.dataset.recipeNo = product.recipe_no;
    option.selected = product.product_model === preferredProduct;
    select.appendChild(option);
  }
  if (products.length === 0) {
    window.__selectedProduct = "";
    return;
  }
  const activeProduct = products.some((product) => product.product_model === preferredProduct)
    ? preferredProduct
    : products[0].product_model;
  select.value = activeProduct;
  window.__selectedProduct = activeProduct;
}

function renderOperatorList() {
  const select = $("#operatorInput");
  if (!select || select.tagName !== "SELECT") return;
  const currentVal = select.value;
  select.innerHTML = "";
  for (const person of settings.personnel || []) {
    if (person.enabled === false) continue;
    const option = document.createElement("option");
    option.value = person.employee_id;
    option.textContent = `${person.employee_id} - ${person.name}`;
    select.appendChild(option);
  }
  select.value = currentVal || settings.auth.default_operator || "";
}

function renderSettings() {
  $("#setStationId").value = settings.station.station_id;
  $("#setLineName").value = settings.station.line_name;
  $("#setModelPath").value = settings.vision.model_path;
  $("#setCameraIp").value = settings.vision.camera_ip;
  $("#setConfidenceThreshold").value = settings.vision.confidence_threshold ?? 0.6;
  $("#setInferenceEnabled").checked = settings.vision.inference_enabled !== false;
  $("#setInferenceIntervalMs").value = settings.vision.inference_interval_ms ?? 300;
  $("#setAutoCaptureEnabled").checked = settings.vision.auto_capture_enabled !== false;
  $("#setPlcIp").value = settings.plc.ip;
  $("#setPlcPort").value = settings.plc.port;
  $("#setPlcRack").value = settings.plc.rack ?? 0;
  $("#setPlcSlot").value = settings.plc.slot ?? 1;
  $("#setPlcTimeout").value = settings.plc.timeout ?? 2.0;
  $("#setPlcReconnect").value = settings.plc.reconnect_interval_s ?? 5.0;
  $("#setPlcEnabled").checked = settings.plc.enabled === true;
  $("#setPlcAutoConnect").checked = settings.plc.auto_connect === true;
  var acfg = settings.automation || {};
  $("#setAutomationEnabled").checked = acfg.enabled === true;
  $("#setStabilityDuration").value = acfg.stability_duration_s ?? 2.0;
  $("#setStabilityThreshold").value = acfg.stability_position_threshold_px ?? 30;
  $("#setCoverageThreshold").value = acfg.coverage_ratio_threshold ?? 0.85;
  $("#setTighteningPoll").value = acfg.tightening_poll_interval_ms ?? 300;
  $("#setTighteningTimeout").value = acfg.tightening_timeout_s ?? 30.0;
  $("#setKilewsIp").value = settings.kilews.ip;
  $("#setKilewsPort").value = settings.kilews.port;
  $("#setKilewsUnitId").value = settings.kilews.unit_id;
  $("#setKilewsSpeed").value = settings.kilews.speed_rpm;
  $("#setKilewsEnabled").checked = settings.kilews.enabled;
  $("#setKilewsAutoConnect").checked = settings.kilews.auto_connect;
  $("#setScannerMode").value = settings.scanner.mode;
  $("#setScannerPort").value = settings.scanner.port;
  $("#setExportRoot").value = settings.data.export_root;
  $("#setImageRoot").value = settings.data.image_root;
  $("#setDatasetRoot").value = settings.data.dataset_root;
  renderProductTable();
  renderPersonTable();
  renderOperatorList();
}

function productTemplate(index) {
  const no = index + 1;
  return {
    enabled: true,
    product_model: `NEW-${String(no).padStart(3, "0")}`,
    recipe_no: no,
    bolt_count: 2,
    torque_target_nm: 4.5,
    torque_min_nm: 4.0,
    torque_max_nm: 5.0,
    angle_target_deg: 90.0,
    angle_min_deg: 70.0,
    angle_max_deg: 120.0,
    kilews_job_no: 0,
    qr_rule: DEFAULT_QR_RULE,
    enable_vision_interlock: true,
    enable_qr_binding: true,
    reject_duplicate_qr: true,
  };
}

function personTemplate(index) {
  return {
    enabled: true,
    employee_id: `OP${String(index + 1).padStart(3, "0")}`,
    name: "鏂版搷浣滃憳",
    role: "\u64cd\u4f5c\u5458",
    shift: "鐧界彮",
  };
}

function renderProductTable() {
  applyProductGridWidths();
  const rows = settings.products || [];
  const header = `
    <div class="config-header product-grid" aria-hidden="true">
      <span title="\u542f\u7528/\u7981\u7528">\u542f\u7528</span>
      <span class="resizable-head" title="\u4ea7\u54c1\u578b\u53f7"><span>\u4ea7\u54c1\u578b\u53f7</span><button type="button" class="col-resizer" data-resize-col="model" aria-label="\u62d6\u62fd\u8c03\u6574\u578b\u53f7\u5217\u5bbd\u5ea6"></button></span>
      <span title="\u87ba\u4e1d\u6570\u91cf">\u87ba\u4e1d\u6570</span>
      <span title="\u76ee\u6807\u626d\u77e9 (N\u00b7m)">\u76ee\u6807\u626d\u77e9</span>
      <span title="\u626d\u77e9\u4e0b\u9650 (N\u00b7m)">\u626d\u77e9\u4e0b\u9650</span>
      <span title="\u626d\u77e9\u4e0a\u9650 (N\u00b7m)">\u626d\u77e9\u4e0a\u9650</span>
      <span title="\u89d2\u5ea6\u4e0b\u9650 (\u00b0)">\u89d2\u5ea6\u4e0b\u9650</span>
      <span title="\u89d2\u5ea6\u4e0a\u9650 (\u00b0)">\u89d2\u5ea6\u4e0a\u9650</span>
      <span class="resizable-head" title="\u4e8c\u7ef4\u7801\u6b63\u5219\u89c4\u5219"><span>\u4e8c\u7ef4\u7801\u89c4\u5219</span><button type="button" class="col-resizer" data-resize-col="rule" aria-label="\u62d6\u62fd\u8c03\u6574\u89c4\u5219\u5217\u5bbd\u5ea6"></button></span>
      <span title="\u89c6\u89c9\u8054\u9501\u4e92\u9501">\u89c6\u89c9\u8054\u9501</span>
      <span title="\u7ed1\u5b9a\u4e8c\u7ef4\u7801">\u7ed1\u5b9aQR</span>
      <span title="\u91cd\u590d\u4e8c\u7ef4\u7801\u62e6\u622a">\u91cd\u590d\u62e6\u622a</span>
      <span title="\u5220\u9664\u4ea7\u54c1">\u5220\u9664</span>
    </div>
  `;

  const body = rows
    .map(
      (product, index) => `
      <div class="config-row product-grid" data-product-row="${index}">
        <input class="row-check" type="checkbox" data-product-field="enabled" ${product.enabled !== false ? "checked" : ""}>
        <input class="cell-input row-input model-cell" data-product-field="product_model" value="${escapeHtml(product.product_model)}" title="\u4ea7\u54c1\u578b\u53f7">
        <input class="cell-input row-input" type="number" min="1" max="2" data-product-field="bolt_count" value="${product.bolt_count}" title="\u87ba\u4e1d\u6570">
        <input class="cell-input row-input" type="number" step="0.01" data-product-field="torque_target_nm" value="${product.torque_target_nm}" title="\u76ee\u6807\u626d\u529b">
        <input class="cell-input row-input" type="number" step="0.01" data-product-field="torque_min_nm" value="${product.torque_min_nm}" title="\u6700\u5c0f\u626d\u529b">
        <input class="cell-input row-input" type="number" step="0.01" data-product-field="torque_max_nm" value="${product.torque_max_nm}" title="\u6700\u5927\u626d\u529b">
        <input class="cell-input row-input" type="number" step="0.01" data-product-field="angle_min_deg" value="${product.angle_min_deg}" title="\u89d2\u5ea6\u4e0b\u9650">
        <input class="cell-input row-input" type="number" step="0.01" data-product-field="angle_max_deg" value="${product.angle_max_deg}" title="\u6700\u5927\u89d2\u5ea6">
        <input class="cell-input row-input qr-cell" data-product-field="qr_rule" value="${escapeHtml(product.qr_rule)}" title="\u4e8c\u7ef4\u7801\u89c4\u5219">
        <label class="row-flag" title="\u89c6\u89c9\u8054\u9501\u4e92\u9501"><input type="checkbox" data-product-field="enable_vision_interlock" ${product.enable_vision_interlock !== false ? "checked" : ""}><span>\u89c6\u89c9</span></label>
        <label class="row-flag" title="\u7ed1\u5b9a\u4e8c\u7ef4\u7801"><input type="checkbox" data-product-field="enable_qr_binding" ${product.enable_qr_binding !== false ? "checked" : ""}><span>\u7ed1\u7801</span></label>
        <label class="row-flag" title="\u91cd\u590d\u4e8c\u7ef4\u7801\u62e6\u622a"><input type="checkbox" data-product-field="reject_duplicate_qr" ${product.reject_duplicate_qr !== false ? "checked" : ""}><span>\u62e6\u622a</span></label>
        <button class="danger mini row-delete" data-remove-product="${index}">\u5220\u9664</button>
      </div>
    `,
    )
    .join("");

  $$("[data-remove-person]").forEach((button) => {
    button.addEventListener("click", () => {
      if ((settings.personnel || []).length <= 1) {
        toast("\u81f3\u5c11\u4fdd\u7559\u4e00\u4e2a\u4eba\u5458");
        return;
      }
      settings.personnel.splice(Number(button.dataset.removePerson), 1);
      renderPersonTable();
      renderOperatorList();
    });
  });

  $("#productRows").innerHTML = header + body;
  bindProductGridResizers();
  $$("[data-remove-product]").forEach((button) => {
    button.addEventListener("click", () => {
      if ((settings.products || []).length <= 1) {
        toast("\u81f3\u5c11\u4fdd\u7559\u4e00\u4e2a\u4ea7\u54c1");
        return;
      }
      settings.products.splice(Number(button.dataset.removeProduct), 1);
      renderProductTable();
      renderProductOptions();
    });
  });
}

function renderPersonTable() {
  const rows = settings.personnel || [];
  const header = `
    <div class="config-header person-grid" aria-hidden="true">
      <span title="\u5de5\u53f7">\u5de5\u53f7</span>
      <span title="\u59d3\u540d">\u59d3\u540d</span>
      <span title="\u5220\u9664">\u5220\u9664</span>
    </div>
  `;

  const body = rows
    .map(
      (person, index) => `
      <div class="config-row person-grid" data-person-row="${index}">
        <input class="cell-input row-input" data-person-field="employee_id" value="${escapeHtml(person.employee_id)}" title="\u5de5\u53f7">
        <input class="cell-input row-input" data-person-field="name" value="${escapeHtml(person.name)}" title="\u59d3\u540d">
        <button class="danger mini row-delete" data-remove-person="${index}">\u5220\u9664</button>
      </div>
    `,
    )
    .join("");

  $("#personRows").innerHTML = header + body;
}

function collectProductRows() {
  const numberFields = new Set([
    "recipe_no",
    "kilews_job_no",
    "bolt_count",
    "torque_target_nm",
    "torque_min_nm",
    "torque_max_nm",
    "angle_target_deg",
    "angle_min_deg",
    "angle_max_deg",
  ]);
  const products = [];
  $$("[data-product-row]").forEach((row) => {
    const product = {};
    row.querySelectorAll("[data-product-field]").forEach((input) => {
      const field = input.dataset.productField;
      if (input.type === "checkbox") {
        product[field] = input.checked;
      } else if (numberFields.has(field)) {
        product[field] = Number(input.value);
      } else {
        product[field] = input.value.trim();
      }
    });
    if (product.product_model) products.push(product);
  });
  if (products.length > MAX_PRODUCTS) throw new Error("\u4ea7\u54c1\u8bbe\u7f6e\u6700\u591a 255 \u884c");
  if (products.length < 1) throw new Error("\u81f3\u5c11\u9700\u8981 1 \u4e2a\u4ea7\u54c1\u578b\u53f7");
  return products;
}

function collectPersonRows() {
  const personnel = [];
  $$("[data-person-row]").forEach((row) => {
    const person = {};
    row.querySelectorAll("[data-person-field]").forEach((input) => {
      const field = input.dataset.personField;
      person[field] = input.type === "checkbox" ? input.checked : input.value.trim();
    });
    if (person.employee_id) personnel.push(person);
  });
  if (personnel.length > MAX_PERSONNEL) throw new Error("\u4eba\u5458\u8bbe\u7f6e\u6700\u591a 255 \u4e2a");
  if (personnel.length < 1) throw new Error("\u81f3\u5c11\u9700\u8981 1 \u4e2a\u4eba\u5458");
  return personnel;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatStatusLabel(value) {
  const labels = {
    WAIT: "待机",
    OK: "OK",
    NG: "NG",
    RUNNING: "\u8fd0\u884c\u4e2d",
    WAIT_QR: "待扫码",
    COMPLETED: "完成",
    BOUND: "\u5df2\u7ed1\u5b9a",
    RULE_NG: "规则 NG",
    DUPLICATE: "重复",
    NG_WAIT_REWORK: "\u5f85\u8fd4\u4fee",
  };
  return labels[value] || value || "--";
}

function chipTone(value) {
  if (["OK", "BOUND", "COMPLETED"].includes(value)) return "good";
  if (["NG", "RULE_NG", "DUPLICATE", "NG_WAIT_REWORK"].includes(value)) return "bad";
  return "warn";
}

function renderStatusChip(value) {
  const label = formatStatusLabel(value);
  return `<span class="status-chip ${chipTone(value)}">${escapeHtml(label)}</span>`;
}

function formatRecentTime(value) {
  if (!value) return "";
  const normalized = String(value).replace("T", " ");
  return normalized.length >= 16 ? normalized.slice(5, 16) : normalized;
}

function getProductConfigByModel(productModel) {
  if (!productModel) return null;
  return (settings?.products || []).find((product) => product.product_model === productModel) || null;
}

function getDisplayProductModel(snapshot = statusSnapshot) {
  const selectedValue = $("#productSelect")?.value || "";
  return (
    window.__selectedProduct ||
    selectedValue ||
    settings?.station?.active_product_model ||
    snapshot?.settings_summary?.product_model ||
    ""
  );
}

function renderProductSummary(snapshot = statusSnapshot) {
  const displayProduct = getDisplayProductModel(snapshot);
  const prodCfg = getProductConfigByModel(displayProduct);
  if (prodCfg) {
    $("#productText").textContent = `${prodCfg.product_model} / ${prodCfg.recipe_no}`;
    $("#recipeText").textContent = `扭矩 ${prodCfg.torque_min_nm.toFixed(2)}-${prodCfg.torque_max_nm.toFixed(2)} Nm / 角度 ${prodCfg.angle_min_deg.toFixed(0)}-${prodCfg.angle_max_deg.toFixed(0)}°`;
    return;
  }
  if (snapshot?.settings_summary) {
    $("#productText").textContent = `${snapshot.settings_summary.product_model} / ${snapshot.settings_summary.recipe_no}`;
    $("#recipeText").textContent = `扭矩 ${snapshot.settings_summary.torque} / 角度 ${snapshot.settings_summary.angle}`;
    return;
  }
  $("#productText").textContent = "--";
  $("#recipeText").textContent = "扭矩 -- / 角度 --";
}

function renderStatus(snapshot) {
  $("#stateLabel").textContent = snapshot.state_label;
  const record = snapshot.current_record || {};
  $("#serialText").textContent = record.internal_serial || "--";
  $("#qrText").textContent = `\u4e8c\u7ef4\u7801\uff1a${record.qr_code || record.qr_bind_status || "\u5f85\u7ed1\u5b9a"}`;
  renderProductSummary(snapshot);
  $("#alarmText").textContent = snapshot.alarm.message ? `${snapshot.alarm.code}: ${snapshot.alarm.message}` : "\u65e0\u62a5\u8b66";
  $("#alarmText").style.color = snapshot.alarm.message ? "#ffd6c9" : "rgba(255,255,255,.76)";
  setBadge("#visionBadge", snapshot.vision.status, snapshot.vision.status);
  setBadge("#permissionBadge", snapshot.pc_outputs.allow_tightening ? "\u5141\u8bb8\u62e7\u7d27" : "\u672a\u8bb8\u53ef", !!snapshot.pc_outputs.allow_tightening);
  setBadge("#scanBadge", snapshot.state === "pending_scan" ? "\u53ef\u626b\u7801" : record.qr_bind_status || "\u5f85\u6d41\u7a0b\u7ed3\u675f", record.qr_bind_status);
  updateStepTrack(snapshot.state);
  renderVision(snapshot.vision, snapshot.alarm);
  renderPlc(snapshot.plc);
  renderAutomation(snapshot);
  renderBolts(snapshot.bolts);
  renderRecent(snapshot.recent_records || [], snapshot.today_stats || {});

  // Kilews live status
  const kw = snapshot.kilews;
  if (kw) {
    if (kw.connected) {
      setBadge("#kilewsConnBadge", "\u63a7\u5236\u5668\u5728\u7ebf", true);
    } else {
      setBadge("#kilewsConnBadge", snapshot.kilews && !kw.connected ? "\u63a7\u5236\u5668\u79bb\u7ebf" : "--", false);
    }
    $("#kilewsLiveJob").textContent = kw.current_job ? `J${kw.current_job}/S${kw.current_seq}` : "--";
    $("#kilewsLiveTorque").textContent = kw.torque_nm != null ? `${kw.torque_nm.toFixed(2)} N路m` : "--";
    $("#kilewsLiveAngle").textContent = kw.angle_deg != null ? `${kw.angle_deg.toFixed(1)}掳` : "--";
    const rcode = kw.result_code;
    const rlabels = {4:"OK",5:"OK-SEQ",6:"OK-JOB",7:"NG",8:"NS"};
    const rlabel = rlabels[rcode] || rcode || "--";
    $("#kilewsLiveResult").textContent = rlabel;
    if (rcode === 4 || rcode === 5 || rcode === 6) {
      $("#kilewsLiveResult").style.color = "var(--green)";
    } else if (rcode === 7) {
      $("#kilewsLiveResult").style.color = "var(--red)";
    } else {
      $("#kilewsLiveResult").style.color = "var(--muted)";
    }
  }
}

function renderVision(vision, alarm) {
  const panel = $(".camera-panel");
  const status = vision?.status || "WAIT";
  const cameraPanelTitle = document.querySelector(".camera-panel .panel-head h2");
  if (cameraPanelTitle) cameraPanelTitle.textContent = "O型圈视觉";

  if (panel) {
    panel.classList.remove("is-ok", "is-ng", "is-wait");
    panel.classList.add(status === "OK" ? "is-ok" : status === "NG" ? "is-ng" : "is-wait");
  }

  const detections = vision?.detections || [];
  const list = document.getElementById("visionDetections");
  if (!list) return;

  if (detections.length === 0) {
    list.innerHTML = '<span class="vision-empty">等待检测...</span>';
    return;
  }

  // Show ALL detections (sorted by confidence)
  var uniq = detections.sort(function(a, b) {
    return (b.confidence || 0) - (a.confidence || 0);
  });

  const colors = {
    NG: '#ff3333', O_Ring: '#33ff33', QR: '#ffff33', TXV: '#33ff33',
  };

  list.innerHTML = uniq.map(function(d) {
    var cls = d.class_name || '?';
    var conf = d.confidence != null ? (d.confidence * 100).toFixed(1) + '%' : '?';
    var color = colors[cls] || '#ccc';
    return '<div class="vision-detection-item">' +
      '<span class="vision-detection-dot" style=\"background:' + color + ';\"></span>' +
      '<span class="vision-detection-label">' + escapeHtml(cls) + '</span>' +
      '<span class="vision-detection-conf">' + conf + '</span>' +
      '</div>';
  }).join('');
}

function updateStepTrack(state) {
  const autoOrder = ["vision_wait_stable", "vision_check_cover", "plc_handshake", "tightening_wait", "tightening_eval", "pending_scan", "complete"];
  const manualOrder = ["vision", "preassemble", "tightening", "pending_scan", "complete"];
  const track = document.getElementById("stepTrack");
  if (!track) return;
  const spans = track.querySelectorAll("span");
  const firstStep = spans.length > 0 ? spans[0].dataset.step : null;
  const isAuto = firstStep === "vision_wait_stable";
  const order = isAuto ? autoOrder : manualOrder;
  const activeIndex = Math.max(0, order.indexOf(state));
  spans.forEach((node) => {
    const index = order.indexOf(node.dataset.step);
    node.classList.remove("active", "done");
    if (index === activeIndex) {
      node.classList.add("active");  // yellow = current step
    } else if (index >= 0 && index < activeIndex) {
      node.classList.add("done");    // green = completed
    }
  });
}

function plcReady(plc) {
  const connected = !!(plc && plc.last_seen && plc.last_seen !== "PLC disconnected" && !String(plc.last_seen).startsWith("Error:"));
  return (
    connected &&
    plc.auto_mode &&
    plc.estop_ok &&
    plc.safety_ok &&
    plc.clamp_ok &&
    plc.home_ok &&
    plc.part_present &&
    plc.plc_comm_allow &&
    !plc.plc_alarm &&
    !plc.plc_tightening_forbidden
  );
}

function plcAutoMode(plc) {
  if (!plc) return false;
  if (plc.auto_mode === true || plc.auto_mode === 1 || plc.auto_mode === "1") return true;
  const manualMode = plc.m_manual_mode;
  return manualMode === false || manualMode === 0 || manualMode === "0";
}

function renderPlc(plc) {
  const plcPanelTitle = document.querySelector(".plc-panel .panel-head h2");

  const mBits = [
    // PLC -> PC (M10.x, M11.x)
    ["m_manual_mode",          "M0.3 手动/自动"],
    ["m_estop",                "M0.4 急停"],
    ["m_plc_reset",            "M0.6 PLC复位"],
    ["m_plc_tightening_done",  "M10.2 拧紧完成"],
    // PC -> PLC outputs
    ["m_product_ready",        "M0.0 产品就绪"],
    ["m_tightening_ok",        "M0.1 拧紧合格"],
    ["m_scan_complete",        "M0.2 扫码完成"],
    ["m_disable_scan",         "M0.7 屏蔽扫码"],
    ["m_tightening_ng",        "M1.0 拧紧不合格"],
  ];
  var grid = document.getElementById("plcMBitsGrid");
  if (grid) {
    grid.innerHTML = mBits
      .map(function (item) {
        var key = item[0], label = item[1];
        var checked = plc[key] ? "checked" : "";
        return "<label>" + label + "<input type=\"checkbox\" disabled " + checked + "></label>";
      })
      .join("");
  }
}

function renderAutomation(snapshot) {
  var auto = snapshot.automation || {};
  var isAuto = auto.active === true;
  var plcAuto = plcAutoMode(snapshot.plc);  // M0.3=0 = auto
  var plcState = snapshot.plc || {};
  var st = snapshot.state;
  var resumableAutoStates = [
    "vision_wait_stable",
    "vision_check_cover",
    "plc_handshake",
    "tightening_wait",
    "tightening_eval",
    "pending_scan",
  ];
  var shouldResumeAutoCycle = plcAuto && !isAuto && resumableAutoStates.indexOf(st) >= 0;

  // Resume any in-flight auto cycle even if the settings toggle was switched off mid-process.
  if (shouldResumeAutoCycle || (plcAuto && !isAuto)) {
    setBadge("#autoBadge", "自动模式(启动中)", true);
    api("/api/automation/start", {}).catch(function() {});
    return;  // next poll will reflect new state
  }

  // Auto badge
  setBadge("#autoBadge", isAuto ? "\u81ea\u52a8\u8fd0\u884c" : "\u624b\u52a8\u6a21\u5f0f", isAuto);

  // Stage label
  var stageLabel = document.getElementById("autoStageLabel");
  if (stageLabel) {
    if (!isAuto) {
      stageLabel.textContent = "自动化未运行";
    } else {
      var stageMap = {
        "vision_wait_stable": "阶段 1/7: O型圈",
        "vision_check_cover": "阶段 2/7: 二维码",
        "plc_handshake": "阶段 3/7: 压紧",
        "tightening_wait": "阶段 4/7: 拧紧",
        "tightening_eval": "阶段 5/7: 判定",
        "pending_scan": "阶段 6/7: 扫码",
        "complete": "阶段 7/7: 完成",
      };
      stageLabel.textContent = stageMap[st] || st;
    }
  }

  // PLC connection badge
  var plcConn = !!(plcState.last_seen && plcState.last_seen !== "PLC disconnected");
  setBadge("#autoPlcBadge", plcConn ? "PLC: 在线" : "PLC: 离线", plcConn);

  // PLC connection text
  var plcConnText = document.getElementById("plcConnText");
  if (plcConnText) {
    plcConnText.textContent = plcConn ? "\u5df2\u8fde\u63a5" : "\u672a\u8fde\u63a5";
    plcConnText.style.color = plcConn ? "var(--green)" : "var(--red)";
  }

  // Stability indicator
  var stabProg = document.getElementById("stabilityProgress");
  var stabStatus = document.getElementById("stabilityStatusText");
  if (stabProg && stabStatus) {
    stabProg.style.display = isAuto ? "" : "none";
    stabStatus.style.display = isAuto ? "" : "none";
    if (isAuto) {
      var prog = auto.stability_progress || 0;
      var target = auto.stability_target || 2.0;
      stabProg.textContent = "\u7a33\u5b9a " + prog.toFixed(1) + "s / " + target.toFixed(1) + "s";
      var ss = auto.stability_status || "unstable";
      stabStatus.textContent = ss === "stable_ok" ? "\u2713 \u7a33\u5b9a" : ss === "wrong_count" ? "\u2717 \u6570\u91cf\u5f02\u5e38" : "\u68c0\u6d4b\u4e2d...";
      stabStatus.style.color = ss === "stable_ok" ? "var(--green)" : ss === "wrong_count" ? "var(--red)" : "var(--muted)";
      stabStatus.style.display = "";
    }
  }

  // Coverage indicator
  var covText = document.getElementById("coverageText");
  var covStatus = document.getElementById("coverageStatusText");
  if (covText && covStatus) {
    covText.style.display = isAuto ? "" : "none";
    covStatus.style.display = isAuto ? "" : "none";
    if (isAuto) {
      var ratios = auto.coverage_ratios || [];
      if (ratios.length > 0) {
        var ioaVals = ratios.map(function(r) { return (r.ioa * 100).toFixed(1) + "%"; }).join(", ");
        covText.textContent = "\u4e8c\u7ef4\u7801/\u8986\u76d6 " + ioaVals;
      } else {
        covText.textContent = "\u4e8c\u7ef4\u7801 --";
      }
      covText.style.display = "";
      var cs = auto.coverage_status || "waiting";
      covStatus.textContent = cs === "covered" || cs === "detected" ? "\u2713 \u5df2\u68c0\u6d4b" : cs === "plc_handshake" ? "\u2192 PLC" : cs === "plc_waiting" ? "PLC\u7b49\u5f85" : "\u68c0\u6d4b\u4e2d...";
      covStatus.style.color = cs === "covered" || cs === "detected" || cs === "plc_handshake" ? "var(--green)" : "var(--muted)";
      covStatus.style.display = "";
    }
  }

  // Toggle manual vision buttons
  var manualActions = document.getElementById("visionManualActions");
  if (manualActions) {
    manualActions.style.display = isAuto ? "none" : "";
  }
}

function renderBolts(bolts) {
  const tighteningPanelTitle = document.querySelector(".tightening-panel .panel-head h2");
  if (tighteningPanelTitle) tighteningPanelTitle.textContent = "奇力速拧紧";
  $("#boltCards").innerHTML = bolts
    .map((bolt) => {
      const torque = bolt.torque_nm;
      const angle = bolt.angle_deg;
      const torqueValue = torque === null || torque === undefined || torque === "" ? "" : asFixed(torque);
      const angleValue = angle === null || angle === undefined || angle === "" ? "" : asFixed(angle);
      return `
        <div class="bolt-card">
          <strong>螺栓 ${bolt.bolt_no}</strong>
          <label>扭矩 Nm<input id="bolt${bolt.bolt_no}Torque" type="number" step="0.01" value="${torqueValue}"></label>
          <label>角度 °<input id="bolt${bolt.bolt_no}Angle" type="number" step="0.01" value="${angleValue}"></label>
          <button data-tighten="${bolt.bolt_no}" class="${bolt.result === "OK" ? "secondary" : "primary"}">${bolt.result}</button>
        </div>
      `;
    })
    .join("");
  $$("[data-tighten]").forEach((button) => {
    button.addEventListener("click", async () => {
      const boltNo = Number(button.dataset.tighten);
      await runAction(async () => {
        await api("/api/tightening/simulate", {
          bolt_no: boltNo,
          torque_nm: Number($(`#bolt${boltNo}Torque`).value),
          angle_deg: Number($(`#bolt${boltNo}Angle`).value),
        });
      }, `\u87ba\u4e1d ${boltNo} \u62e7\u7d27\u6570\u636e\u5df2\u8bb0\u5f55`);
    });
  });
}

function renderRecent(records, stats) {
  $("#recentRecords").innerHTML = records
    .map(
      (row) => `
      <tr>
        <td style="white-space:nowrap;font-size:0.65rem;">${fmtTime(row.created_at)}</td>
        <td>${escapeHtml(row.internal_serial || "")}</td>
        <td>${escapeHtml(row.qr_code || "")}</td>
        <td>${escapeHtml(row.operator || row.operator_name || "")}</td>
        <td>${escapeHtml(row.product_model || "")}</td>
        <td>${renderImageLink(row.image_path)}</td>
        <td>${asFixed(row.bolt1_torque)}</td>
        <td>${asFixed(row.bolt1_angle)}</td>
        <td>${asFixed(row.bolt2_torque)}</td>
        <td>${asFixed(row.bolt2_angle)}</td>
        <td>${renderResultChip(row.final_result)}</td>
      </tr>
    `,
    )
    .join("");

  // Update stats
  if (stats) {
    $("#statTotal").textContent = stats.total || 0;
    $("#statOk").textContent = stats.product_ok != null ? stats.product_ok : "--";
    if (stats.product_model) {
      $("#statProduct").style.display = "";
      $("#statProductLabel").textContent = stats.product_model;
      $("#statProductTotal").textContent = stats.product_total || 0;
    }
  }
}

function renderRecordRows(records) {
  $("#recordRows").innerHTML = records
    .map(
      (row) => `
      <tr>
        <td style="white-space:nowrap;font-size:0.68rem;">${fmtTime(row.created_at)}</td>
        <td>${escapeHtml(row.internal_serial || "")}</td>
        <td>${escapeHtml(row.qr_code || "")}</td>
        <td>${escapeHtml(row.operator || row.operator_name || "")}</td>
        <td>${escapeHtml(row.product_model || "")}</td>
        <td>${renderImageLink(row.image_path)}</td>
        <td>${asFixed(row.bolt1_torque)}</td>
        <td>${asFixed(row.bolt1_angle)}</td>
        <td>${asFixed(row.bolt2_torque)}</td>
        <td>${asFixed(row.bolt2_angle)}</td>
        <td>${renderResultChip(row.final_result)}</td>
      </tr>
    `,
    )
    .join("");
}

function fmtTime(val) {
  if (!val) return "";
  var s = String(val).replace("T", " ");
  return s.length >= 16 ? s.slice(5, 16) : s;
}

function renderImageLink(path) {
  if (!path) return "--";
  return '<a href=\"/api/image?path=' + encodeURIComponent(path) + '\" target=\"_blank\" title=\"' + '查看图片' + '\">' + '图片' + '</a>';
}

function renderResultChip(val) {
  if (!val) return "--";
  var cls = val === "OK" ? "status-chip good" : val === "NG" ? "status-chip bad" : "status-chip warn";
  return `<span class="${cls}">${escapeHtml(val)}</span>`;
}

async function runAction(fn, okMessage) {
  try {
    await fn();
    await loadStatus();
    toast(okMessage);
  } catch (error) {
    toast(error.message);
  }
}

function bindEvents() {
  $$(".tab-btn").forEach((button) => {
    button.addEventListener("click", () => {
      $$(".tab-btn").forEach((item) => item.classList.remove("active"));
      $$(".tab-panel").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      $(`#${button.dataset.tab}`).classList.add("active");
      if (button.dataset.tab === "production" && window._layoutManager) {
        setTimeout(() => window._layoutManager.applyLayout(), 50);
      }
      if (button.dataset.tab === "production" || button.dataset.tab === "datasets") {
        applyDatasetsTransform();
      }
      if (button.dataset.tab === "production" || button.dataset.tab === "datasets") {
        refreshCameraFeeds(true);
      }
    });
  });

  $$(".settings-subtab").forEach((button) => {
    button.addEventListener("click", () => {
      $$(".settings-subtab").forEach((item) => item.classList.remove("active"));
      $$(".settings-subpanel").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      $(`#settings-${button.dataset.settingsTab}`).classList.add("active");
    });
  });



  $("#scanBtn").addEventListener("click", async () => {
    try {
      await submitQrBinding($("#qrInput").value, "\u4e8c\u7ef4\u7801\u7ed1\u5b9a\u5b8c\u6210");
    } catch (e) {
      toast(e.message);
    }
  });

  $("#skipScanBtn").addEventListener("click", () =>
    runAction(() => api("/api/scan/skip", {}), "\u5df2\u8df3\u8fc7\u626b\u7801"),
  );

  $("#reworkBtn").addEventListener("click", () =>
    runAction(() => api("/api/rework", { choice: "\u8fd4\u4fee" }), "PLC \u8fd4\u4fee\u9009\u62e9\u5df2\u8bb0\u5f55"),
  );

  $("#refreshBtn").addEventListener("click", loadStatus);

  $("#productSelect").addEventListener("change", async () => {
    const product = (settings.products || []).find((item) => item.product_model === $("#productSelect").value);
    if (!product) return;
    settings.station.active_product_model = product.product_model;
    settings.station.active_recipe_no = product.recipe_no;
    window.__selectedProduct = product.product_model;
    renderProductSummary(statusSnapshot);

    try {
      await api("/api/settings", {
        station: {
          active_product_model: product.product_model,
          active_recipe_no: product.recipe_no,
        },
      });
    } catch (e) {
      console.error("Persist active product failed:", e);
    }

    try {
      await api("/api/kilews/write-params", { product_model: product.product_model });
    } catch (e) {
      console.error("Write Kilews params failed:", e);
    }
  });

  $("#addProductBtn").addEventListener("click", () => {
    settings.products = collectProductRows();
    if (settings.products.length >= MAX_PRODUCTS) {
      toast("\u4ea7\u54c1\u8bbe\u7f6e\u6700\u591a 255 \u884c");
      return;
    }
    settings.products.push(productTemplate(settings.products.length));
    renderProductTable();
    toast("\u5df2\u589e\u52a0\u4e00\u884c\u4ea7\u54c1");
  });

  $("#addPersonBtn").addEventListener("click", () => {
    settings.personnel = collectPersonRows();
    if (settings.personnel.length >= MAX_PERSONNEL) {
      toast("\u4eba\u5458\u6700\u591a 255 \u4e2a");
      return;
    }
    settings.personnel.push(personTemplate(settings.personnel.length));
    renderPersonTable();
    toast("\u5df2\u589e\u52a0\u4e00\u4e2a\u4eba\u5458");
  });

  $("#saveSettingsBtn").addEventListener("click", async () => {
    const products = collectProductRows();
    const personnel = collectPersonRows();
    const selectedProduct = products.find((product) => product.product_model === $("#productSelect").value) || products[0];
    const defaultPerson = personnel.find((person) => person.employee_id === $("#operatorInput").value) || personnel[0];
    const patch = {
      station: {
        station_id: $("#setStationId").value,
        line_name: $("#setLineName").value,
        active_product_model: selectedProduct.product_model,
        active_recipe_no: Number(selectedProduct.recipe_no),
      },
      auth: {
        default_operator: defaultPerson.employee_id,
        default_shift: defaultPerson.shift,
      },
      vision: {
        model_path: $("#setModelPath").value,
        model_version: $("#setModelPath").value.split(/[\\/]/).pop() || "yolo26s.pt",
        camera_ip: $("#setCameraIp").value,
        confidence_threshold: Number($("#setConfidenceThreshold").value),
        inference_enabled: $("#setInferenceEnabled").checked,
        inference_interval_ms: Number($("#setInferenceIntervalMs").value),
        auto_capture_enabled: $("#setAutoCaptureEnabled").checked,
      },
      plc: {
        enabled: $("#setPlcEnabled").checked,
        ip: $("#setPlcIp").value,
        port: Number($("#setPlcPort").value),
        rack: Number($("#setPlcRack").value),
        slot: Number($("#setPlcSlot").value),
        timeout: Number($("#setPlcTimeout").value),
        reconnect_interval_s: Number($("#setPlcReconnect").value),
        auto_connect: $("#setPlcAutoConnect").checked,
        heartbeat_timeout_ms: Number($("#setPlcTimeout").value) * 1000,
      },
      automation: {
        enabled: $("#setAutomationEnabled").checked,
        stability_duration_s: Number($("#setStabilityDuration").value),
        stability_position_threshold_px: Number($("#setStabilityThreshold").value),
        coverage_ratio_threshold: Number($("#setCoverageThreshold").value),
        tightening_poll_interval_ms: Number($("#setTighteningPoll").value),
        tightening_timeout_s: Number($("#setTighteningTimeout").value),
      },
      kilews: {
        ip: $("#setKilewsIp").value,
        port: Number($("#setKilewsPort").value),
        unit_id: Number($("#setKilewsUnitId").value),
        enabled: $("#setKilewsEnabled").checked,
        auto_connect: $("#setKilewsAutoConnect").checked,
        speed_rpm: Number($("#setKilewsSpeed").value),
      },
      scanner: {
        mode: $("#setScannerMode").value,
        port: Number($("#setScannerPort").value),
      },
      data: {
        export_root: $("#setExportRoot").value,
        image_root: $("#setImageRoot").value,
        dataset_root: $("#setDatasetRoot").value,
      },
      products,
      personnel,
    };
    await runAction(async () => {
      settings = await api("/api/settings", patch);
      renderSettings();
      renderProductOptions();
    }, "\u8bbe\u7f6e\u5df2\u4fdd\u5b58");
  });

  $("#queryRecordsBtn").addEventListener("click", async () => {
    try {
      const keyword = encodeURIComponent($("#recordKeyword").value);
      const status = encodeURIComponent($("#recordStatus").value);
      const payload = await api(`/api/records?keyword=${keyword}&status=${status}&limit=200`);
      renderRecordRows(payload.records);
      toast("鏌ヨ瀹屾垚");
    } catch (error) {
      toast(error.message);
    }
  });

  $("#kilewsConnectBtn").addEventListener("click", async () => {
    try {
      const payload = await api("/api/kilews/connect", {});
      $("#kilewsConnMsg").textContent = payload.connected ? "\u5df2\u8fde\u63a5" : "\u8fde\u63a5\u5931\u8d25";
      $("#kilewsConnMsg").style.color = payload.connected ? "var(--green)" : "var(--red)";
    } catch (e) { toast(e.message); }
  });

  $("#kilewsDisconnectBtn").addEventListener("click", async () => {
    try {
      await api("/api/kilews/disconnect", {});
      $("#kilewsConnMsg").textContent = "宸叉柇寮€";
      $("#kilewsConnMsg").style.color = "var(--muted)";
    } catch (e) { toast(e.message); }
  });

  $("#kilewsWriteBtn").addEventListener("click", async () => {
    try {
      const product = (settings.products || []).find(
        p => p.product_model === settings.station.active_product_model
      );
      if (!product) { toast("鏈€夋嫨浜у搧"); return; }
      const result = await api("/api/kilews/write-all", {
        torque_target_nm: product.torque_target_nm,
        torque_min_nm: product.torque_min_nm,
        torque_max_nm: product.torque_max_nm,
        angle_target_deg: product.angle_target_deg,
        angle_min_deg: product.angle_min_deg,
        angle_max_deg: product.angle_max_deg,
        speed_rpm: settings.kilews.speed_rpm,
        target_type: 2,
      });
      if (result.ok) {
        $("#kilewsConnMsg").textContent = `鍐欏叆鎴愬姛 (${result.written} 姝?`;
        $("#kilewsConnMsg").style.color = "var(--green)";
        toast("鍙傛暟宸插啓鍏ユ帶鍒跺櫒");
      } else {
        $("#kilewsConnMsg").textContent = "鍐欏叆澶辫触: " + (result.error || "鏈煡");
        $("#kilewsConnMsg").style.color = "var(--red)";
        toast("鍐欏叆澶辫触锛岃鏌ョ湅璇︽儏");
      }
    } catch (e) { toast(e.message); }
  });

  $("#exportDailyBtn").addEventListener("click", async () => {
    await runAction(async () => {
      const payload = await api("/api/export/daily", {});
      $("#exportPath").textContent = `宸插鍑猴細${payload.export_path}`;
    }, "\u65e5\u62a5 Excel \u5df2\u5bfc\u51fa");
  });

  $("#captureBtn").addEventListener("click", async () => {
    await runAction(async () => {
      const payload = await api("/api/image/capture", {
        product_model: $("#productSelect").value,
        transform: datasetsTransform,
      });
      $("#capturePath").textContent = `宸蹭繚瀛橈細${payload.image_path}`;
    }, "\u6293\u62cd\u56fe\u7247\u5df2\u4fdd\u5b58");
  });

  $("#exportDatasetBtn").addEventListener("click", async () => {
    await runAction(async () => {
      const payload = await api("/api/datasets/export", { product_model: $("#productSelect").value });
      $("#datasetPath").textContent = `宸茬敓鎴愶細${payload.dataset_path}`;
    }, "\u672c\u5730 datasets \u5df2\u751f\u6210");
  });

  // ---- Datasets page controls ----

  // Save camera settings
  document.getElementById("saveCameraSettingsBtn")?.addEventListener("click", async () => {
    // Save exposure to server
    const slider = document.getElementById("exposureSlider");
    if (slider) {
      try {
        await api("/api/camera/exposure", { exposure_us: Number(slider.value) });
      } catch (e) {
        // ignore error
      }
    }
    // Save transform to localStorage
    saveCameraSettings();
    const label = document.getElementById("cameraSettingsSaved");
    if (label) {
      label.style.display = "";
      setTimeout(() => { label.style.display = "none"; }, 2000);
    }
    toast("\u76f8\u673a\u8bbe\u7f6e\u5df2\u4fdd\u5b58");
  });

  // Camera connect / disconnect
  document.getElementById("cameraConnectBtn")?.addEventListener("click", async () => {
    try {
      const payload = await api("/api/camera/connect", {});
      if (payload.ok && !payload.is_mock) {
        const badge = document.getElementById("captureCameraBadge");
        if (badge) { badge.textContent = "实时画面"; badge.className = "badge good"; }
        toast("\u76f8\u673a\u5df2\u542f\u52a8");
      } else {
        const badge = document.getElementById("captureCameraBadge");
        if (badge) { badge.textContent = "相机未连接"; badge.className = "badge bad"; }
        toast(payload.error || "相机启动失败");
      }
    } catch (e) {
      toast(`相机启动失败: ${e.message}`);
    }
  });

  document.getElementById("cameraDisconnectBtn")?.addEventListener("click", async () => {
    try {
      await api("/api/camera/disconnect", {});
      const badge = document.getElementById("captureCameraBadge");
      if (badge) { badge.textContent = "相机已断开"; badge.className = "badge bad"; }
      toast("相机已断开");
    } catch (e) {
      toast(`断开失败: ${e.message}`);
    }
  });

  // Exposure slider
  const exposureSlider = document.getElementById("exposureSlider");
  if (exposureSlider) {
    exposureSlider.addEventListener("input", () => {
      const label = document.getElementById("exposureValue");
      if (label) label.textContent = `${exposureSlider.value} us`;
    });
    let exposureTimer;
    exposureSlider.addEventListener("change", () => {
      clearTimeout(exposureTimer);
      exposureTimer = setTimeout(() => {
        setCameraExposure(Number(exposureSlider.value));
      }, 150);
    });
  }

  // Exposure reset
  document.getElementById("exposureResetBtn")?.addEventListener("click", () => {
    const slider = document.getElementById("exposureSlider");
    const label = document.getElementById("exposureValue");
    if (slider) slider.value = EXPOSURE_DEFAULT;
    if (label) label.textContent = `${EXPOSURE_DEFAULT} us`;
    setCameraExposure(EXPOSURE_DEFAULT);
  });

  // Zoom
  document.getElementById("zoomInBtn")?.addEventListener("click", () => {
    datasetsTransform.zoom = Math.min(ZOOM_MAX, datasetsTransform.zoom + ZOOM_STEP);
    applyDatasetsTransform();
  });
  document.getElementById("zoomOutBtn")?.addEventListener("click", () => {
    datasetsTransform.zoom = Math.max(ZOOM_MIN, datasetsTransform.zoom - ZOOM_STEP);
    applyDatasetsTransform();
  });
  document.getElementById("zoomResetBtn")?.addEventListener("click", () => {
    datasetsTransform.zoom = 1.0;
    applyDatasetsTransform();
  });

  // Rotate
  document.getElementById("rotateLeftBtn")?.addEventListener("click", () => {
    datasetsTransform.rotate = (datasetsTransform.rotate - 90) % 360;
    applyDatasetsTransform();
  });
  document.getElementById("rotateRightBtn")?.addEventListener("click", () => {
    datasetsTransform.rotate = (datasetsTransform.rotate + 90) % 360;
    applyDatasetsTransform();
  });
  document.getElementById("rotateResetBtn")?.addEventListener("click", () => {
    datasetsTransform.rotate = 0;
    applyDatasetsTransform();
  });

  // Pan
  document.getElementById("panUpBtn")?.addEventListener("click", () => {
    datasetsTransform.panY += PAN_STEP;
    applyDatasetsTransform();
  });
  document.getElementById("panDownBtn")?.addEventListener("click", () => {
    datasetsTransform.panY -= PAN_STEP;
    applyDatasetsTransform();
  });
  document.getElementById("panLeftBtn")?.addEventListener("click", () => {
    datasetsTransform.panX += PAN_STEP;
    applyDatasetsTransform();
  });
  document.getElementById("panRightBtn")?.addEventListener("click", () => {
    datasetsTransform.panX -= PAN_STEP;
    applyDatasetsTransform();
  });
  document.getElementById("panResetBtn")?.addEventListener("click", () => {
    datasetsTransform.panX = 0;
    datasetsTransform.panY = 0;
    applyDatasetsTransform();
  });
}

function tickClock() {
  $("#clock").textContent = new Date().toLocaleTimeString("zh-CN", { hour12: false });
}

async function boot() {
  applyProductGridWidths();
  bindEvents();
  tickClock();
  setInterval(tickClock, 1000);

  const board = document.getElementById("production");
  if (board) {
    window._layoutManager = new LayoutManager(board);
    window._layoutManager.init();
  }

  // Shared camera feed polling: only one visible panel refreshes at a time.
  startCameraFeedPolling();
  /* legacy polling
  setInterval(() => {
    const img = document.getElementById('cameraFeed');
    if (img) {
      img.onerror = () => {
        const status = document.getElementById('cameraStatus');
        if (status) status.textContent = '鐩告満鏈繛鎺?;
      };
      img.onload = () => {
        const status = document.getElementById('cameraStatus');
        if (status) status.textContent = '瀹炴椂鐢婚潰';
        // Re-apply saved transform after each frame load
        applyDatasetsTransform();
      };
      img.src = '/api/vision/latest-frame?t=' + Date.now();
    }
  }, 200);
  */

  // Datasets page camera: auto-connect + restore settings.
  setTimeout(() => autoConnectAndRestore(), 500);

function checkConnections(snapshot) {
  var errors = [];
  // 1. Camera
  var cameraOk = snapshot.vision && snapshot.vision.status !== "WAIT";
  if (!cameraOk) errors.push("相机 192.168.0.101 未连接");
  // 2. PLC
  var plcOk = snapshot.plc && snapshot.plc.auto_mode !== undefined;
  if (!plcOk) errors.push("PLC 192.168.0.10 未连接");
  // 3. Kilews
  var kwOk = snapshot.kilews && snapshot.kilews.connected;
  if (!kwOk) errors.push("拧紧枪 192.168.0.105 未连接");
  // 4. Scanner
  var scannerOk = snapshot.scanner_connected !== false && lastQr !== undefined;
  // Scanner is harder to check via status - use badge color

  if (errors.length > 0) {
    setBadge("#connectionBadge", errors[0], false);
    toast("硬件连接异常: " + errors.join(", "));
  } else {
    setBadge("#connectionBadge", "全部在线", true);
  }
}

  await loadSettings();
  await loadStatus();

  // Connection check: verify all 4 hardware devices
  checkConnections(statusSnapshot);

  // Auto-login and auto-start production (after settings loaded)
  autoLoginAndStart();
  const payload = await api("/api/records?limit=200");
  renderRecordRows(payload.records);
  startStatusPolling();
  return;
  setInterval(() => loadStatus().catch(() => setBadge("#connectionBadge", "连接异常", false)), 1500);
}

// Graceful shutdown on browser close
window.addEventListener("beforeunload", () => {
  releaseCameraPollLease();
  navigator.sendBeacon("/api/shutdown");
});

boot().catch((error) => toast(error.message));
