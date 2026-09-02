/* AI 早报控制中心前端逻辑 */
const $ = (s) => document.querySelector(s);
let date = null;
let items = [];
let picks = new Set();
let previewTimer = null;
let runPollTimer = null;
let runWasActive = false;
let exportOrder = [];
let runLogVisible = false;

async function api(path, body) {
  const opt = body
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : {};
  const r = await fetch(path, opt);
  try { return await r.json(); } catch { return { ok: false, error: "服务返回异常" }; }
}

function status(msg, err = false) {
  // 提示会一直保留，直到被下一条提示替换——成功消息不会被自动吞掉
  const el = $("#statusText");
  el.textContent = msg || "";
  $("#status").classList.toggle("err", err);
  $("#status").classList.toggle("ok", !err);
}

function outputUrl(path) {
  if (!path) return "";
  return "/output/" + String(path).replaceAll("\\", "/");
}

function resolveOutputAsset(path) {
  if (!path || /^(https?:|data:|\/|#)/i.test(path)) return path;
  const clean = path.replaceAll("\\", "/").replace(/^\.?\//, "");
  if (/^\d{4}-\d{2}-\d{2}\//.test(clean)) return outputUrl(clean);
  return outputUrl(`${date}/${clean}`);
}

function renderDateOptions(dates, selectedDate, hasDraft) {
  const sel = $("#dateSel");
  const availableDates = [...new Set(dates || [])];
  if (selectedDate && !availableDates.includes(selectedDate)) {
    availableDates.unshift(selectedDate);
  }
  sel.innerHTML = "";
  for (const d of availableDates) {
    const o = document.createElement("option");
    o.value = d;
    o.textContent = d === selectedDate && !hasDraft ? `${d}（无草稿）` : d;
    sel.appendChild(o);
  }
  sel.value = selectedDate;
}

function renderItems() {
  const list = $("#itemList");
  list.innerHTML = "";
  if (!items.length) {
    list.innerHTML = `<div class="side-tip">没有解析到条目</div>`;
  } else {
    for (const it of items) {
      const row = document.createElement("div");
      row.className = "item";
      row.innerHTML = `
        <label class="item-main" title="勾选编入终稿">
          <input type="checkbox" ${picks.has(it.no) ? "checked" : ""}>
          <span class="no">#${it.no}</span>
          <span class="cat">${it.category}</span>
          <span class="t">${it.has_img ? "🖼 " : ""}${it.title}</span>
        </label>
        <button class="single-btn" title="单条导出：只导出这一条">⬇</button>`;
      row.querySelector("input").addEventListener("change", (e) => {
        e.target.checked ? picks.add(it.no) : picks.delete(it.no);
      });
      row.querySelector(".single-btn").addEventListener("click", async (e) => {
        e.preventDefault();
        status(`单条导出中（#${it.no}）…`);
        const r = await api("/api/export-single", { date, no: it.no });
        if (!r.ok) { status(r.error || "单条导出失败", true); return; }
        status(`✅ 单条已导出：output/${r.name}（${r.title}）`);
        window.open(outputUrl(r.path || `${date}/${r.name}`), "_blank");
      });
      list.appendChild(row);
    }
  }
  renderNav();
  renderImageShelf();
}

function renderImageShelf() {
  const shelf = $("#imageShelf");
  const imageItems = items.filter((it) => it.needs_image);
  shelf.innerHTML = "";
  shelf.hidden = !imageItems.length;
  if (!imageItems.length) return;

  const head = document.createElement("div");
  head.className = "image-shelf-head";
  head.innerHTML = `<strong>📷 资讯截图存放区 <span class="image-shelf-count">（共 ${items.length} 条资讯）</span></strong><span>点击对应卡片后 Ctrl+V，自动保存、命名并放入该条资讯</span>`;
  shelf.appendChild(head);

  const cards = document.createElement("div");
  cards.className = "image-slot-list";
  for (const it of imageItems) {
    const card = document.createElement("article");
    card.className = "image-slot" + (it.has_img ? " filled" : "");
    card.tabIndex = 0;
    card.dataset.no = String(it.no);
    card.title = `点击后粘贴 #${it.no} 的截图`;

    const meta = document.createElement("div");
    meta.className = "image-slot-meta";
    const label = document.createElement("strong");
    label.textContent = `#${it.no} ${it.title}`;
    const tip = document.createElement("span");
    tip.textContent = it.has_img ? "已有截图 · 再粘贴可替换" : "待截图 · 点击后 Ctrl+V";
    meta.append(label, tip);
    card.appendChild(meta);

    if (it.image_path) {
      const img = document.createElement("img");
      img.src = resolveOutputAsset(it.image_path);
      img.alt = `${it.title} 截图预览`;
      card.appendChild(img);
    } else {
      const empty = document.createElement("div");
      empty.className = "image-slot-empty";
      empty.textContent = "粘贴截图到这里";
      card.appendChild(empty);
    }
    card.addEventListener("click", () => card.focus());
    card.addEventListener("paste", (e) => pasteItemImage(e, it.no));
    cards.appendChild(card);
  }
  shelf.appendChild(cards);
}

async function fileToDataUrl(file) {
  return await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

async function pasteItemImage(event, no) {
  const found = [...(event.clipboardData?.items || [])].find((item) => item.type.startsWith("image/"));
  if (!found) {
    status(`剪贴板里没有图片，请先截图，再选中 #${no} 卡片按 Ctrl+V`, true);
    return;
  }
  event.preventDefault();
  const card = event.currentTarget;
  card.classList.add("uploading");
  status(`正在保存 #${no} 的截图…`);
  try {
    const data = await fileToDataUrl(found.getAsFile());
    const r = await api("/api/item-image", { date, no, data });
    if (!r.ok) { status(r.error || "截图保存失败", true); return; }
    $("#editor").value = r.content;
    items = r.items || items;
    renderItems();
    renderPreview();
    status(`✅ #${no} 截图已保存并插入，草稿已自动保存`);
  } catch (err) {
    status(`截图保存失败：${err.message}`, true);
  } finally {
    card.classList.remove("uploading");
  }
}

// 条目导航：点击编号 → 编辑器光标跳到条目标题行，预览精准定位到对应标题
function renderNav() {
  const nav = $("#navBar");
  nav.innerHTML = "";
  for (const it of items) {
    const b = document.createElement("button");
    b.className = "nav-chip";
    b.textContent = "#" + it.no;
    b.title = `${it.category}｜${it.title}`;
    b.addEventListener("click", () => jumpToItem(it.no));
    nav.appendChild(b);
  }
}

function jumpToItem(no) {
  const ta = $("#editor");
  const lines = ta.value.split("\n");
  const re = new RegExp("^## .*`#" + no + "`\\s*$");
  let lineIdx = -1;
  for (let i = 0; i < lines.length; i++) {
    if (re.test(lines[i])) { lineIdx = i; break; }
  }
  if (lineIdx < 0) { status(`草稿里没找到条目 #${no} 的标题行（可能已被改掉）`, true); return; }

  // 编辑器：光标放到该行行首，浏览器自动滚到光标处
  const pos = lines.slice(0, lineIdx).join("\n").length + (lineIdx ? 1 : 0);
  ta.focus();
  ta.setSelectionRange(pos, pos);

  // 短暂锁定滚动同步，避免比例同步干扰预览的精准定位
  syncSource = "#editor";
  clearTimeout(syncTimer);
  syncTimer = setTimeout(() => { syncSource = null; }, 300);

  const target = [...$("#preview").querySelectorAll("h2")]
    .find((h) => h.textContent.trim().endsWith("#" + no));
  if (target) target.scrollIntoView({ block: "start", behavior: "smooth" });
}

function renderPreview() {
  const src = $("#editor").value;
  let html;
  try {
    html = marked.parse(src);
  } catch {
    html = "<p>预览解析失败</p>";
  }
  // Obsidian 的 ![[文件名]] 语法：预览里显示为提示块（图片本体在 Obsidian 附件库里）
  html = html.replace(/!\[\[([^\]]+)\]\]/g, (m, name) =>
    `<div class="ob-img">📎 Obsidian 附件图片：${name} —— 控制中心预览读不到该图；建议删除此行，在编辑器里把截图重新 Ctrl+V 粘贴（会存入 assets/ 并用标准语法引用）</div>`
  );
  // 相对路径资源（assets/...）指向 output/{date}/ 下的静态服务
  html = html.replace(/(src|href)="(?!https?:|data:|\/|#)([^"]+)"/g, (m, a, p) => `${a}="${resolveOutputAsset(p)}"`);
  $("#preview").innerHTML = html;
  // 预览里加载失败的图片（尚未补的占位图）替换成明确的提示框，而不是破图
  $("#preview").querySelectorAll("img").forEach((img) => {
    img.addEventListener("error", () => {
      const div = document.createElement("div");
      div.className = "ob-img";
      div.textContent = "📷 待补截图：" + (img.getAttribute("alt") || "截图未添加");
      img.replaceWith(div);
    });
  });
}

function closeExportPreview() {
  $("#exportPreview").hidden = true;
  exportOrder = [];
}

function moveExportItem(from, to) {
  if (from === to || from < 0 || to < 0 || from >= exportOrder.length || to >= exportOrder.length) return;
  const [moved] = exportOrder.splice(from, 1);
  exportOrder.splice(to, 0, moved);
  renderExportPreview();
}

function renderExportPreview() {
  const list = $("#exportPreviewList");
  list.innerHTML = "";
  exportOrder.forEach((it, index) => {
    const card = document.createElement("article");
    card.className = "export-preview-card";
    card.draggable = true;
    card.dataset.index = String(index);
    card.innerHTML = `
      <div class="drag-handle" title="按住拖动调整顺序" aria-hidden="true">⠿</div>
      <div class="export-position">${index + 1}</div>
      <div class="export-card-content">
        <div><span class="cat">${it.category}</span>${it.has_img ? '<span class="image-mark">🖼 已配图</span>' : ""}</div>
        <h3>${it.title}</h3>
        <div class="original-no">原草稿 #${it.no}</div>
      </div>
      <div class="order-buttons">
        <button class="move-up" title="上移" aria-label="上移${it.title}" ${index === 0 ? "disabled" : ""}>↑</button>
        <button class="move-down" title="下移" aria-label="下移${it.title}" ${index === exportOrder.length - 1 ? "disabled" : ""}>↓</button>
      </div>`;
    card.querySelector(".move-up").addEventListener("click", () => moveExportItem(index, index - 1));
    card.querySelector(".move-down").addEventListener("click", () => moveExportItem(index, index + 1));
    card.addEventListener("dragstart", (e) => {
      card.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", String(index));
    });
    card.addEventListener("dragend", () => card.classList.remove("dragging"));
    card.addEventListener("dragover", (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      card.classList.add("drag-over");
    });
    card.addEventListener("dragleave", () => card.classList.remove("drag-over"));
    card.addEventListener("drop", (e) => {
      e.preventDefault();
      card.classList.remove("drag-over");
      moveExportItem(Number(e.dataTransfer.getData("text/plain")), index);
    });
    list.appendChild(card);
  });
  $("#exportPreviewCount").textContent = `共 ${exportOrder.length} 条 · 拖动后将按 1–${exportOrder.length} 重新编号`;
}

function defaultExportTitle(d) {
  const parts = String(d || "").split("-");
  const suffix = parts.length === 3 ? `${parts[1].padStart(2, "0")}${parts[2].padStart(2, "0")}` : "";
  return `今日资讯 | AI日报${suffix}`;
}

function openExportPreview() {
  exportOrder = items.filter((it) => picks.has(it.no));
  if (!exportOrder.length) {
    status("请先在左侧勾选要编入终稿的条目", true);
    return;
  }
  renderExportPreview();
  const titleInput = $("#exportTitle");
  titleInput.value = defaultExportTitle(date);
  $("#includeSources").checked = false;
  $("#exportPreview").hidden = false;
  titleInput.focus();
  titleInput.setSelectionRange(0, "今日资讯".length);
}

async function confirmExport() {
  if (!exportOrder.length) return;
  const orderedPicks = exportOrder.map((it) => it.no);
  const title = $("#exportTitle").value.trim();
  const includeSources = $("#includeSources").checked;
  const btn = $("#confirmExportBtn");
  btn.disabled = true;
  btn.textContent = "导出中…";
  status("导出中…");
  try {
    const r = await api("/api/export", {
      date, picks: orderedPicks, title, include_sources: includeSources,
    });
    if (!r.ok) { status(r.error || "导出失败", true); return; }
    closeExportPreview();
    status(`✅ 终稿和 PDF 已导出（${r.selected.length} 条），PDF 图片已内嵌，正在打开…`);
    const mdUrl = outputUrl(r.path || `${date}/${r.name}`);
    const pdfUrl = outputUrl(r.pdf_path || `${date}/${r.pdf_name}`);
    $("#finalLink").innerHTML = `<a href="${pdfUrl}" target="_blank">查看 PDF ↗</a> · <a href="${mdUrl}" target="_blank">Markdown ↗</a>`;
    window.open(pdfUrl, "_blank");
  } finally {
    btn.disabled = false;
    btn.textContent = "确认并导出";
  }
}

async function loadState(d) {
  const st = await api("/api/state" + (d ? `?date=${encodeURIComponent(d)}` : ""));
  date = st.date;
  renderDateOptions(st.dates, date, !!st.content);
  $("#editor").value = st.content;
  items = st.items || [];
  picks = new Set(items.map((i) => i.no)); // 默认全选
  renderItems();
  renderPreview();
  $("#finalLink").innerHTML = st.final_exists
    ? `<a href="${outputUrl(st.final_path || `${date}/${st.final_name}`)}" target="_blank">已有终稿 ↗</a>` : "";
  if (!st.content) status("该日期没有草稿：先运行 run.bat 生成，或直接粘贴内容后保存");
}

async function save() {
  if (!date) return;
  const r = await api("/api/save", { date, content: $("#editor").value });
  if (!r.ok) { status(r.error || "保存失败", true); return; }
  items = r.items || items;
  renderItems();
  renderPreview();
  status("✅ 已保存 ✓ " + new Date().toLocaleTimeString());
}

// 编辑 → 防抖预览
$("#editor").addEventListener("input", () => {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(renderPreview, 300);
});

// 截图粘贴 → 上传 → 插入 markdown
$("#editor").addEventListener("paste", async (e) => {
  const found = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/"));
  if (!found) return; // 普通文本粘贴不受影响
  e.preventDefault();
  status("上传截图中…");
  const blob = found.getAsFile();
  const data = await fileToDataUrl(blob);
  const r = await api("/api/upload-image", { date, data });
  if (!r.ok) { status(r.error || "截图上传失败", true); return; }
  const ta = $("#editor");
  const start = ta.selectionStart ?? ta.value.length;
  const end = ta.selectionEnd ?? start;
  const ins = `\n![](${r.path})\n`;
  ta.value = ta.value.slice(0, start) + ins + ta.value.slice(end);
  ta.selectionStart = ta.selectionEnd = start + ins.length;
  renderPreview();
  status("截图已插入：" + r.path);
});

// 左右滚动同步：按滚动比例映射，带防循环抖动；可用开关关闭
let syncEnabled = true;
let syncSource = null;
let syncTimer = null;

function syncScroll(srcSel, dstSel) {
  if (!syncEnabled) return;
  if (syncSource && syncSource !== srcSel) return; // 另一方正在驱动，避免互相拉扯
  syncSource = srcSel;
  const src = $(srcSel), dst = $(dstSel);
  const srcMax = src.scrollHeight - src.clientHeight;
  const dstMax = dst.scrollHeight - dst.clientHeight;
  if (srcMax > 0 && dstMax > 0) {
    dst.scrollTop = (src.scrollTop / srcMax) * dstMax;
  }
  clearTimeout(syncTimer);
  syncTimer = setTimeout(() => { syncSource = null; }, 150);
}

$("#editor").addEventListener("scroll", () => syncScroll("#editor", "#preview"));
$("#preview").addEventListener("scroll", () => syncScroll("#preview", "#editor"));

$("#syncBtn").addEventListener("click", () => {
  syncEnabled = !syncEnabled;
  $("#syncBtn").textContent = syncEnabled ? "🔄 同步滚动：开" : "🔄 同步滚动：关";
  $("#syncBtn").classList.toggle("primary", syncEnabled);
});

$("#saveBtn").addEventListener("click", save);
$("#refreshBtn").addEventListener("click", async () => {
  status("正在刷新草稿和图片预览…");
  await loadState(date);
  status("✅ 已刷新草稿和图片预览");
});
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); save(); }
});

