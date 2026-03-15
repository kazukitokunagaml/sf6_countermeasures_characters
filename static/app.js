let templateSignature = "";
let loadedConfig = null;

function byId(id) {
  return document.getElementById(id);
}

function formatTimestamp(unixTime) {
  if (!unixTime) {
    return "-";
  }
  return new Date(unixTime * 1000).toLocaleString("ja-JP", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function summarizeTemplates(groups) {
  const total = groups.reduce((sum, group) => sum + group.count, 0);
  return `${groups.length}キャラ / ${total}枚`;
}

function summarizeRegions(regions) {
  return `${regions.length} phase`;
}

function renderNotes(state) {
  const notes = byId("notes");
  notes.innerHTML = "";
  for (const note of state.notes || []) {
    const item = document.createElement("li");
    item.textContent = note;
    notes.appendChild(item);
  }
}

function renderDebugImages(images) {
  const root = byId("debug-images");
  root.innerHTML = "";
  for (const [label, path] of Object.entries(images || {})) {
    const card = document.createElement("div");
    card.className = "debug-image-card";
    card.innerHTML = `<div class="label">${label}</div><img src="${path}?t=${Date.now()}" alt="${label}">`;
    root.appendChild(card);
  }
}

async function refresh() {
  const response = await fetch("/state", { cache: "no-store" });
  const state = await response.json();
  byId("self-character").textContent = state.self_character || "-";
  byId("opponent").textContent = state.opponent || "認識待ち";
  byId("confidence").textContent = (state.confidence ?? 0).toFixed(3);
  byId("phase").textContent = state.phase || "-";
  byId("status").textContent = state.status || "";
  renderNotes(state);

  const debug = state.debug || {};
  const ocr = debug.ocr || {};
  byId("ocr-debug").textContent = JSON.stringify(
    {
      available: ocr.available,
      text: ocr.text || "",
      reason: ocr.reason || "",
      matches: ocr.matches || {},
    },
    null,
    2,
  );
  byId("candidate-debug").textContent = JSON.stringify(debug.top_candidates || [], null, 2);
  byId("region-debug").textContent = JSON.stringify(debug.regions || [], null, 2);
  renderDebugImages(debug.images || {});
}

function buildRegionRow(region, index) {
  const row = document.createElement("section");
  row.className = "region-card";
  row.innerHTML = `
    <div class="region-head">
      <input class="region-name" data-key="name" value="${region.name || `PHASE ${index + 1}`}">
      <div class="inline-actions">
        <label class="checkbox mini"><input data-key="enabled" type="checkbox" ${region.enabled ? "checked" : ""}><span>有効</span></label>
        <label class="checkbox mini"><input data-key="ocr" type="checkbox" ${region.ocr ? "checked" : ""}><span>OCR</span></label>
        <button class="ghost-button danger remove-region" type="button">削除</button>
      </div>
    </div>
    <div class="config-grid region-grid">
      <label><span>left</span><input data-key="left" type="number" value="${region.left}"></label>
      <label><span>top</span><input data-key="top" type="number" value="${region.top}"></label>
      <label><span>width</span><input data-key="width" type="number" min="1" value="${region.width}"></label>
      <label><span>height</span><input data-key="height" type="number" min="1" value="${region.height}"></label>
    </div>
  `;
  row.querySelector(".remove-region").addEventListener("click", () => {
    row.remove();
    byId("regions-summary").textContent = summarizeRegions(readRegionsFromForm());
  });
  row.querySelectorAll("input").forEach((input) => {
    input.addEventListener("input", () => {
      byId("regions-summary").textContent = summarizeRegions(readRegionsFromForm());
    });
  });
  return row;
}

function readRegionsFromForm() {
  return [...document.querySelectorAll(".region-card")].map((row, index) => {
    const value = (key) => row.querySelector(`[data-key="${key}"]`);
    return {
      name: value("name").value.toUpperCase() || `PHASE ${index + 1}`,
      left: Number(value("left").value),
      top: Number(value("top").value),
      width: Number(value("width").value),
      height: Number(value("height").value),
      enabled: value("enabled").checked,
      ocr: value("ocr").checked,
    };
  });
}

function renderConfig(config) {
  loadedConfig = config;
  byId("self-character-input").value = config.self_character || "";
  byId("min-confidence-input").value = config.min_confidence;
  byId("poll-seconds-input").value = config.poll_seconds;
  byId("ocr-weight-input").value = config.ocr_weight;
  byId("ocr-enabled-input").checked = !!config.ocr_enabled;
  byId("debug-save-images-input").checked = !!config.debug_save_images;
  byId("obs-mode-input").checked = !!config.obs_mode;

  const regionsList = byId("regions-list");
  regionsList.innerHTML = "";
  for (const [index, region] of (config.capture_regions || []).entries()) {
    regionsList.appendChild(buildRegionRow(region, index));
  }
  byId("regions-summary").textContent = summarizeRegions(config.capture_regions || []);
  document.body.classList.toggle("obs-mode", !!config.obs_mode);
}

async function loadConfig() {
  const response = await fetch("/config", { cache: "no-store" });
  const config = await response.json();
  renderConfig(config);
}

async function saveConfig() {
  const payload = {
    self_character: byId("self-character-input").value.trim(),
    min_confidence: Number(byId("min-confidence-input").value),
    poll_seconds: Number(byId("poll-seconds-input").value),
    ocr_weight: Number(byId("ocr-weight-input").value),
    ocr_enabled: byId("ocr-enabled-input").checked,
    debug_save_images: byId("debug-save-images-input").checked,
    obs_mode: byId("obs-mode-input").checked,
    capture_regions: readRegionsFromForm(),
  };
  const response = await fetch("/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const config = await response.json();
  renderConfig(config);
}

async function previewCapture() {
  const response = await fetch("/preview-capture", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ region: readRegionsFromForm()[0] }),
  });
  const payload = await response.json();
  byId("preview-wrap").classList.remove("hidden");
  byId("preview-image").src = `${payload.path}?t=${Date.now()}`;
}

