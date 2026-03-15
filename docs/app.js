'use strict';

// ── 定数 ────────────────────────────────────────────────────────────────────
const STORAGE_KEY = 'sf6_overlay_v1';
const DEFAULT_CONFIG = {
  selfCharacter: '',
  region: { left: 1320, top: 40, width: 520, height: 180 },
  pollSeconds: 1.5,
  minConfidence: 0.35,
  obsMode: false,
};

// ── 状態 ────────────────────────────────────────────────────────────────────
let tesseractWorker = null;
let captureStream = null;
let pollTimer = null;
let lastCharacter = null;
let config = structuredClone(DEFAULT_CONFIG);

// ── DOM ──────────────────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);
const video = $('capture-video');
const setupScreen = $('setup-screen');
const overlayScreen = $('overlay-screen');
const startBtn = $('start-btn');

// ── 設定の永続化（localStorage） ────────────────────────────────────────────
function loadConfig() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      config = {
        ...DEFAULT_CONFIG,
        ...parsed,
        region: { ...DEFAULT_CONFIG.region, ...(parsed.region ?? {}) },
      };
    }
  } catch {
    // 壊れていたら無視してデフォルトを使う
  }
}

function saveConfig() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
}

function readConfigFromForm() {
  config.selfCharacter = $('self-character-input').value.trim();
  config.pollSeconds = parseFloat($('poll-seconds').value) || 1.5;
  config.minConfidence = parseFloat($('min-confidence').value) || 0.35;
  config.obsMode = $('obs-mode').checked;
  config.region = {
    left: parseInt($('region-left').value, 10) || 0,
    top: parseInt($('region-top').value, 10) || 0,
    width: Math.max(1, parseInt($('region-width').value, 10) || 100),
    height: Math.max(1, parseInt($('region-height').value, 10) || 50),
  };
}

function applyConfigToForm() {
  $('self-character-input').value = config.selfCharacter;
  $('poll-seconds').value = config.pollSeconds;
  $('min-confidence').value = config.minConfidence;
  $('obs-mode').checked = config.obsMode;
  $('region-left').value = config.region.left;
  $('region-top').value = config.region.top;
  $('region-width').value = config.region.width;
  $('region-height').value = config.region.height;
  $('self-character').textContent = config.selfCharacter || '-';
  document.body.classList.toggle('obs-mode', config.obsMode);
}

// ── Tesseract 初期化 ─────────────────────────────────────────────────────────
async function initTesseract() {
  const bar = $('worker-bar');
  const label = $('worker-label');

  tesseractWorker = await Tesseract.createWorker(['eng', 'jpn'], 1, {
    logger: (m) => {
      if (
        m.status === 'loading tesseract core' ||
        m.status === 'initializing tesseract' ||
        m.status === 'loading language traineddata'
      ) {
        const pct = Math.round((m.progress ?? 0) * 100);
        bar.style.width = `${pct}%`;
        label.textContent = `OCR エンジン読み込み中... ${pct}%`;
      }
    },
  });

  bar.style.width = '100%';
  label.textContent = 'OCR エンジン準備完了';
}

// ── 画面キャプチャ ───────────────────────────────────────────────────────────
async function startScreenCapture() {
  captureStream = await navigator.mediaDevices.getDisplayMedia({
    video: { frameRate: { ideal: 5, max: 10 } },
    audio: false,
  });

  video.srcObject = captureStream;
  await new Promise((resolve, reject) => {
    video.onloadedmetadata = resolve;
    video.onerror = reject;
  });
  await video.play();

  // ユーザーが共有を停止したとき
  captureStream.getVideoTracks()[0].addEventListener('ended', stopCapture);

  $('video-info').textContent = `映像サイズ: ${video.videoWidth} × ${video.videoHeight} px`;
}

function stopCapture() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  if (captureStream) {
    captureStream.getTracks().forEach((t) => t.stop());
    captureStream = null;
  }
  lastCharacter = null;
  setupScreen.classList.remove('hidden');
  overlayScreen.classList.add('hidden');
}

// ── フレーム取得 ─────────────────────────────────────────────────────────────
function grabRegionCanvas() {
  const { left, top, width, height } = config.region;
  const canvas = Object.assign(document.createElement('canvas'), { width, height });
  canvas.getContext('2d').drawImage(video, left, top, width, height, 0, 0, width, height);
  return canvas;
}

// ── キャラクター検出 ─────────────────────────────────────────────────────────
/**
 * Jaccard 係数でテキスト間の文字レベル類似度を計算する。
 * 短い名前との比較に適している。
 */
function jaccardSimilarity(a, b) {
  const sa = new Set(a);
  const sb = new Set(b);
  let inter = 0;
  for (const c of sa) if (sb.has(c)) inter++;
  return inter / (sa.size + sb.size - inter);
}

/**
 * OCR テキストからキャラクター名を検出する。
 * 優先順位: 完全一致 → エイリアス一致（日本語含む） → ファジー一致
 */
