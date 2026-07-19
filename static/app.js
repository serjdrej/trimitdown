const LANG = (navigator.language || "en").toLowerCase().startsWith("ru") ? "ru" : "en";
const DATE_LOCALE = LANG === "ru" ? "ru-RU" : "en-US";

const STRINGS = {
  ru: {
    tabConvert: "Конвертация",
    tabArchive: "Архив",
    dropzoneHint: "Нажми или перетащи файл сюда",
    downloadBtn: "Скачать .md",
    copyBtn: "Копировать",
    copiedBtn: "Скопировано",
    copyFailed: "Не вышло",
    searchPlaceholder: "Поиск по названию…",
    privacyHint: "Приватность и хранение данных",
    tabSettings: "Настройки",
    tokensAfterLabel: "Токенов после сжатия",
    tokensAfterSub: "в результате",
    converting: name => `Конвертирую ${name}…`,
    done: "Готово, сохранено в архив.",
    error: msg => `Ошибка: ${msg}`,
    genericError: "Ошибка конвертации",
    notFound: "Ничего не найдено",
    emptyArchive: "Пока нет документов",
    deleteConfirm: name => `Удалить ${name}?`,
    deleteFailed: "Не удалось удалить",
    previewBtn: "Просмотр",
    sourceBtn: "RAW",
    justNow: "готово • только что",
    batchPending: "Ожидание…",
    batchOk: "Готово",
    batchError: "Ошибка",
    batchLimitExceeded: n => `Максимум ${n} файлов за раз`,
    batchDone: (ok, failed) => failed > 0 ? `Готово: ${ok} успешно, ${failed} с ошибкой` : `Готово: ${ok} файлов сконвертировано`,
    downloadZip: "Скачать всё ZIP",
    sizeUnit: "КБ",
    modeLocal: "локально",
    modeServer: "сервер",
    serverUrlLabel: "Адрес сервера",
    saveBtn: "Сохранить",
    testConnectionBtn: "Проверить соединение",
    resetLocalBtn: "Сбросить на локальный режим",
    colorThemeLabel: "Цветовая тема",
    themeClay: "Глина",
    themeOcean: "Океан",
    appearanceLabel: "Оформление",
    appSystem: "Системное",
    appLight: "Светлое",
    appDark: "Тёмное",
    invalidUrlMsg: "Неверный формат: нужен https://, без слэша в конце",
    restartMsg: "Изменения вступят в силу после перезапуска приложения",
    testingMsg: "Проверяю…",
    reachableMsg: "Сервер доступен",
    unreachableMsg: "Сервер недоступен",
    versionLabel: v => `Версия ${v}`,
  },
  en: {
    tabConvert: "Convert",
    tabArchive: "Archive",
    dropzoneHint: "Tap or drop a file here",
    downloadBtn: "Download .md",
    copyBtn: "Copy",
    copiedBtn: "Copied",
    copyFailed: "Failed",
    searchPlaceholder: "Search by name…",
    privacyHint: "Privacy and data storage",
    tabSettings: "Settings",
    tokensAfterLabel: "Tokens after compression",
    tokensAfterSub: "in the result",
    converting: name => `Converting ${name}…`,
    done: "Done, saved to archive.",
    error: msg => `Error: ${msg}`,
    genericError: "Conversion failed",
    notFound: "Nothing found",
    emptyArchive: "No documents yet",
    deleteConfirm: name => `Delete ${name}?`,
    deleteFailed: "Failed to delete",
    previewBtn: "Preview",
    sourceBtn: "RAW",
    justNow: "done • just now",
    batchPending: "Waiting…",
    batchOk: "Done",
    batchError: "Error",
    batchLimitExceeded: n => `Maximum ${n} files at a time`,
    batchDone: (ok, failed) => failed > 0 ? `Done: ${ok} succeeded, ${failed} failed` : `Done: ${ok} files converted`,
    downloadZip: "Download all as ZIP",
    sizeUnit: "KB",
    modeLocal: "local",
    modeServer: "server",
    serverUrlLabel: "Server address",
    saveBtn: "Save",
    testConnectionBtn: "Test connection",
    resetLocalBtn: "Reset to local mode",
    colorThemeLabel: "Color theme",
    themeClay: "Clay",
    themeOcean: "Ocean",
    appearanceLabel: "Appearance",
    appSystem: "System",
    appLight: "Light",
    appDark: "Dark",
    invalidUrlMsg: "Invalid format: needs https://, no trailing slash",
    restartMsg: "Changes take effect after restarting the app",
    testingMsg: "Checking…",
    reachableMsg: "Server is reachable",
    unreachableMsg: "Server is unreachable",
    versionLabel: v => `Version ${v}`,
  },
};
const t = STRINGS[LANG];