function renderTemplates(groups) {
  const summary = byId("templates-summary");
  const list = byId("templates-list");
  summary.textContent = summarizeTemplates(groups);
  list.innerHTML = "";

  if (!groups.length) {
    const empty = document.createElement("div");
    empty.className = "template-empty";
    empty.textContent = "templates/<公式キャラ名>/ に PNG を保存するとここに表示される。";
    list.appendChild(empty);
    return;
  }

  for (const group of groups) {
    const section = document.createElement("section");
    section.className = "template-group";

    const title = document.createElement("div");
    title.className = "template-group-title";
    title.textContent = `${group.character} (${group.count})`;
    section.appendChild(title);

    for (const file of group.files) {
      const row = document.createElement("div");
      row.className = "template-item";
      const meta = document.createElement("div");
      meta.className = "template-meta";
      meta.innerHTML = `<div class="template-name">${file.name}</div><div class="template-sub">${formatTimestamp(file.updated_at)} / ${file.size} bytes</div>`;
      row.appendChild(meta);

      const button = document.createElement("button");
      button.className = "ghost-button danger";
      button.type = "button";
      button.textContent = "削除";
      button.addEventListener("click", async () => {
        if (!window.confirm(`${group.character} の ${file.name} を削除する。`)) {
          return;
        }
        const response = await fetch(file.delete_url, { method: "DELETE" });
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          window.alert(body.error || "テンプレート削除に失敗した。");
          return;
        }
        await refreshTemplates(true);
      });
      row.appendChild(button);
      section.appendChild(row);
    }
    list.appendChild(section);
  }
}

async function refreshTemplates(force = false) {
  const response = await fetch("/templates", { cache: "no-store" });
  const payload = await response.json();
  const groups = payload.templates || [];
  const signature = JSON.stringify(groups.map((group) => [group.character, group.files.map((file) => [file.name, file.updated_at])]));
  if (!force && signature === templateSignature) {
    return;
  }
  templateSignature = signature;
  renderTemplates(groups);
}

byId("templates-refresh").addEventListener("click", () => refreshTemplates(true));
byId("save-config").addEventListener("click", saveConfig);
byId("preview-capture").addEventListener("click", previewCapture);
byId("add-region").addEventListener("click", () => {
  const regions = readRegionsFromForm();
  byId("regions-list").appendChild(
    buildRegionRow(
      {
        name: `PHASE ${regions.length + 1}`,
        left: loadedConfig?.capture_region?.left || 0,
        top: loadedConfig?.capture_region?.top || 0,
        width: loadedConfig?.capture_region?.width || 100,
        height: loadedConfig?.capture_region?.height || 50,
        enabled: true,
        ocr: true,
      },
      regions.length,
    ),
  );
  byId("regions-summary").textContent = summarizeRegions(readRegionsFromForm());
});
byId("obs-mode-input").addEventListener("change", () => {
  document.body.classList.toggle("obs-mode", byId("obs-mode-input").checked);
});

loadConfig();
refresh();
refreshTemplates(true);
setInterval(refresh, 700);
setInterval(() => refreshTemplates(), 3000);
