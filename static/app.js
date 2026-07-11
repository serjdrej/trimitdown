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
    searchPlaceholder: "Поиск по названию…",
    certHint: "Установить сертификат (для iOS, один раз)",
    converting: name => `Конвертирую ${name}…`,
    done: "Готово, сохранено в архив.",
    error: msg => `Ошибка: ${msg}`,
    genericError: "Ошибка конвертации",
    notFound: "Ничего не найдено",
    deleteConfirm: name => `Удалить ${name}?`,
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
    searchPlaceholder: "Search by name…",
    certHint: "Install certificate (for iOS, one-time)",
    converting: name => `Converting ${name}…`,
    done: "Done, saved to archive.",
    error: msg => `Error: ${msg}`,
    genericError: "Conversion failed",
    notFound: "Nothing found",
    deleteConfirm: name => `Delete ${name}?`,
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
let lastFilename = null;

fileInput.addEventListener("change", () => { if (fileInput.files[0]) convertFile(fileInput.files[0]); });
["dragover", "dragleave", "drop"].forEach(ev =>
  dropzone.addEventListener(ev, e => { e.preventDefault(); dropzone.classList.toggle("drag", ev === "dragover"); })
);
dropzone.addEventListener("drop", e => { const f = e.dataTransfer.files[0]; if (f) convertFile(f); });

async function convertFile(file) {
  statusEl.textContent = t.converting(file.name);
  resultEl.hidden = true;
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
  await navigator.clipboard.writeText(resultText.value);
  copyBtn.textContent = t.copiedBtn;
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
        <div class="item-name">${item.filename}</div>
        <div class="item-meta">${size} · ${date}</div>
      </div>
      <div class="item-btns">
        <button class="icon-btn" data-act="dl">⬇</button>
        <button class="icon-btn" data-act="del">✕</button>
      </div>`;
    li.querySelector('[data-act="dl"]').addEventListener("click", () => {
      triggerDownload(item.filename);
    });
    li.querySelector('[data-act="del"]').addEventListener("click", async () => {
      if (!confirm(t.deleteConfirm(item.filename))) return;
      await fetch(`/api/archive/${encodeURIComponent(item.filename)}`, { method: "DELETE" });
      loadArchive();
    });
    archiveList.appendChild(li);
  }
}

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