const THEME_KEY = "trimitdown-theme";
function loadThemePref() {
  try { const p = JSON.parse(localStorage.getItem(THEME_KEY));
        if (p && p.colorTheme && p.mode) return p; } catch (e) {}
  return { colorTheme: "clay", mode: "auto" };
}
function saveThemePref(pref) { localStorage.setItem(THEME_KEY, JSON.stringify(pref)); }
const darkMQ = matchMedia("(prefers-color-scheme: dark)");
function applyTheme() {
  const pref = loadThemePref();
  const dark = pref.mode === "auto" ? darkMQ.matches : pref.mode === "dark";
  document.documentElement.dataset.theme = pref.colorTheme;
  document.documentElement.dataset.mode  = dark ? "dark" : "light";
  setThemeColorMeta();
}
function setThemeColorMeta() {
  const bg = getComputedStyle(document.body).backgroundColor;
  let m = document.querySelector('meta[name="theme-color"]');
  if (!m) { m = document.createElement("meta"); m.name = "theme-color"; document.head.appendChild(m); }
  m.setAttribute("content", bg);
}
// re-run on system change only while in auto:
darkMQ.addEventListener("change", () => { if (loadThemePref().mode === "auto") applyTheme(); });
applyTheme();

document.documentElement.lang = LANG;
document.querySelectorAll("[data-i18n]").forEach(el => { el.textContent = t[el.dataset.i18n]; });
document.querySelectorAll("[data-i18n-placeholder]").forEach(el => { el.placeholder = t[el.dataset.i18nPlaceholder]; });
document.querySelectorAll("[data-i18n-aria]").forEach(el => { el.setAttribute("aria-label", t[el.dataset.i18nAria]); });

const statusPill = document.getElementById("status-pill");
const statusPillLabel = statusPill.querySelector(".status-label");
const appVersionEl = document.getElementById("app-version");
function setStatusPill(mode) {
  const local = mode === "local";
  statusPill.classList.toggle("mode-local", local);
  statusPill.classList.toggle("mode-server", !local);
  statusPillLabel.textContent = local ? t.modeLocal : t.modeServer;
}
fetch("/api/mode").then(r => r.json()).then(d => {
  setStatusPill(d.mode);
  appVersionEl.textContent = t.versionLabel(d.version);
}).catch(() => { setStatusPill("server"); });

function isValidServerUrl(url) {
  return /^https:\/\/.+[^/]$/.test(url);
}

// A failed response body isn't always JSON: an unhandled server exception returns
// a plain-text "Internal Server Error", and res.json() on that throws its own
// cryptic "Unexpected token" — hiding the real problem. Read the body as text,
// pull .detail if it happens to be our JSON error, otherwise fall back to a
// readable generic message.
async function errorDetail(res) {
  const body = await res.text();
  try {
    return JSON.parse(body).detail || t.genericError;
  } catch (e) {
    return t.genericError;
  }
}

