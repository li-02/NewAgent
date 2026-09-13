/* AI 早报控制中心前端逻辑 */
const $ = (s) => document.querySelector(s);
let date = null;
let items = [];
let picks = new Set();
let previewTimer = null;
let runPollTimer = null;
let runWasActive = false;
let exportOrder = [];
let exportCoverPath = null;
let exportCoverCustom = false;
let carryoverItems = [];
let carryoverSourceDate = null;
let carryoverPicks = new Set();
let runLogVisible = false;
let draftDirty = false;
function markDraftDirty() { draftDirty = true; const el = $("#draftState"); if (el) { el.textContent = "● 未保存"; el.classList.add("dirty"); } if (date) localStorage.setItem(`ai-daily-draft:${date}`, $("#editor").value); }
function markDraftSaved() { draftDirty = false; const el = $("#draftState"); if (el) { el.textContent = "已保存"; el.classList.remove("dirty"); } if (date) localStorage.removeItem(`ai-daily-draft:${date}`); }
function guardUnsaved(action) {
  if (draftDirty && !confirm("当前草稿有未保存修改，继续操作会丢失，是否继续？")) {
    $("#dateSel").value = date || "";
    return false;
  }
  action();
  return true;
}

// 编辑区不显示条目编号；编号仍由解析器按条目顺序保留，用于导航和导出。
function stripTitleNumbers(text) {
  return String(text || "").replace(
    /^(\s*(?:##|-)\s*.+?)\s+(?:`#\d+`|#\d+)\s*$/gm,
    "$1"
  );
}

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
        <label class="item-check" title="勾选编入终稿">
          <input type="checkbox" ${picks.has(it.no) ? "checked" : ""}>
        </label>
        <span class="no">#${it.no}</span>
        <span class="cat">${it.category}</span>
        <span class="t">${it.has_img ? "🖼 " : ""}${it.title}</span>
        <button class="single-btn" title="单条导出：只导出这一条">⬇</button>`;
      row.title = `点击跳转到 #${it.no}`;
      row.addEventListener("click", (e) => {
        if (e.target.closest(".item-check, .source-link, .single-btn")) return;
        jumpToItem(it.no);
      });
      row.querySelector("input").addEventListener("change", (e) => {
        e.target.checked ? picks.add(it.no) : picks.delete(it.no);
      });
      if (it.links?.length) {
        const sourceLink = document.createElement("a");
        sourceLink.className = "source-link";
        sourceLink.href = it.links[0];
        sourceLink.target = "_blank";
        sourceLink.rel = "noopener noreferrer";
        sourceLink.textContent = "原文";
        sourceLink.title = "打开原文链接";
        row.querySelector(".t").insertAdjacentElement("afterend", sourceLink);
      }
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
  renderImageShelf();
}

function renderCarryover() {
  const panel = $("#carryoverPanel");
  panel.hidden = !carryoverItems.length;
  if (!carryoverItems.length) return;
  $("#carryoverTitle").textContent = `${carryoverSourceDate} 未导出（${carryoverItems.length}）`;
  const list = $("#carryoverList");
  list.innerHTML = "";
  for (const item of carryoverItems) {
    const row = document.createElement("label");
    row.className = "carryover-item";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = carryoverPicks.has(item.key);
    input.addEventListener("change", () => {
      input.checked ? carryoverPicks.add(item.key) : carryoverPicks.delete(item.key);
      $("#addCarryoverBtn").disabled = !carryoverPicks.size;
    });
    const cat = document.createElement("span");
    cat.className = "cat";
    cat.textContent = item.category;
    const title = document.createElement("span");
    title.className = "t";
    title.textContent = `${item.has_img ? "🖼 " : ""}${item.title}`;
    row.append(input, cat, title);
    list.appendChild(row);
  }
  $("#addCarryoverBtn").disabled = !carryoverPicks.size;
}

async function loadCarryover() {
  const result = await api(`/api/carryover?date=${encodeURIComponent(date)}`);
  carryoverItems = result.ok ? (result.items || []) : [];
  carryoverSourceDate = result.source_date || null;
  carryoverPicks = new Set();
  renderCarryover();
}

function renderImageShelf() {
  const shelf = $("#imageShelf");
  // Every article gets a slot. A pre-generated Markdown placeholder is optional:
  // the item-image endpoint can insert the managed image region on first paste.
  const imageItems = items;
  shelf.innerHTML = "";
  shelf.hidden = !imageItems.length;
  const shelfSplitter = $("#shelfSplitter");
  if (shelfSplitter) shelfSplitter.hidden = shelf.hidden;
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
    if (it.image_path) {
      const copyButton = document.createElement("button");
      copyButton.type = "button";
      copyButton.className = "image-copy-btn";
      copyButton.textContent = "复制图片";
      copyButton.setAttribute("aria-label", `复制 #${it.no} 的截图`);
      copyButton.title = `复制 #${it.no} 的截图到剪贴板`;
      copyButton.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        copyShelfImage(it, copyButton);
      });
      meta.appendChild(copyButton);
    }
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

