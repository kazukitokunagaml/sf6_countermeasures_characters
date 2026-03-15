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

/** フォルダから読み込んだ対策データ。null のとき matchups.js の MATCHUP_DATA を使う */
let activeMatchupData = null;
let currentDirHandle = null;

// ── DOM ──────────────────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);
const video = $('capture-video');
const setupScreen = $('setup-screen');
const overlayScreen = $('overlay-screen');
const startBtn = $('start-btn');

// ── IndexedDB（ディレクトリハンドルの永続化） ────────────────────────────────
function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open('sf6_overlay', 1);
    req.onupgradeneeded = (e) => e.target.result.createObjectStore('kv');
    req.onsuccess = (e) => resolve(e.target.result);
    req.onerror = (e) => reject(e.target.error);
  });
}

async function idbGet(key) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('kv', 'readonly');
    const req = tx.objectStore('kv').get(key);
    req.onsuccess = () => resolve(req.result ?? null);
    req.onerror = () => reject(req.error);
  });
}

async function idbSet(key, value) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('kv', 'readwrite');
    const req = tx.objectStore('kv').put(value, key);
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
  });
}

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

// ── 対策フォルダ管理 ─────────────────────────────────────────────────────────
/**
 * .md ファイルのテキストをパースして対策メモ配列を返す。
 * Python 側の parse_matchup_notes と同じルール。
 */
function parseMatchupText(text) {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith('#'))
    .map((line) => line.replace(/\*\*/g, '').replace(/\s+/g, ' '));
}

/** ディレクトリハンドルから全 .md ファイルを読み込んで対策データを返す */
async function loadMatchupsFromDirectory(dirHandle) {
  const data = {};
  for await (const [name, handle] of dirHandle.entries()) {
    if (handle.kind !== 'file' || !name.endsWith('.md')) continue;
    const file = await handle.getFile();
    const text = await file.text();
    const character = name.slice(0, -3); // ".md" を除く
    const notes = parseMatchupText(text);
    if (notes.length) data[character] = notes;
  }
  return data;
}

/** ディレクトリを適用（パーミッション確認 → データ読込 → 表示更新） */
async function applyDirectory(handle) {
  const permission = await handle.requestPermission({ mode: 'read' });
  if (permission !== 'granted') throw new Error('フォルダへのアクセスが拒否されました');

  currentDirHandle = handle;
  activeMatchupData = await loadMatchupsFromDirectory(handle);

  const count = Object.keys(activeMatchupData).length;
  updateFolderDisplay(handle.name, count);

  // 現在表示中のキャラのメモを更新
  if (lastCharacter) renderNotes(lastCharacter);

  return count;
}

/** フォルダ名表示を更新（セットアップ画面・設定パネルの両方） */
function updateFolderDisplay(folderName, count) {
  const text = folderName
    ? `${folderName}（${count} キャラ）`
    : '未設定（内蔵データを使用）';
  const isMuted = !folderName;

  for (const id of ['setup-folder-name', 'settings-folder-name']) {
    const el = $(id);
    if (!el) continue;
    el.textContent = text;
    el.classList.toggle('muted', isMuted);
    el.classList.toggle('folder-active', !isMuted);
  }
}

/** フォルダ選択ダイアログを開く */
async function selectDirectory() {
  if (!('showDirectoryPicker' in window)) {
    $('folder-api-warning')?.classList.remove('hidden');
    return;
  }
  try {
    const handle = await window.showDirectoryPicker({ mode: 'read' });
    const count = await applyDirectory(handle);
    await idbSet('dirHandle', handle);
    $('status').textContent = `フォルダを読み込みました（${count} キャラ）`;
  } catch (err) {
    if (err.name !== 'AbortError') {
      alert('フォルダの読み込みに失敗しました: ' + err.message);
    }
  }
}

/** 現在のフォルダを再読込する */
async function reloadDirectory() {
  if (!currentDirHandle) {
    alert('フォルダが選択されていません');
    return;
  }
  try {
    const count = await applyDirectory(currentDirHandle);
    $('status').textContent = `再読込しました（${count} キャラ）`;
  } catch (err) {
    alert('再読込に失敗しました: ' + err.message);
  }
}