const serverUrlGroup = document.getElementById("server-url-group");
function setupServerSettings() {
  serverUrlGroup.hidden = false;
  const serverUrlInput = document.getElementById("server-url-input");
  const serverStatusMsg = document.getElementById("server-status-msg");
  const saveServerBtn = document.getElementById("save-server-btn");
  const testServerBtn = document.getElementById("test-server-btn");
  const resetServerBtn = document.getElementById("reset-server-btn");

  window.pywebview.api.get_server_url().then(url => { serverUrlInput.value = url || ""; });

  saveServerBtn.addEventListener("click", async () => {
    const url = serverUrlInput.value.trim();
    if (url && !isValidServerUrl(url)) {
      serverStatusMsg.textContent = t.invalidUrlMsg;
      return;
    }
    await window.pywebview.api.save_server_url(url);
    serverStatusMsg.textContent = t.restartMsg;
  });

  testServerBtn.addEventListener("click", async () => {
    const url = serverUrlInput.value.trim();
    if (!isValidServerUrl(url)) {
      serverStatusMsg.textContent = t.invalidUrlMsg;
      return;
    }
    serverStatusMsg.textContent = t.testingMsg;
    const ok = await window.pywebview.api.check_reachable(url);
    serverStatusMsg.textContent = ok ? t.reachableMsg : t.unreachableMsg;
  });

  resetServerBtn.addEventListener("click", async () => {
    serverUrlInput.value = "";
    await window.pywebview.api.save_server_url("");
    serverStatusMsg.textContent = t.restartMsg;
  });
}

// pywebview injects window.pywebview.api asynchronously; the ready signal is the
// pywebviewready event. Checking synchronously at script load loses the race in
// the packaged app (slow onefile startup), which left the server-address group
// hidden and forced users to hand-edit config.json. Run now if the api is
// already present, otherwise wait for the event. In browser/server mode
// pywebview never exists, so the group correctly stays hidden.
if (window.pywebview && window.pywebview.api) {
  setupServerSettings();
} else {
  window.addEventListener("pywebviewready", setupServerSettings);
}

const colorThemeSelect = document.getElementById("color-theme-select");
const appearanceSelect = document.getElementById("appearance-select");
const initialThemePref = loadThemePref();
colorThemeSelect.value = initialThemePref.colorTheme;
appearanceSelect.value = initialThemePref.mode;
colorThemeSelect.addEventListener("change", () => {
  const pref = loadThemePref();
  pref.colorTheme = colorThemeSelect.value;
  saveThemePref(pref);
  applyTheme();
});
appearanceSelect.addEventListener("change", () => {
  const pref = loadThemePref();
  pref.mode = appearanceSelect.value;
  saveThemePref(pref);
  applyTheme();
});

const tabs = document.querySelectorAll(".tab");
const views = document.querySelectorAll(".view");
tabs.forEach(tab => tab.addEventListener("click", () => {
  tabs.forEach(t => t.classList.remove("active"));
  views.forEach(v => v.classList.remove("active"));
  tab.classList.add("active");
  document.getElementById(tab.dataset.tab).classList.add("active");
  if (tab.dataset.tab === "archive") loadArchive();
}));

const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("file-input");
const statusEl = document.getElementById("status");
function setStatus(txt) { statusEl.textContent = txt; statusEl.hidden = !txt; }
const progressEl = document.getElementById("convert-progress");
const resultEl = document.getElementById("result");
const resultText = document.getElementById("result-text");
const resultPreview = document.getElementById("result-preview");
const resultName = document.getElementById("result-name");
const resultStatus = document.getElementById("result-status");
const resultBadge = document.getElementById("result-badge");
const tokenInfoEl = document.getElementById("token-info");
const tokenSavingsEl = document.getElementById("token-savings");
const tokenDetailEl = document.getElementById("token-detail");
const tokenRingEl = document.getElementById("token-ring");
const downloadBtn = document.getElementById("download-btn");
const copyBtn = document.getElementById("copy-btn");
const previewToggleBtn = document.getElementById("preview-toggle-btn");
const sourceToggleBtn = document.getElementById("source-toggle-btn");
const batchResultEl = document.getElementById("batch-result");
const batchListEl = document.getElementById("batch-list");
const batchSummaryEl = document.getElementById("batch-summary");
const downloadZipBtn = document.getElementById("download-zip-btn");
const BATCH_LIMIT = 10;
let lastFilename = null;