$("#exportBtn").addEventListener("click", openExportPreview);
$("#confirmExportBtn").addEventListener("click", confirmExport);
$("#cancelExportBtn").addEventListener("click", closeExportPreview);
$("#closeExportPreviewBtn").addEventListener("click", closeExportPreview);
$("#exportPreview").addEventListener("click", (e) => {
  if (e.target === e.currentTarget) closeExportPreview();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("#exportPreview").hidden) closeExportPreview();
});

$("#dateSel").addEventListener("change", (e) => loadState(e.target.value));
$("#allBtn").addEventListener("click", () => { items.forEach((i) => picks.add(i.no)); renderItems(); });
$("#noneBtn").addEventListener("click", () => { picks.clear(); renderItems(); });

function renderRunState(st) {
  const btn = $("#runBtn");
  const log = $("#runLog");
  const logToggle = $("#toggleLogBtn");
  btn.disabled = !!st.running;
  btn.textContent = st.running ? "运行中…" : "▶ 采集/成稿";
  const lines = st.logs || [];
  if (st.running) runLogVisible = true;
  const hasLogs = st.running || lines.length > 0;
  log.hidden = !hasLogs || !runLogVisible;
  logToggle.hidden = !hasLogs;
  logToggle.textContent = runLogVisible ? "关闭运行日志" : "查看运行日志";
  logToggle.setAttribute("aria-expanded", String(runLogVisible));
  log.textContent = lines.join("\n");
  log.scrollTop = log.scrollHeight;
  if (st.running) {
    runWasActive = true;
    if (!runPollTimer) runPollTimer = setInterval(pollRunState, 1500);
    status(`采集/成稿运行中，开始时间：${st.started_at || ""}`);
    return;
  }
  if (!runWasActive) return;
  runWasActive = false;
  clearInterval(runPollTimer);
  runPollTimer = null;
  if (st.returncode === 0) {
    status("✅ 采集/成稿完成，已刷新最新草稿");
    loadState();
  } else {
    status(st.error || `采集/成稿失败，退出码：${st.returncode}`, true);
  }
}