/** 起動時に前回のフォルダハンドルを IndexedDB から復元する */
async function restoreSavedDirectory() {
  try {
    const handle = await idbGet('dirHandle');
    if (!handle) return;

    // セッション内で既にパーミッションが付与されているか確認
    const permission = await handle.queryPermission({ mode: 'read' });
    if (permission === 'granted') {
      await applyDirectory(handle);
    } else {
      // パーミッション未取得の場合はフォルダ名だけ表示して再選択を促す
      updateFolderDisplay(handle.name + '（再許可が必要）', 0);
      currentDirHandle = handle; // ボタン押下時に requestPermission できるように保持
    }
  } catch {
    // 保存済みハンドルが無効になっていても無視
  }
}

// ── デフォルト対策データを ZIP でダウンロード ────────────────────────────────
async function downloadDefaultMatchups() {
  const btn = $('download-defaults-btn');
  btn.disabled = true;
  btn.textContent = '生成中...';

  try {
    const zip = new JSZip();
    for (const [character, notes] of Object.entries(MATCHUP_DATA)) {
      zip.file(`${character}.md`, notes.join('\n') + '\n');
    }
    const blob = await zip.generateAsync({ type: 'blob' });
    const url = URL.createObjectURL(blob);
    Object.assign(document.createElement('a'), {
      href: url,
      download: 'sf6_matchups.zip',
    }).click();
    URL.revokeObjectURL(url);
  } finally {
    btn.disabled = false;
    btn.textContent = 'デフォルトをDL';
  }
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

  captureStream.getVideoTracks()[0].addEventListener('ended', stopCapture);
  $('video-info').textContent = `映像サイズ: ${video.videoWidth} × ${video.videoHeight} px`;
}

function stopCapture() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  if (captureStream) { captureStream.getTracks().forEach((t) => t.stop()); captureStream = null; }
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
function jaccardSimilarity(a, b) {
  const sa = new Set(a);
  const sb = new Set(b);
  let inter = 0;
  for (const c of sa) if (sb.has(c)) inter++;
  return inter / (sa.size + sb.size - inter);
}

function detectCharacter(rawText) {
  if (!rawText.trim()) return null;

  const upper = rawText.toUpperCase();

  // 1. 正規名で部分一致
  for (const canonical of CHARACTER_LIST) {
    if (upper.includes(canonical)) {
      return { character: canonical, confidence: 0.95, method: 'exact' };
    }
  }

  // 2. エイリアス一致（日本語カタカナ含む）
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
    if (score > bestScore) { bestScore = score; bestCharacter = canonical; }
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
    const { data: { text } } = await tesseractWorker.recognize(frame);

    $('ocr-text').textContent = text.trim() || '（テキストなし）';

    const result = detectCharacter(text);
    if (result) {
      $('detect-log').textContent =
        `${result.character}\n方法: ${result.method}\n信頼度: ${result.confidence.toFixed(2)}`;
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

/**
 * 対策メモを表示する。
 * activeMatchupData（ユーザーフォルダ）が設定されていればそちらを優先し、
 * なければ matchups.js の MATCHUP_DATA を使う。
 */
function renderNotes(character) {
  const list = $('notes');
  list.innerHTML = '';

  const data = activeMatchupData ?? MATCHUP_DATA;
  const notes = data[character] ?? [];

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
    canvas.getContext('2d').drawImage(grabRegionCanvas(), 0, 0);
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
    if (err.name !== 'NotAllowedError') alert('エラー: ' + err.message);
  }
});

$('select-folder-btn').addEventListener('click', selectDirectory);
$('download-defaults-btn').addEventListener('click', downloadDefaultMatchups);
$('change-folder-btn').addEventListener('click', selectDirectory);
$('reload-folder-btn').addEventListener('click', reloadDirectory);

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

// ── ブラウザ互換性チェック ────────────────────────────────────────────────────
function checkBrowserSupport() {
  if (!('showDirectoryPicker' in window)) {
    $('folder-api-warning')?.classList.remove('hidden');
    $('select-folder-btn').disabled = true;
    $('select-folder-btn').title = 'Chrome / Edge が必要です';
  }
}

// ── 起動 ────────────────────────────────────────────────────────────────────
(async () => {
  loadConfig();
  checkBrowserSupport();

  // Tesseract 初期化とフォルダ復元を並行して実行
  const [tesseractResult] = await Promise.allSettled([
    initTesseract(),
    restoreSavedDirectory(),
  ]);

  if (tesseractResult.status === 'fulfilled') {
    startBtn.disabled = false;
    startBtn.textContent = 'スタート';
  } else {
    $('worker-label').textContent = 'OCR 初期化失敗: ' + tesseractResult.reason?.message;
    startBtn.textContent = '読み込み失敗（再読み込みしてください）';
  }
})();