const FILE_BADGE_MAP = {
  pdf:  { color: "#C0392B", label: "PDF" },
  docx: { color: "#2B6CB0", label: "DOC" },
  doc:  { color: "#2B6CB0", label: "DOC" },
  pptx: { color: "#D97706", label: "PPT" },
  ppt:  { color: "#D97706", label: "PPT" },
  xlsx: { color: "#2F855A", label: "XLS" },
  xls:  { color: "#2F855A", label: "XLS" },
  epub: { color: "#6B46C1", label: "PUB" },
  html: { color: "#DD6B20", label: "HTM" },
  htm:  { color: "#DD6B20", label: "HTM" },
};
function fileBadge(filename) {
  const dot = filename.lastIndexOf(".");
  const ext = dot >= 0 ? filename.slice(dot + 1).toLowerCase() : "";
  if (FILE_BADGE_MAP[ext]) return FILE_BADGE_MAP[ext];
  return { color: "var(--muted)", label: ext ? ext.slice(0, 3).toUpperCase() : "DOC" };
}

function showPreview() {
  resultPreview.hidden = false;
  resultText.hidden = true;
  previewToggleBtn.classList.add("active");
  sourceToggleBtn.classList.remove("active");
}

function showSource() {
  resultPreview.hidden = true;
  resultText.hidden = false;
  previewToggleBtn.classList.remove("active");
  sourceToggleBtn.classList.add("active");
}

function renderTokenInfo(tokens) {
  tokenInfoEl.hidden = false;
  const pct = tokens.before != null ? Math.round((1 - tokens.after / tokens.before) * 100) : 0;
  tokenDetailEl.textContent = tokens.after.toLocaleString(DATE_LOCALE);
  if (pct > 0) {
    const capped = Math.min(100, pct);
    tokenSavingsEl.textContent = capped + "%";
    tokenRingEl.style.setProperty("--pct", capped + "%");
    tokenRingEl.hidden = false;
  } else {
    tokenRingEl.hidden = true;
  }
}

previewToggleBtn.addEventListener("click", showPreview);
sourceToggleBtn.addEventListener("click", showSource);

function handleFiles(fileList) {
  const files = Array.from(fileList);
  if (files.length === 0) return;
  dropzone.classList.add("compact");
  if (files.length === 1) convertFile(files[0]);
  else convertBatch(files);
}

fileInput.addEventListener("change", () => { handleFiles(fileInput.files); fileInput.value = ""; });
["dragover", "dragleave", "drop"].forEach(ev =>
  dropzone.addEventListener(ev, e => { e.preventDefault(); dropzone.classList.toggle("drag", ev === "dragover"); })
);
dropzone.addEventListener("drop", e => handleFiles(e.dataTransfer.files));

async function convertFile(file) {
  setStatus(t.converting(file.name));
  progressEl.hidden = false;
  resultEl.hidden = true;
  batchResultEl.hidden = true;
  tokenInfoEl.hidden = true;
  const form = new FormData();
  form.append("file", file);
  try {
    const res = await fetch("/api/convert", { method: "POST", body: form });
    if (!res.ok) throw new Error(await errorDetail(res));
    const data = await res.json();
    lastFilename = data.filename;
    resultName.textContent = data.filename;
    resultStatus.textContent = t.justNow;
    const badge = fileBadge(file.name);
    resultBadge.style.background = badge.color;
    resultBadge.textContent = badge.label;
    resultText.value = data.content;
    resultPreview.innerHTML = DOMPurify.sanitize(marked.parse(data.content));
    showPreview();
    renderTokenInfo(data.tokens);
    resultEl.hidden = false;
    setStatus("");
  } catch (e) {
    setStatus(t.error(e.message));
  } finally {
    progressEl.hidden = true;
  }
}

