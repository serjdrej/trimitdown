const modeBadge = document.getElementById("mode-badge");
fetch("/api/mode").then(r => r.json()).then(d => {
  modeBadge.textContent = d.mode === "local" ? "локально" : "NAS";
}).catch(() => { modeBadge.textContent = "NAS"; });

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
  statusEl.textContent = `Конвертирую ${file.name}…`;
  resultEl.hidden = true;
  const form = new FormData();
  form.append("file", file);
  try {
    const res = await fetch("/api/convert", { method: "POST", body: form });
    if (!res.ok) throw new Error((await res.json()).detail || "Ошибка конвертации");
    const data = await res.json();
    lastFilename = data.filename;
    resultName.textContent = data.filename;
    resultText.value = data.content;
    resultEl.hidden = false;
    statusEl.textContent = "Готово, сохранено в архив.";
  } catch (e) {
    statusEl.textContent = "Ошибка: " + e.message;
  }
}

downloadBtn.addEventListener("click", () => {
  if (lastFilename) window.location.href = `/api/archive/${encodeURIComponent(lastFilename)}`;
});
copyBtn.addEventListener("click", async () => {
  await navigator.clipboard.writeText(resultText.value);
  copyBtn.textContent = "Скопировано";
  setTimeout(() => (copyBtn.textContent = "Копировать"), 1200);
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
    archiveList.innerHTML = `<li class="item-info"><span class="item-meta">Ничего не найдено</span></li>`;
    return;
  }
  for (const item of items) {
    const li = document.createElement("li");
    const size = (item.size / 1024).toFixed(1) + " КБ";
    const date = new Date(item.modified).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
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
      window.location.href = `/api/archive/${encodeURIComponent(item.filename)}`;
    });
    li.querySelector('[data-act="del"]').addEventListener("click", async () => {
      if (!confirm(`Удалить ${item.filename}?`)) return;
      await fetch(`/api/archive/${encodeURIComponent(item.filename)}`, { method: "DELETE" });
      loadArchive();
    });
    archiveList.appendChild(li);
  }
}

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
