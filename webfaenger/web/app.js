"use strict";
// Webfänger – Oberfläche. Python erledigt Suche, Laden und Speichern
// (window.pywebview.api) und meldet Fortschritt über poll().

const $ = (id) => document.getElementById(id);
const plural = (n, one, many) => `${n.toLocaleString("de-DE")} ${n === 1 ? one : many}`;

function formatBytes(n) {
  if (n < 1024 * 1024) return `${Math.max(1, Math.round(n / 1024)).toLocaleString("de-DE")} KB`;
  return `${(n / 1048576).toLocaleString("de-DE", { maximumFractionDigits: 1 })} MB`;
}

function debounce(fn, ms) {
  let timer;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); };
}

const state = {
  api: null,
  scanId: 0,
  host: "",
  phase: "idle",            // idle, scanning, loading, ready, saving
  items: new Map(),         // id -> {id, name, url, imgType, size, w, h, tile}
  order: [],
  selected: new Set(),
  shownTypes: new Set(),
  minKb: 10,
  problems: [],
  duplicates: 0,
  viewerId: null,
};

// ------------------------------------------------------------------ Start

window.addEventListener("pywebviewready", init);

async function init() {
  state.api = window.pywebview.api;
  const { settings, collisions, theme } = await state.api.init();
  if (theme) document.documentElement.dataset.theme = theme;

  state.shownTypes = new Set(settings.types);
  state.minKb = settings.min_kb;
  $("minKb").value = settings.min_kb;
  $("folder").value = settings.folder;
  $("subfolder").checked = settings.subfolder_per_search;
  $("prefix").value = settings.prefix;
  $("pattern").value = settings.pattern;
  for (const [value, label] of collisions) $("collision").add(new Option(label, value));
  $("collision").value = settings.collision;
  const mode = document.querySelector(`input[name="naming"][value="${settings.naming_mode}"]`);
  (mode || document.querySelector('input[name="naming"]')).checked = true;

  bindEvents();
  updateNamingRows();
  updateNamePreview();
  updateFolderHint();
  render();
  poll();
  $("url").focus();
}

async function poll() {
  try {
    for (const event of await state.api.poll()) handle(event);
  } finally {
    setTimeout(poll, 150);
  }
}

// ------------------------------------------------------------------ Ereignisse aus Python

function handle(e) {
  if (e.scanId !== undefined && e.scanId !== state.scanId) return;
  switch (e.type) {
    case "scan_done":
      state.host = e.host;
      if (e.count === 0) {
        setPhase("idle");
        setHeadline(`Keine Bilder gefunden auf ${e.host}`,
          "Möglicherweise lädt die Webseite ihre Bilder erst per JavaScript nach. " +
          "Das unterstützt Webfänger noch nicht.");
      } else {
        setPhase("loading");
        setHeadline(`Vorschau wird geladen …`, `${plural(e.count, "Bild-Adresse", "Bild-Adressen")} auf ${e.host}`);
      }
      break;
    case "item":
      $("progressBar").style.width = `${(e.done / e.total) * 100}%`;
      if (e.status === "ok") addTile(e);
      else if (e.status === "duplicate") state.duplicates++;
      else if (e.status === "error" || e.status === "notimage") {
        state.problems.push(`${e.url} (${e.error || "kein Bild"})`);
      }
      scheduleRender();
      break;
    case "fetch_done":
      setPhase("ready");
      if (e.cancelled) $("status").textContent = "Laden abgebrochen. Die bisher geladenen Bilder bleiben verfügbar.";
      render();
      break;
    case "scan_error":
      setPhase("idle");
      setHeadline("Webseite konnte nicht geladen werden", e.message, true);
      break;
    case "save_progress":
      $("status").textContent = `Speichere ${e.done} von ${e.total} …`;
      break;
    case "save_done":
      setPhase("ready");
      $("status").textContent = e.summary.replace("\n", " · ");
      $("openBtn").hidden = e.saved === 0;
      if (e.failed.length) state.problems.push(...e.failed);
      updateFolderHint();
      render();
      break;
    case "save_error":
      setPhase("ready");
      $("status").textContent = e.message;
      break;
  }
}

// ------------------------------------------------------------------ Aktionen