async function convertBatch(files) {
  if (files.length > BATCH_LIMIT) {
    setStatus(t.batchLimitExceeded(BATCH_LIMIT));
    return;
  }
  setStatus("");
  resultEl.hidden = true;
  batchResultEl.hidden = false;
  tokenInfoEl.hidden = true;
  batchListEl.innerHTML = "";
  batchSummaryEl.textContent = "";
  downloadZipBtn.hidden = true;

  const rows = [];
  for (const file of files) {
    const li = document.createElement("li");
    li.innerHTML = `<div class="batch-item-name"></div><div class="batch-item-status"></div>`;
    li.querySelector(".batch-item-name").textContent = file.name;
    li.querySelector(".batch-item-status").textContent = t.batchPending;
    batchListEl.appendChild(li);
    rows.push(li);
  }

  const form = new FormData();
  for (const file of files) form.append("files", file);

  const successful = [];
  let failedCount = 0;
  let eventIndex = 0;
  try {
    const res = await fetch("/api/convert-batch", { method: "POST", body: form });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop();
      for (const part of parts) {
        if (!part.startsWith("data: ")) continue;
        const event = JSON.parse(part.slice(6));
        const li = rows[eventIndex++];
        if (!li) continue;
        const statusSpan = li.querySelector(".batch-item-status");
        if (event.status === "ok") {
          statusSpan.textContent = t.batchOk;
          statusSpan.className = "batch-item-status status-ok";
          successful.push(event.saved_as);
        } else {
          statusSpan.textContent = event.detail || t.batchError;
          statusSpan.className = "batch-item-status status-error";
          failedCount++;
        }
      }
    }
  } catch (e) {
    batchSummaryEl.textContent = t.error(e.message);
    return;
  }

  batchSummaryEl.textContent = t.batchDone(successful.length, failedCount);
  if (successful.length > 0) {
    downloadZipBtn.hidden = false;
    downloadZipBtn.onclick = () => {
      window.location.href = `/api/archive-zip?names=${encodeURIComponent(successful.join(","))}`;
    };
  }
}

function triggerDownload(filename) {
  // A real click on an <a download> element makes pywebview's WKWebView backend
  // treat this as a download (shouldPerformDownload()) regardless of the
  // response's MIME type; window.location.href / fetch+blob navigations don't
  // reliably trigger it and just render the file in-window instead.
  const a = document.createElement("a");
  a.href = `/api/archive/${encodeURIComponent(filename)}`;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

downloadBtn.addEventListener("click", () => {
  if (lastFilename) triggerDownload(lastFilename);
});
const copyBtnLabel = copyBtn.querySelector("span");
copyBtn.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(resultText.value);
    copyBtnLabel.textContent = t.copiedBtn;
  } catch (e) {
    copyBtnLabel.textContent = t.copyFailed;
  }
  setTimeout(() => (copyBtnLabel.textContent = t.copyBtn), 1200);
});

const searchInput = document.getElementById("search");
const archiveList = document.getElementById("archive-list");
let searchTimer;
searchInput.addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(loadArchive, 250); });

async function loadArchive() {
  const q = encodeURIComponent(searchInput.value);
  const items = await (await fetch(`/api/archive?q=${q}`)).json();
  archiveList.innerHTML = "";
  if (items.length === 0) {
    if (searchInput.value.trim() === "") {
      archiveList.innerHTML = `<li class="empty-state">
        <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M22 12h-6l-2 3h-4l-2-3H2"/>
          <path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>
        </svg>
        <p>${t.emptyArchive}</p>
      </li>`;
    } else {
      archiveList.innerHTML = `<li class="item-info"><span class="item-meta">${t.notFound}</span></li>`;
    }
    return;
  }
  for (const item of items) {
    const li = document.createElement("li");
    const size = (item.size / 1024).toFixed(1) + " " + t.sizeUnit;
    const date = new Date(item.modified).toLocaleString(DATE_LOCALE, { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
    li.innerHTML = `
      <button class="item-row" type="button">
        <div class="item-info">
          <div class="item-name"></div>
          <div class="item-meta">${size} · ${date}</div>
        </div>
        <div class="item-btns">
          <span class="icon-btn" data-act="del">✕</span>
        </div>
      </button>`;
    li.querySelector(".item-name").textContent = item.filename;
    li.querySelector(".item-row").addEventListener("click", () => {
      triggerDownload(item.filename);
    });
    li.querySelector('[data-act="del"]').addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm(t.deleteConfirm(item.filename))) return;
      try {
        await fetch(`/api/archive/${encodeURIComponent(item.filename)}`, { method: "DELETE" });
      } catch (e) {
        alert(t.deleteFailed);
        return;
      }
      loadArchive();
    });
    archiveList.appendChild(li);
  }
}

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