$("#toggleLogBtn").addEventListener("click", () => {
  runLogVisible = !runLogVisible;
  const log = $("#runLog");
  log.hidden = !runLogVisible;
  const btn = $("#toggleLogBtn");
  btn.textContent = runLogVisible ? "关闭运行日志" : "查看运行日志";
  btn.setAttribute("aria-expanded", String(runLogVisible));
  if (runLogVisible) log.scrollTop = log.scrollHeight;
});

async function pollRunState() {
  const st = await api("/api/run-state");
  if (st.ok) renderRunState(st);
}

$("#runBtn").addEventListener("click", async () => {
  status("正在启动采集/成稿…");
  const r = await api("/api/run", {});
  if (!r.ok) { status(r.error || "启动失败", true); return; }
  renderRunState(r.state);
  clearInterval(runPollTimer);
  runPollTimer = setInterval(pollRunState, 1500);
});

async function imageToDataUrl(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const blob = await res.blob();
  return await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

async function copyPublishHtml() {
  status("正在准备发布版富文本…");
  const r = await api("/api/final" + (date ? `?date=${encodeURIComponent(date)}` : ""));
  if (!r.ok) { status(r.error || "读取终稿失败", true); return; }
  let html;
  try {
    html = marked.parse(r.content);
  } catch {
    status("终稿 Markdown 解析失败", true);
    return;
  }
  html = html.replace(/!\[\[([^\]]+)\]\]/g, (m, name) =>
    `<p>Obsidian 附件图片未内嵌：${name}</p>`
  );
  const box = document.createElement("div");
  box.innerHTML = html;
  const failed = [];
  for (const img of box.querySelectorAll("img")) {
    const raw = img.getAttribute("src") || "";
    if (!raw || /^(https?:|data:)/i.test(raw)) continue;
    const url = resolveOutputAsset(raw);
    try {
      img.setAttribute("src", await imageToDataUrl(url));
    } catch {
      failed.push(raw);
    }
  }
  const plain = r.content;
  const publishHtml = `<article class="ai-daily">${box.innerHTML}</article>`;
  try {
    if (!navigator.clipboard || !window.ClipboardItem) throw new Error("当前浏览器不支持富文本剪贴板");
    await navigator.clipboard.write([
      new ClipboardItem({
        "text/html": new Blob([publishHtml], { type: "text/html" }),
        "text/plain": new Blob([plain], { type: "text/plain" }),
      }),
    ]);
    status(failed.length
      ? `已复制发布版，但 ${failed.length} 张本地图片未能内嵌：${failed.join("、")}`
      : `✅ 已复制发布版：${r.name}，图片已尽量内嵌`);
  } catch (err) {
    try {
      await navigator.clipboard.writeText(plain);
      status(`已复制纯文本；富文本复制不可用：${err.message}`, true);
    } catch {
      status(`复制失败：${err.message}`, true);
    }
  }
}

$("#copyFinalBtn").addEventListener("click", copyPublishHtml);

loadState();
pollRunState();