async function copyShelfImage(item, button) {
  if (!navigator.clipboard?.write || !window.ClipboardItem) {
    status("当前浏览器不支持复制图片，请使用支持图片剪贴板的浏览器", true);
    return;
  }
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "复制中…";
  try {
    const response = await fetch(resolveOutputAsset(item.image_path));
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const blob = await response.blob();
    if (!blob.type.startsWith("image/")) throw new Error("资源不是图片");
    await navigator.clipboard.write([new ClipboardItem({ [blob.type]: blob })]);
    status(`✅ #${item.no} 截图已复制，可直接粘贴到聊天或文档`);
    button.textContent = "已复制";
    setTimeout(() => { button.textContent = originalText; }, 1500);
  } catch (err) {
    status(`图片复制失败：${err.message}`, true);
  } finally {
    button.disabled = false;
    if (button.textContent === "复制中…") button.textContent = originalText;
  }
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
    if (draftDirty) {
      await save();
      if (draftDirty) { status("未保存草稿，已中止截图上传", true); return; }
    }
    const data = await fileToDataUrl(found.getAsFile());
    const r = await api("/api/item-image", { date, no, data });
    if (!r.ok) { status(r.error || "截图保存失败", true); return; }
    $("#editor").value = stripTitleNumbers(r.content);
    markDraftSaved();
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

function jumpToItem(no) {
  const ta = $("#editor");
  const lines = ta.value.split("\n");
  const item = items.find((it) => it.no === no);
  const title = item?.title || "";
  let lineIdx = -1;
  for (let i = 0; i < lines.length; i++) {
    const match = lines[i].match(/^## (.+?)(?:\s+`#\d+`|\s+#\d+)?\s*$/);
    if (match && match[1].trim() === title) { lineIdx = i; break; }
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
    .find((h) => h.textContent.trim().replace(/\s+#\d+$/, "") === (items.find((it) => it.no === no)?.title || ""));
  if (target) target.scrollIntoView({ block: "start", behavior: "smooth" });
}

function isCopyableUrl(value) {
  return /^https?:\/\//i.test(String(value || "").trim());
}

async function copyLink(value, button) {
  const text = String(value || "").trim();
  if (!text) return;
  const defaultLabel = button.dataset.defaultLabel || button.textContent;
  button.dataset.defaultLabel = defaultLabel;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const input = document.createElement("textarea");
      input.value = text;
      input.setAttribute("readonly", "");
      input.style.position = "fixed";
      input.style.opacity = "0";
      document.body.appendChild(input);
      input.select();
      if (!document.execCommand("copy")) throw new Error("浏览器拒绝了复制操作");
      input.remove();
    }
    button.textContent = "已复制";
    button.classList.add("copied");
    status("✅ 链接已复制");
    setTimeout(() => {
      button.textContent = defaultLabel;
      button.classList.remove("copied");
    }, 1600);
  } catch (err) {
    status(`复制失败：${err.message}`, true);
  }
}

function addLinkCopyButtons(container) {
  // 文章里的原文链接通常位于 fenced code block；整块复制可兼容多链接场景。
  container.querySelectorAll("pre").forEach((pre) => {
    const text = pre.textContent.trim();
    const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    if (!lines.length || !lines.every(isCopyableUrl)) return;
    const wrap = document.createElement("div");
    wrap.className = "link-copy-wrap";
    pre.parentNode.insertBefore(wrap, pre);
    wrap.appendChild(pre);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "link-copy-btn";
    button.textContent = lines.length === 1 ? "复制链接" : "复制全部链接";
    button.title = lines.length === 1 ? "复制原文链接" : "复制代码块中的全部原文链接";
    button.addEventListener("click", () => copyLink(lines.join("\n"), button));
    wrap.appendChild(button);
  });

  // 同时支持正文中使用 Markdown [文字](URL) 写出的链接。
  container.querySelectorAll("a[href]").forEach((link) => {
    const url = link.href;
    if (!isCopyableUrl(url) || link.nextElementSibling?.classList.contains("inline-link-copy")) return;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "inline-link-copy";
    button.textContent = "复制";
    button.title = "复制链接";
    button.addEventListener("click", () => copyLink(url, button));
    link.insertAdjacentElement("afterend", button);
  });
}

function renderPreview() {
  const src = stripTitleNumbers($("#editor").value);
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
  addLinkCopyButtons($("#preview"));
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
  if (!exportCoverCustom) exportCoverPath = exportOrder[0]?.image_path || null;
  renderExportPreview();
}

function renderExportCover() {
  const preview = $("#exportCoverPreview");
  const path = exportCoverPath;
  preview.innerHTML = path
    ? `<img src="${resolveOutputAsset(path)}" alt="导出封面预览">`
    : "<span>暂无可用图片</span>";
  $("#exportCoverStatus").textContent = path
    ? (exportCoverCustom ? "已上传并自动保存" : "默认取第一篇文章的第一张图片")
    : "第一篇文章暂无图片，可上传封面";
  $("#resetExportCoverBtn").hidden = !exportCoverCustom;
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
  renderExportCover();
  $("#exportPreviewCount").textContent = `共 ${exportOrder.length} 条 · 拖动后将按 1–${exportOrder.length} 重新编号`;
}

function defaultExportTitle(d) {
  const parts = String(d || "").split("-");
  const suffix = parts.length === 3 ? `${parts[1].padStart(2, "0")}${parts[2].padStart(2, "0")}` : "";
  return `今日资讯 | AI日报${suffix}`;
}

async function openExportPreview() {
  exportOrder = items.filter((it) => picks.has(it.no));
  if (!exportOrder.length) {
    status("请先在左侧勾选要编入终稿的条目", true);
    return;
  }
  exportCoverCustom = false;
  exportCoverPath = exportOrder[0]?.image_path || null;
  renderExportPreview();
  let warnings = [];
  try {
    const check = await api("/api/export-check", { date, picks: exportOrder.map((it) => it.no) });
    warnings = check.warnings || [];
  } catch (error) {
    warnings = [`检查失败：${error.message}（仍可继续导出）`];
  }
  const warningNode = $("#exportPreviewWarning");
  warningNode.textContent = warnings.length ? `⚠ 导出前检查提醒（仍可继续）：${warnings.join("；")}` : "✅ 导出前检查通过";
  warningNode.className = warnings.length ? "export-preview-warning warn" : "export-preview-warning ok";
  const titleInput = $("#exportTitle");
  titleInput.value = defaultExportTitle(date);
  $("#includeSources").checked = false;
  $("#includeOverview").checked = false;
  $("#exportPreview").hidden = false;
  titleInput.focus();
  titleInput.setSelectionRange(0, "今日资讯".length);
}

async function confirmExport() {
  if (!exportOrder.length) return;
  const orderedPicks = exportOrder.map((it) => it.no);
  const title = $("#exportTitle").value.trim();
  const includeSources = $("#includeSources").checked;
  const includeOverview = $("#includeOverview").checked;
  const btn = $("#confirmExportBtn");
  btn.disabled = true;
  btn.textContent = "导出中…";
  status("导出中…");
  try {
    const r = await api("/api/export", {
      date, picks: orderedPicks, title,
      include_sources: includeSources, include_overview: includeOverview,
      cover_path: exportCoverPath,
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

$("#uploadExportCoverBtn").addEventListener("click", () => $("#exportCoverFile").click());
$("#exportCoverFile").addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;
  try {
    status("正在保存导出封面…");
    const r = await api("/api/export-cover", { date, data: await fileToDataUrl(file) });
    if (!r.ok) { status(r.error || "封面上传失败", true); return; }
    exportCoverPath = r.path;
    exportCoverCustom = true;
    renderExportCover();
    status("✅ 导出封面已自动保存");
  } catch (error) { status(`封面上传失败：${error.message}`, true); }
});
$("#resetExportCoverBtn").addEventListener("click", () => {
  exportCoverCustom = false;
  exportCoverPath = exportOrder[0]?.image_path || null;
  renderExportCover();
});

async function loadState(d) {
  const st = await api("/api/state" + (d ? `?date=${encodeURIComponent(d)}` : ""));
  date = st.date;
  renderDateOptions(st.dates, date, !!st.content);
  const incoming = stripTitleNumbers(st.content);
  $("#editor").value = incoming;
  const backup = date ? localStorage.getItem(`ai-daily-draft:${date}`) : null;
  if (backup && backup !== incoming && confirm("发现该日期的本地恢复草稿，是否恢复？")) { $("#editor").value = backup; markDraftDirty(); status("已恢复本地草稿，请确认后保存"); } else markDraftSaved();
  items = st.items || [];
  picks = new Set(items.map((i) => i.no)); // 默认全选
  renderItems();
  renderPreview();
  await loadCarryover();
  $("#finalLink").innerHTML = st.final_exists
    ? `<a href="${outputUrl(st.final_path || `${date}/${st.final_name}`)}" target="_blank">已有终稿 ↗</a>` : "";
  if (!st.content) status("该日期没有草稿：先运行 run.bat 生成，或直接粘贴内容后保存");
}

async function save() {
  if (!date) return;
  const r = await api("/api/save", { date, content: stripTitleNumbers($("#editor").value) });
  if (!r.ok) { status(r.error || "保存失败", true); return; }
  items = r.items || items;
  renderItems();
  renderPreview();
  await loadCarryover();
  markDraftSaved();
  status("✅ 已保存 ✓ " + new Date().toLocaleTimeString());
}

$("#addCarryoverBtn").addEventListener("click", async () => {
  if (!carryoverPicks.size) return;
  status("正在加入昨日文章…");
  const result = await api("/api/carryover", {
    date, source_date: carryoverSourceDate, keys: [...carryoverPicks],
  });
  if (!result.ok) { status(result.error || "加入昨日文章失败", true); return; }
  $("#editor").value = stripTitleNumbers(result.content || "");
  items = result.items || [];
  picks = new Set(items.map((item) => item.no));
  renderItems();
  renderPreview();
  markDraftSaved();
  await loadCarryover();
  status(result.added ? `✅ 已加入 ${result.added} 篇昨日文章` : "所选文章已在今天草稿中");
});

// 编辑 → 防抖预览
$("#editor").addEventListener("input", () => {
  markDraftDirty();
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

$("#toggleEditorBtn").addEventListener("click", () => {
  const editor = $("#editor");
  editor.hidden = !editor.hidden;
  const expanded = !editor.hidden;
  const btn = $("#toggleEditorBtn");
  btn.textContent = expanded ? "✏ 隐藏编辑区" : "✏ 展开编辑区";
  btn.setAttribute("aria-expanded", String(expanded));
  const editorSplitter = $("#editorSplitter");
  if (editorSplitter) editorSplitter.hidden = editor.hidden;
  if (expanded) editor.focus();
});

$("#saveBtn").addEventListener("click", save);
$("#refreshBtn").addEventListener("click", async () => {
  if (draftDirty && !confirm("当前草稿有未保存修改，刷新会丢失，是否继续？")) return;
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

$("#dateSel").addEventListener("change", (e) => guardUnsaved(() => loadState(e.target.value)));
$("#allBtn").addEventListener("click", () => { items.forEach((i) => picks.add(i.no)); renderItems(); });
$("#noneBtn").addEventListener("click", () => { picks.clear(); renderItems(); });

function renderRunState(st) {
  const btn = $("#runBtn");
  const log = $("#runLog");
  const logToggle = $("#toggleLogBtn");
  const copyLogBtn = $("#copyRunLogBtn");
  const summaryNode = $("#runSummary");
  btn.disabled = !!st.running;
  btn.textContent = st.running ? "运行中…" : "▶ 采集/成稿";
  const lines = st.logs || [];
  if (st.running) runLogVisible = true;
  const hasLogs = st.running || lines.length > 0;
  log.hidden = !hasLogs || !runLogVisible;
  logToggle.hidden = !hasLogs;
  copyLogBtn.hidden = !hasLogs;
  logToggle.textContent = runLogVisible ? "关闭运行日志" : "查看运行日志";
  logToggle.setAttribute("aria-expanded", String(runLogVisible));
  log.textContent = lines.join("\n");
  const summary = st.summary;
  if (summaryNode && summary) {
    const failed = summary.failed_sources?.length || 0;
    summaryNode.textContent = `本次摘要：抓取 ${summary.fetched || 0} 条 · 入选 ${summary.kept || 0} 条${failed ? ` · 失败来源 ${failed} 个` : " · 来源正常"}`;
    summaryNode.title = failed ? summary.failed_sources.join("\n") : "";
  }
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
    if (draftDirty) status("✅ 采集完成；当前有未保存草稿，已跳过自动刷新", true);
    else loadState();
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

$("#copyRunLogBtn").addEventListener("click", async () => {
  const text = $("#runLog").textContent || "";
  if (!text.trim()) return;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const input = document.createElement("textarea");
      input.value = text;
      input.setAttribute("readonly", "");
      input.style.position = "fixed";
      input.style.opacity = "0";
      document.body.appendChild(input);
      input.select();
      if (!document.execCommand("copy")) throw new Error("浏览器拒绝了复制操作");
      input.remove();
    }
    status("✅ 运行日志已复制");
  } catch (err) {
    status(`复制日志失败：${err.message}`, true);
  }
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

window.addEventListener("beforeunload", (event) => { if (!draftDirty) return; event.preventDefault(); event.returnValue = ""; });

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

/* ── 区域宽度自由调整：条目选择区 / 截图区 / 编辑区三条拖拽分隔条，宽度记入 localStorage ── */
const LAYOUT_KEY = "ai-daily-layout-v1";
const DEFAULT_LAYOUT = { aside: 300, shelf: 250, editor: 50 };
let layout = { ...DEFAULT_LAYOUT };
try { Object.assign(layout, JSON.parse(localStorage.getItem(LAYOUT_KEY) || "{}")); } catch { /* 忽略损坏的历史配置 */ }
const clampWidth = (v, lo, hi) => Math.round(Math.min(Math.max(v, lo), hi));

function applyLayout() {
  const root = document.documentElement.style;
  root.setProperty("--aside-w", `${clampWidth(layout.aside, 160, window.innerWidth * .6)}px`);
  root.setProperty("--shelf-w", `${clampWidth(layout.shelf, 140, window.innerWidth * .5)}px`);
  root.setProperty("--editor-w", `${clampWidth(layout.editor, 15, 85)}%`);
}
function saveLayout() { localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout)); }

function setupSplitter(el, { begin, update, reset }) {
  if (!el) return;
  el.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    const startX = e.clientX;
    const start = begin();
    try { el.setPointerCapture(e.pointerId); } catch { /* 合成事件没有活动指针，忽略 */ }
    el.classList.add("dragging");
    document.body.classList.add("col-resizing");
    const move = (ev) => update(start, ev.clientX - startX);
    const up = () => {
      el.classList.remove("dragging");
      document.body.classList.remove("col-resizing");
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", up);
      saveLayout();
    };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
  });
  el.addEventListener("dblclick", () => { reset(); applyLayout(); saveLayout(); });
}

applyLayout();
window.addEventListener("resize", applyLayout);
setupSplitter($("#asideSplitter"), {
  begin: () => layout.aside,
  update: (s, dx) => { layout.aside = s + dx; applyLayout(); },
  reset: () => { layout.aside = DEFAULT_LAYOUT.aside; },
});
setupSplitter($("#shelfSplitter"), {
  begin: () => layout.shelf,
  update: (s, dx) => { layout.shelf = s + dx; applyLayout(); },
  reset: () => { layout.shelf = DEFAULT_LAYOUT.shelf; },
});
setupSplitter($("#editorSplitter"), {
  begin: () => layout.editor,
  update: (s, dx) => {
    const panesWidth = $("#panes").getBoundingClientRect().width || 1;
    layout.editor = s + (dx / panesWidth) * 100; applyLayout();
  },
  reset: () => { layout.editor = DEFAULT_LAYOUT.editor; },
});
$("#editorSplitter").hidden = $("#editor").hidden;

loadState();
pollRunState();
