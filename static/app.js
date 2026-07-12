const LANG = (navigator.language || "en").toLowerCase().startsWith("ru") ? "ru" : "en";
const DATE_LOCALE = LANG === "ru" ? "ru-RU" : "en-US";

const STRINGS = {
  ru: {
    tabConvert: "Конвертировать",
    tabArchive: "Архив",
    dropzoneHint: "Нажми или перетащи файл сюда",
    downloadBtn: "Скачать .md",
    copyBtn: "Копировать",
    copiedBtn: "Скопировано",
    copyFailed: "Не вышло",
    searchPlaceholder: "Поиск по названию…",
    certHint: "Установить сертификат (для iOS, один раз)",
    converting: name => `Конвертирую ${name}…`,
    done: "Готово, сохранено в архив.",
    error: msg => `Ошибка: ${msg}`,
    genericError: "Ошибка конвертации",
    notFound: "Ничего не найдено",
    deleteConfirm: name => `Удалить ${name}?`,
    deleteFailed: "Не удалось удалить",
    batchPending: "Ожидание…",
    batchOk: "Готово",
    batchError: "Ошибка",
    batchLimitExceeded: n => `Максимум ${n} файлов за раз`,
    batchDone: (ok, failed) => failed > 0 ? `Готово: ${ok} успешно, ${failed} с ошибкой` : `Готово: ${ok} файлов сконвертировано`,
    downloadZip: "Скачать всё ZIP",
    sizeUnit: "КБ",
    modeLocal: "локально",
    modeServer: "сервер",
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
    certHint: "Install certificate (for iOS, one-time)",
    converting: name => `Converting ${name}…`,
    done: "Done, saved to archive.",
    error: msg => `Error: ${msg}`,
    genericError: "Conversion failed",
    notFound: "Nothing found",
    deleteConfirm: name => `Delete ${name}?`,
    deleteFailed: "Failed to delete",
    batchPending: "Waiting…",
    batchOk: "Done",
    batchError: "Error",
    batchLimitExceeded: n => `Maximum ${n} files at a time`,
    batchDone: (ok, failed) => failed > 0 ? `Done: ${ok} succeeded, ${failed} failed` : `Done: ${ok} files converted`,
    downloadZip: "Download all as ZIP",
    sizeUnit: "KB",
    modeLocal: "local",
    modeServer: "server",
  },
};
const t = STRINGS[LANG];

document.documentElement.lang = LANG;
document.querySelectorAll("[data-i18n]").forEach(el => { el.textContent = t[el.dataset.i18n]; });
document.querySelectorAll("[data-i18n-placeholder]").forEach(el => { el.placeholder = t[el.dataset.i18nPlaceholder]; });

const modeBadge = document.getElementById("mode-badge");
fetch("/api/mode").then(r => r.json()).then(d => {
  modeBadge.textContent = d.mode === "local" ? t.modeLocal : t.modeServer;
}).catch(() => { modeBadge.textContent = t.modeServer; });

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
const resultEl = document.getElementById("result");
const resultText = document.getElementById("result-text");
const resultName = document.getElementById("result-name");
const downloadBtn = document.getElementById("download-btn");
const copyBtn = document.getElementById("copy-btn");
const batchResultEl = document.getElementById("batch-result");
const batchListEl = document.getElementById("batch-list");
const batchSummaryEl = document.getElementById("batch-summary");
const downloadZipBtn = document.getElementById("download-zip-btn");
const BATCH_LIMIT = 10;
let lastFilename = null;

function handleFiles(fileList) {
  const files = Array.from(fileList);
  if (files.length === 0) return;
  if (files.length === 1) convertFile(files[0]);
  else convertBatch(files);
}

fileInput.addEventListener("change", () => handleFiles(fileInput.files));
["dragover", "dragleave", "drop"].forEach(ev =>
  dropzone.addEventListener(ev, e => { e.preventDefault(); dropzone.classList.toggle("drag", ev === "dragover"); })
);
dropzone.addEventListener("drop", e => handleFiles(e.dataTransfer.files));

async function convertFile(file) {
  statusEl.textContent = t.converting(file.name);
  resultEl.hidden = true;
  batchResultEl.hidden = true;
  const form = new FormData();
  form.append("file", file);
  try {
    const res = await fetch("/api/convert", { method: "POST", body: form });
    if (!res.ok) throw new Error((await res.json()).detail || t.genericError);
    const data = await res.json();
    lastFilename = data.filename;
    resultName.textContent = data.filename;
    resultText.value = data.content;
    resultEl.hidden = false;
    statusEl.textContent = t.done;
  } catch (e) {
    statusEl.textContent = t.error(e.message);
  }
}

async function convertBatch(files) {
  if (files.length > BATCH_LIMIT) {
    statusEl.textContent = t.batchLimitExceeded(BATCH_LIMIT);
    return;
  }
  statusEl.textContent = "";
  resultEl.hidden = true;
  batchResultEl.hidden = false;
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
copyBtn.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(resultText.value);
    copyBtn.textContent = t.copiedBtn;
  } catch (e) {
    copyBtn.textContent = t.copyFailed;
  }
  setTimeout(() => (copyBtn.textContent = t.copyBtn), 1200);
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
    archiveList.innerHTML = `<li class="item-info"><span class="item-meta">${t.notFound}</span></li>`;
    return;
  }
  for (const item of items) {
    const li = document.createElement("li");
    const size = (item.size / 1024).toFixed(1) + " " + t.sizeUnit;
    const date = new Date(item.modified).toLocaleString(DATE_LOCALE, { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
    li.innerHTML = `
      <div class="item-info">
        <div class="item-name"></div>
        <div class="item-meta">${size} · ${date}</div>
      </div>
      <div class="item-btns">
        <button class="icon-btn" data-act="dl">⬇</button>
        <button class="icon-btn" data-act="del">✕</button>
      </div>`;
    li.querySelector(".item-name").textContent = item.filename;
    li.querySelector('[data-act="dl"]').addEventListener("click", () => {
      triggerDownload(item.filename);
    });
    li.querySelector('[data-act="del"]').addEventListener("click", async () => {
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