async function startScan(event) {
  event?.preventDefault();
  if (state.phase === "scanning" || state.phase === "loading" || state.phase === "saving") return;
  $("urlError").textContent = "";
  const result = await state.api.scan($("url").value);
  if (result.error) {
    $("urlError").textContent = result.error;
    $("url").focus();
    return;
  }
  state.scanId = result.scanId;
  state.items.clear();
  state.order = [];
  state.selected.clear();
  state.problems = [];
  state.duplicates = 0;
  $("grid").replaceChildren();
  $("openBtn").hidden = true;
  $("status").textContent = "";
  setHeadline("Webseite wird durchsucht …", result.url);
  setPhase("scanning");
  updateFolderHint();
}

async function save() {
  const ids = visibleIds().filter((id) => state.selected.has(id));
  const result = await state.api.save({
    ids,
    folder: $("folder").value,
    subfolder: $("subfolder").checked,
    naming: namingSettings(),
  });
  if (result.error) {
    $("status").textContent = result.error;
    return;
  }
  setPhase("saving");
  $("status").textContent = `Speichere nach ${result.folder} …`;
}

function namingSettings() {
  return {
    mode: document.querySelector('input[name="naming"]:checked').value,
    prefix: $("prefix").value,
    pattern: $("pattern").value,
    collision: $("collision").value,
  };
}

const persist = debounce(() => {
  const naming = namingSettings();
  const minKb = parseInt($("minKb").value, 10);
  state.api.save_settings({
    folder: $("folder").value.trim(),
    subfolder_per_search: $("subfolder").checked,
    types: [...state.shownTypes].sort(),
    min_kb: Number.isFinite(minKb) && minKb >= 0 ? minKb : 10,
    naming_mode: naming.mode,
    prefix: naming.prefix,
    pattern: naming.pattern,
    collision: naming.collision,
  });
}, 400);

const updateNamePreview = debounce(async () => {
  const result = await state.api.preview_name(namingSettings());
  const preview = $("namePreview");
  preview.classList.toggle("invalid", Boolean(result.error));
  preview.textContent = result.error ? `Muster ungültig: ${result.error}` : `Beispiel: ${result.name}`;
}, 120);

const updateFolderHint = debounce(async () => {
  const hint = $("subfolderName");
  if (!$("subfolder").checked) { hint.textContent = ""; return; }
  const { name } = await state.api.target_folder($("folder").value, true);
  hint.textContent = name ? `→ ${name}` : "benannt nach der Webseite, z. B. „bildde“";
}, 120);

function updateNamingRows() {
  const mode = namingSettings().mode;
  $("prefixRow").hidden = mode !== "numbered";
  $("patternRow").hidden = mode !== "pattern";
}

// ------------------------------------------------------------------ Vorschau-Raster

function addTile(e) {
  const tile = $("tileTemplate").content.firstElementChild.cloneNode(true);
  const item = { id: e.id, name: e.name, url: e.url, imgType: e.imgType, size: e.size, w: 0, h: 0, tile };
  const img = tile.querySelector("img");
  img.src = `img/${e.scanId}/${e.id}`;
  img.alt = e.name;
  img.addEventListener("load", () => {
    item.w = img.naturalWidth;
    item.h = img.naturalHeight;
    updateTileInfo(item);
  }, { once: true });
  tile.dataset.id = e.id;
  tile.title = e.url;
  tile.querySelector(".name").textContent = e.name;
  updateTileInfo(item);

  state.items.set(e.id, item);
  state.order.push(e.id);
  state.selected.add(e.id);
  $("grid").append(tile);
}

function updateTileInfo(item) {
  const dims = item.w && item.imgType !== "svg" ? `${item.w}×${item.h} · ` : "";
  item.tile.querySelector(".info").textContent = `${dims}${formatBytes(item.size)} · ${item.imgType.toUpperCase()}`;
}

function isVisible(item) {
  return state.shownTypes.has(item.imgType) && item.size >= state.minKb * 1024;
}

function visibleIds() {
  return state.order.filter((id) => isVisible(state.items.get(id)));
}

function toggle(id, force) {
  const on = force ?? !state.selected.has(id);
  if (on) state.selected.add(id); else state.selected.delete(id);
  render();
}

let renderQueued = false;
function scheduleRender() {
  if (renderQueued) return;
  renderQueued = true;
  requestAnimationFrame(() => { renderQueued = false; render(); });
}

