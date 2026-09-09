const $ = (selector) => document.querySelector(selector);
const TYPE_LABELS = {
  rss: "RSS / Atom",
  page_watch: "页面变更追踪",
  article_index: "文章目录",
  huggingface: "Hugging Face 模型",
  github_org: "GitHub 机构仓库",
  x_account: "X 官方账号",
  model_catalog: "模型服务目录",
  changelog: "更新日志",
  html_updates: "HTML 更新页",
  hackernews: "Hacker News",
};

let sources = [];
let editingIndex = null;
let dirty = false;

async function requestJson(path, { method = "GET", body } = {}) {
  const response = await fetch(path, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let payload;
  try { payload = await response.json(); }
  catch { payload = { ok: false, error: "服务返回了无法解析的内容" }; }
  if (!response.ok || payload.ok === false) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

function setState(message, error = false) {
  const state = $("#saveState");
  state.textContent = message;
  state.className = `settings-state ${error ? "err" : "ok"}`;
}

function markDirty() {
  dirty = true;
  setState("有未保存修改");
}

function sourceMatches(source, query) {
  if (!query) return true;
  return [source.name, source.type, source.url, source.site, source.category]
    .filter(Boolean).join(" ").toLowerCase().includes(query.toLowerCase());
}

function renderSources() {
  const list = $("#sourceList");
  const query = $("#sourceFilter").value.trim();
  list.replaceChildren();
  const visible = sources.map((source, index) => ({ source, index }))
    .filter(({ source }) => sourceMatches(source, query));
  const enabledCount = sources.filter((source) => source.enabled !== false).length;
  $("#sourceCount").textContent = `${sources.length} 个信息源 · ${enabledCount} 个已启用`;

  if (!visible.length) {
    const empty = document.createElement("div");
    empty.className = "empty-sources";
    empty.textContent = query ? "没有匹配的信息源" : "还没有信息源，先新增一个 RSS 吧。";
    list.appendChild(empty);
    return;
  }

  visible.forEach(({ source, index }) => {
    const card = document.createElement("article");
    card.className = `source-card${source.enabled === false ? " disabled" : ""}`;

    const toggleLabel = document.createElement("label");
    toggleLabel.className = "source-toggle";
    toggleLabel.title = source.enabled === false ? "启用" : "停用";
    const toggle = document.createElement("input");
    toggle.type = "checkbox";
    toggle.checked = source.enabled !== false;
    toggle.addEventListener("change", () => {
      source.enabled = toggle.checked;
      markDirty();
      renderSources();
    });
    toggleLabel.appendChild(toggle);

    const main = document.createElement("div");
    main.className = "source-card-main";
    const titleRow = document.createElement("div");
    titleRow.className = "source-card-title";
    const title = document.createElement("h2");
    title.textContent = source.name || "未命名来源";
    const type = document.createElement("span");
    type.className = "source-type";
    type.textContent = TYPE_LABELS[source.type] || source.type;
    titleRow.append(title, type);
    const url = document.createElement("div");
    url.className = "source-card-url";
    url.textContent = source.url || "内置 API，无需 URL";
    const meta = document.createElement("div");
    meta.className = "source-card-meta";
    meta.textContent = `分类：${source.category || "news"}　权重：${source.weight ?? 1}${source.require_ai ? "　仅 AI" : ""}`;
    main.append(titleRow, url, meta);

    const actions = document.createElement("div");
    actions.className = "source-card-actions";
    const testButton = document.createElement("button");
    testButton.textContent = "测试";
    testButton.addEventListener("click", () => testExistingSource(index, testButton));
    const editButton = document.createElement("button");
    editButton.textContent = "编辑";
    editButton.addEventListener("click", () => openDialog(index));
    const deleteButton = document.createElement("button");
    deleteButton.className = "danger";
    deleteButton.textContent = "删除";
    deleteButton.addEventListener("click", () => {
      if (!confirm(`删除信息源“${source.name}”？保存全部后才会写入配置。`)) return;
      sources.splice(index, 1);
      markDirty();
      renderSources();
    });
    actions.append(testButton, editButton, deleteButton);
    card.append(toggleLabel, main, actions);
    list.appendChild(card);
  });
}

function defaultSource(type = "rss") {
  return { name: "", type, url: "", enabled: true, weight: 1, category: "news", require_ai: false };
}

function openDialog(index = null, preferredType = "rss") {
  editingIndex = index;
  const source = index === null ? defaultSource(preferredType) : sources[index];
  $("#sourceDialogTitle").textContent = index === null ? "新增信息源" : "编辑信息源";
  $("#fieldName").value = source.name || "";
  $("#fieldType").value = source.type || "rss";
  $("#fieldUrl").value = source.url || "";
  $("#fieldWeight").value = source.weight ?? 1;
  $("#fieldCategory").value = source.category || "news";
  $("#fieldEnabled").checked = source.enabled !== false;
  $("#fieldRequireAi").checked = source.require_ai === true;
  $("#fieldLinkBase").value = source.link_base || "";
  $("#fieldItemLimit").value = source.item_limit ?? 5;
  $("#fieldSite").value = source.site || "generic";
  $("#fieldCode").value = source.code || "";
  $("#fieldContentXpath").value = source.content_xpath || "";
  $("#fieldLinkPattern").value = source.link_pattern || "";
  $("#fieldMinScore").value = source.min_score ?? 150;
  $("#testResult").textContent = "";
  $("#testResult").className = "test-result";
  updateTypeFields();
  $("#sourceDialog").showModal();
  $("#fieldName").focus();
}

function updateTypeFields() {
  const type = $("#fieldType").value;
  document.querySelectorAll(".type-fields").forEach((node) => { node.hidden = true; });
  $(".url-field").hidden = type === "hackernews";
  $("#fieldUrl").required = type !== "hackernews";
  if (type === "changelog") $(".changelog-fields").hidden = false;
  if (type === "html_updates") $(".html-fields").hidden = false;
  if (type === "hackernews") $(".hn-fields").hidden = false;
  if (["page_watch", "article_index"].includes(type)) $(".watch-fields").hidden = false;
  $(".pattern-field").hidden = type !== "article_index";
}

function valueOrUndefined(selector) {
  const value = $(selector).value.trim();
  return value || undefined;
}

function sourceFromForm() {
  const type = $("#fieldType").value;
  const source = {
    ...(editingIndex === null ? {} : sources[editingIndex]),
    name: $("#fieldName").value.trim(),
    type,
    enabled: $("#fieldEnabled").checked,
    weight: Number($("#fieldWeight").value || 1),
    category: $("#fieldCategory").value,
    require_ai: $("#fieldRequireAi").checked,
  };
  if (type !== "hackernews") source.url = $("#fieldUrl").value.trim();
  if (type === "changelog") {
    source.format = "markdown";
    source.link_base = valueOrUndefined("#fieldLinkBase");
    source.item_limit = Number($("#fieldItemLimit").value || 5);
  }
  if (type === "html_updates") {
    source.site = $("#fieldSite").value;
    source.code = valueOrUndefined("#fieldCode");
  }
  if (["page_watch", "article_index"].includes(type)) source.content_xpath = valueOrUndefined("#fieldContentXpath");
  if (type === "article_index") source.link_pattern = valueOrUndefined("#fieldLinkPattern");
  if (type === "hackernews") source.min_score = Number($("#fieldMinScore").value || 150);
  return Object.fromEntries(Object.entries(source).filter(([, value]) => value !== undefined));
}

async function testSource(source, button, resultNode = null) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "测试中…";
  try {
    const payload = await requestJson("/api/sources/test", { method: "POST", body: { source } });
    const rows = payload.items || payload.rows || [];
    const message = rows.length
      ? `成功抓取 ${rows.length} 条：${rows.slice(0, 3).map((row) => row.title).join("；")}`
      : "连接成功，但当前没有解析到条目。";
    if (resultNode) {
      resultNode.textContent = message;
      resultNode.className = "test-result ok";
    } else setState(message);
  } catch (error) {
    if (resultNode) {
      resultNode.textContent = `测试失败：${error.message}`;
      resultNode.className = "test-result err";
    } else setState(`测试失败：${error.message}`, true);
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

async function testExistingSource(index, button) {
  await testSource(sources[index], button);
}

async function loadSources() {
  try {
    const payload = await requestJson("/api/sources");
    sources = payload.sources || [];
    dirty = false;
    setState("配置已加载");
    renderSources();
  } catch (error) {
    setState(`读取失败：${error.message}`, true);
    $("#sourceList").innerHTML = '<div class="empty-sources">无法读取信息源配置</div>';
  }
}

async function loadAppSettings() {
  try {
    const payload = await requestJson("/api/settings");
    $("#topN").value = payload.top_n ?? 12;
    $("#timeWindow").value = payload.time_window_hours ?? 26;
    $("#screenshotCount").value = payload.screenshot_count ?? 5;
    $("#maxTextChars").value = payload.max_text_chars ?? 2500;
    $("#llmEnabled").value = String(payload.llm?.enabled ?? "auto");
    $("#llmModel").value = payload.llm?.model ?? "";
    $("#llmBaseUrl").value = payload.llm?.base_url ?? "";
    $("#llmTemperature").value = payload.llm?.temperature ?? 0.7;
    $("#llmKeyState").textContent = payload.llm?.api_key_configured ? "已配置（不显示密钥）" : "未配置";
    for (const [id, key] of [["boostKeywords", "boost_keywords"], ["downrankKeywords", "downrank_keywords"], ["blockKeywords", "block_keywords"]]) $("#" + id).value = (payload.preferences?.[key] || []).join(", ");
  } catch (error) {
    setState(`读取筛选设置失败：${error.message}`, true);
  }
}

async function saveTopN() {
  const button = $("#saveTopNBtn");
  button.disabled = true;
  try {
    const payload = await requestJson("/api/settings", {
      method: "PUT",
      body: { top_n: Number($("#topN").value), time_window_hours: Number($("#timeWindow").value), screenshot_count: Number($("#screenshotCount").value), max_text_chars: Number($("#maxTextChars").value), llm: { enabled: $("#llmEnabled").value === "true" ? true : $("#llmEnabled").value === "false" ? false : "auto", model: $("#llmModel").value.trim(), base_url: $("#llmBaseUrl").value.trim(), temperature: Number($("#llmTemperature").value) }, preferences: { boost_keywords: $("#boostKeywords").value.split(","), downrank_keywords: $("#downrankKeywords").value.split(","), block_keywords: $("#blockKeywords").value.split(",") } },
    });
    $("#topN").value = payload.top_n;
    setState(`已保存采集设置：每天 ${payload.top_n} 条`);
  } catch (error) {
    setState(`保存筛选设置失败：${error.message}`, true);
  } finally {
    button.disabled = false;
  }
}

async function saveSources() {
  const button = $("#saveSourcesBtn");
  button.disabled = true;
  button.textContent = "保存中…";
  try {
    const payload = await requestJson("/api/sources", { method: "PUT", body: { sources } });
    sources = payload.sources || sources;
    dirty = false;
    setState(`已保存 ${sources.length} 个信息源`);
    renderSources();
  } catch (error) {
    setState(`保存失败：${error.message}`, true);
  } finally {
    button.disabled = false;
    button.textContent = "保存全部";
  }
}

$("#sourceForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const source = sourceFromForm();
  if (!source.name || (source.type !== "hackernews" && !source.url)) {
    $("#sourceForm").reportValidity();
    return;
  }
  if (editingIndex === null) sources.push(source);
  else sources[editingIndex] = source;
  markDirty();
  renderSources();
  $("#sourceDialog").close();
});

$("#fieldType").addEventListener("change", updateTypeFields);
$("#addRssBtn").addEventListener("click", () => openDialog(null, "rss"));
$("#addSourceBtn").addEventListener("click", () => openDialog(null, "html_updates"));
$("#saveSourcesBtn").addEventListener("click", saveSources);
$("#sourceFilter").addEventListener("input", renderSources);
$("#closeSourceDialog").addEventListener("click", () => $("#sourceDialog").close());
$("#cancelSourceBtn").addEventListener("click", () => $("#sourceDialog").close());
$("#testSourceBtn").addEventListener("click", () => testSource(sourceFromForm(), $("#testSourceBtn"), $("#testResult")));
$("#saveTopNBtn").addEventListener("click", saveTopN);
window.addEventListener("beforeunload", (event) => {
  if (!dirty) return;
  event.preventDefault();
  event.returnValue = "";
});

loadSources();
loadAppSettings();