function detectCharacter(rawText) {
  if (!rawText.trim()) return null;

  const upper = rawText.toUpperCase();

  // 1. 正規名で完全一致（部分文字列）
  for (const canonical of CHARACTER_LIST) {
    if (upper.includes(canonical)) {
      return { character: canonical, confidence: 0.95, method: 'exact' };
    }
  }

  // 2. エイリアスで一致（日本語カタカナも含む）
  for (const [alias, canonical] of Object.entries(CHARACTER_ALIASES)) {
    if (rawText.includes(alias) || upper.includes(alias.toUpperCase())) {
      return { character: canonical, confidence: 0.85, method: 'alias' };
    }
  }

  // 3. ファジーマッチ（英字のみ）
  const clean = upper.replace(/[^\w.\s]/g, ' ').replace(/\s+/g, ' ').trim();
  let bestCharacter = null;
  let bestScore = 0;
  for (const canonical of CHARACTER_LIST) {
    const score = jaccardSimilarity(clean, canonical);
    if (score > bestScore) {
      bestScore = score;
      bestCharacter = canonical;
    }
  }

  if (bestScore >= config.minConfidence) {
    return { character: bestCharacter, confidence: bestScore, method: 'fuzzy' };
  }

  return null;
}

// ── ポーリングループ ──────────────────────────────────────────────────────────
async function poll() {
  if (!tesseractWorker || !captureStream) return;

  try {
    const frame = grabRegionCanvas();
    const {
      data: { text },
    } = await tesseractWorker.recognize(frame);

    $('ocr-text').textContent = text.trim() || '（テキストなし）';

    const result = detectCharacter(text);

    if (result) {
      $('detect-log').textContent = `${result.character}\n方法: ${result.method}\n信頼度: ${result.confidence.toFixed(2)}`;
      updateCharacterDisplay(result.character, result.confidence);
    } else {
      $('detect-log').textContent = '（キャラ未検出）';
      $('status').textContent = '検出中...';
    }
  } catch (err) {
    console.error('Poll error:', err);
    $('status').textContent = 'エラー: ' + err.message;
  }
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  poll();
  pollTimer = setInterval(poll, config.pollSeconds * 1000);
}

// ── UI 更新 ──────────────────────────────────────────────────────────────────
function updateCharacterDisplay(character, confidence) {
  $('opponent').textContent = character;
  $('confidence').textContent = confidence.toFixed(2);
  $('status').textContent = '検出済み';

  if (character !== lastCharacter) {
    lastCharacter = character;
    renderNotes(character);
  }
}

function renderNotes(character) {
  const list = $('notes');
  list.innerHTML = '';

  const notes = MATCHUP_DATA[character] ?? [];

  if (!notes.length) {
    const li = document.createElement('li');
    li.textContent = `${character} の対策メモはありません`;
    li.style.color = 'var(--muted)';
    list.appendChild(li);
    return;
  }

  for (const note of notes) {
    const li = document.createElement('li');
    li.textContent = note;
    list.appendChild(li);
  }
}

// ── プレビュー ───────────────────────────────────────────────────────────────
function showPreview() {
  readConfigFromForm();
  const { width, height } = config.region;
  const canvas = $('preview-canvas');
  canvas.width = width;
  canvas.height = height;

  try {
    const frame = grabRegionCanvas();
    canvas.getContext('2d').drawImage(frame, 0, 0);
    $('preview-container').classList.remove('hidden');
  } catch {
    alert('プレビューの取得に失敗しました。画面共有中か確認してください。');
  }
}

// ── イベントハンドラ ─────────────────────────────────────────────────────────
startBtn.addEventListener('click', async () => {
  try {
    startBtn.disabled = true;
    startBtn.textContent = '画面を選択してください...';

    await startScreenCapture();

    setupScreen.classList.add('hidden');
    overlayScreen.classList.remove('hidden');

    applyConfigToForm();
    $('status').textContent = '検出中...';
    startPolling();
  } catch (err) {
    startBtn.disabled = false;
    startBtn.textContent = 'スタート';
    if (err.name !== 'NotAllowedError') {
      alert('エラー: ' + err.message);
    }
  }
});

$('save-settings').addEventListener('click', () => {
  readConfigFromForm();
  saveConfig();
  applyConfigToForm();
  startPolling();
  $('status').textContent = '設定を保存しました';
});

$('preview-btn').addEventListener('click', showPreview);

$('stop-btn').addEventListener('click', stopCapture);

$('obs-mode').addEventListener('change', () => {
  document.body.classList.toggle('obs-mode', $('obs-mode').checked);
});

// ── 起動 ────────────────────────────────────────────────────────────────────
(async () => {
  loadConfig();

  try {
    await initTesseract();
    startBtn.disabled = false;
    startBtn.textContent = 'スタート';
  } catch (err) {
    $('worker-label').textContent = 'OCR 初期化失敗: ' + err.message;
    startBtn.textContent = '読み込み失敗（再読み込みしてください）';
  }
})();