function render() {
  let shown = 0, chosen = 0, bytes = 0;
  const typeCounts = new Map();
  for (const id of state.order) {
    const item = state.items.get(id);
    typeCounts.set(item.imgType, (typeCounts.get(item.imgType) || 0) + 1);
    const visible = isVisible(item);
    const selected = state.selected.has(id);
    item.tile.hidden = !visible;
    item.tile.setAttribute("aria-checked", String(selected));
    if (visible) {
      shown++;
      if (selected) { chosen++; bytes += item.size; }
    }
  }
  renderChips(typeCounts);

  const total = state.order.length;
  $("tools").hidden = total === 0;
  $("empty").hidden = total > 0;
  if (total && (state.phase === "ready" || state.phase === "loading" || state.phase === "saving")) {
    const hidden = total - shown;
    setHeadline(state.phase === "loading" ? `${plural(total, "Bild", "Bilder")} geladen …`
                                          : `${plural(total, "Bild", "Bilder")} auf ${state.host}`,
      `${chosen.toLocaleString("de-DE")} von ${shown.toLocaleString("de-DE")} ausgewählt` +
      (chosen ? ` · ${formatBytes(bytes)}` : "") +
      (hidden ? ` · ${hidden.toLocaleString("de-DE")} durch Filter ausgeblendet` : ""));
  }

  const saveBtn = $("saveBtn");
  saveBtn.textContent = chosen ? `${plural(chosen, "Bild", "Bilder")} speichern` : "Bilder speichern";
  saveBtn.disabled = chosen === 0 || state.phase !== "ready";

  const problems = state.problems.length;
  $("problems").hidden = problems + state.duplicates === 0;
  $("problemsSummary").textContent = [
    state.duplicates ? `${plural(state.duplicates, "Duplikat", "Duplikate")} entfernt` : "",
    problems ? `${plural(problems, "Adresse", "Adressen")} nicht ladbar` : "",
  ].filter(Boolean).join(" · ");
  const list = $("problemList");
  if (list.childElementCount !== problems) {
    list.replaceChildren(...state.problems.map((text) => {
      const li = document.createElement("li");
      li.textContent = text;
      return li;
    }));
  }
}

function renderChips(typeCounts) {
  const chips = $("typeChips");
  const types = [...typeCounts.keys()].sort();
  if (chips.dataset.types !== types.join(",")) {
    chips.dataset.types = types.join(",");
    chips.replaceChildren(...types.map((type) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip";
      chip.dataset.type = type;
      chip.append(type.toUpperCase());
      const count = document.createElement("span");
      count.className = "count";
      chip.append(count);
      chip.addEventListener("click", () => {
        if (state.shownTypes.has(type)) state.shownTypes.delete(type); else state.shownTypes.add(type);
        persist();
        render();
      });
      return chip;
    }));
  }
  for (const chip of chips.children) {
    chip.setAttribute("aria-pressed", String(state.shownTypes.has(chip.dataset.type)));
    chip.querySelector(".count").textContent = typeCounts.get(chip.dataset.type);
  }
}

// ------------------------------------------------------------------ Zustand und Anzeige

function setPhase(phase) {
  state.phase = phase;
  const busy = phase === "scanning" || phase === "loading" || phase === "saving";
  $("searchBtn").disabled = busy;
  $("searchBtn").textContent = phase === "scanning" ? "Suche läuft …" : "Bilder suchen";
  $("url").disabled = busy;
  $("cancelBtn").hidden = !(phase === "scanning" || phase === "loading");
  $("progress").hidden = !(phase === "scanning" || phase === "loading");
  $("progress").classList.toggle("indeterminate", phase === "scanning");
  if (phase === "scanning") $("progressBar").style.width = "";
  render();
}

function setHeadline(title, subline, failed = false) {
  $("headline").textContent = title;
  $("subline").textContent = subline || "";
  document.querySelector(".summary").classList.toggle("failed", failed);
}

// ------------------------------------------------------------------ Bildansicht

function openViewer(id) {
  state.viewerId = id;
  showViewerItem();
  if (!$("viewer").open) $("viewer").showModal();
}

function showViewerItem() {
  const item = state.items.get(state.viewerId);
  if (!item) return;
  $("viewerImg").src = item.tile.querySelector("img").src;
  $("viewerImg").alt = item.name;
  $("viewerName").textContent = item.name;
  const dims = item.w && item.imgType !== "svg" ? `${item.w} × ${item.h} Pixel · ` : "";
  $("viewerMeta").textContent = `${dims}${formatBytes(item.size)} · ${item.imgType.toUpperCase()}`;
  $("viewerSelect").checked = state.selected.has(item.id);
}

function stepViewer(delta) {
  const ids = visibleIds();
  const index = ids.indexOf(state.viewerId);
  if (index < 0 || !ids.length) return;
  state.viewerId = ids[(index + delta + ids.length) % ids.length];
  showViewerItem();
}

// ------------------------------------------------------------------ Bedienung

function bindEvents() {
  $("searchForm").addEventListener("submit", startScan);
  $("url").addEventListener("input", () => { $("urlError").textContent = ""; });
  $("saveBtn").addEventListener("click", save);
  $("cancelBtn").addEventListener("click", () => state.api.cancel());
  $("openBtn").addEventListener("click", async () => {
    const result = await state.api.open_folder();
    if (result.error) $("status").textContent = result.error;
  });
  $("browseBtn").addEventListener("click", async () => {
    const chosen = await state.api.choose_folder($("folder").value);
    if (chosen) {
      $("folder").value = chosen;
      persist();
      updateFolderHint();
    }
  });
  $("folder").addEventListener("input", () => { persist(); updateFolderHint(); });
  $("subfolder").addEventListener("change", () => { persist(); updateFolderHint(); });
  $("minKb").addEventListener("input", () => {
    const value = parseInt($("minKb").value, 10);
    state.minKb = Number.isFinite(value) && value >= 0 ? value : 0;
    persist();
    render();
  });
  $("selectAll").addEventListener("click", () => { visibleIds().forEach((id) => state.selected.add(id)); render(); });
  $("selectNone").addEventListener("click", () => { visibleIds().forEach((id) => state.selected.delete(id)); render(); });

  const grid = $("grid");
  grid.addEventListener("click", (event) => {
    const tile = event.target.closest(".tile");
    if (!tile) return;
    const id = Number(tile.dataset.id);
    if (event.target.closest(".zoom")) openViewer(id); else toggle(id);
  });
  grid.addEventListener("dblclick", (event) => {
    const tile = event.target.closest(".tile");
    if (tile && !event.target.closest(".zoom")) { toggle(Number(tile.dataset.id)); openViewer(Number(tile.dataset.id)); }
  });
  grid.addEventListener("keydown", (event) => {
    const tile = event.target.closest(".tile");
    if (!tile) return;
    if (event.key === " ") { event.preventDefault(); toggle(Number(tile.dataset.id)); }
    if (event.key === "Enter") { event.preventDefault(); openViewer(Number(tile.dataset.id)); }
  });

  // Einstellungen
  $("settingsBtn").addEventListener("click", () => $("settings").showModal());
  document.querySelectorAll('input[name="naming"]').forEach((radio) => radio.addEventListener("change", () => {
    updateNamingRows(); updateNamePreview(); persist();
  }));
  for (const id of ["prefix", "pattern"]) {
    $(id).addEventListener("input", () => { updateNamePreview(); persist(); });
  }
  $("collision").addEventListener("change", persist);

  // Dialoge: Schließen-Knöpfe und Klick auf den Hintergrund
  for (const dialog of [$("settings"), $("viewer")]) {
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog || event.target.closest("[data-close]")) dialog.close();
    });
  }
  $("prevBtn").addEventListener("click", () => stepViewer(-1));
  $("nextBtn").addEventListener("click", () => stepViewer(1));
  $("viewerSelect").addEventListener("change", (event) => toggle(state.viewerId, event.target.checked));
  $("viewer").addEventListener("keydown", (event) => {
    if (event.key === "ArrowLeft") stepViewer(-1);
    if (event.key === "ArrowRight") stepViewer(1);
    if (event.key === " " && event.target.tagName !== "INPUT") {
      event.preventDefault();
      toggle(state.viewerId);
      $("viewerSelect").checked = state.selected.has(state.viewerId);
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !document.querySelector("dialog[open]") &&
        (state.phase === "scanning" || state.phase === "loading")) {
      state.api.cancel();
    }
  });
}
