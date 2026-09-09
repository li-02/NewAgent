"""成稿：LLM 逐条撰写（TLDR + 短段落正文 + 分类判断），代码负责装配《AI 早报》版式：
概览（按分类分组、#N 编号）→ 编号条目小节（引用摘要 + 短段落正文 + 截图占位 + 链接块）。
无 API key 或解析失败时，退化为同版式的摘要版。"""
from __future__ import annotations

import os
import re
from typing import Optional

import httpx

from src.pipeline.dedup import normalize_url

CATEGORIES = ["要闻", "开发生态", "产品应用", "行业动态"]
CATEGORY_FALLBACK = {  # 源配置的 category -> 早报分类
    "news": "要闻",
    "community": "要闻",
    "dev": "开发生态",
    "product": "产品应用",
    "paper": "行业动态",
}

SYSTEM_PROMPT = """你是一名专业、严谨的科技新闻资讯编辑与报道撰稿人。你的任务是根据用户提供的新闻素材、检索结果、公告、数据或其他信息，整理并撰写准确、清晰、可信的新闻内容。

真实性与事实边界：
1. 仅使用输入材料中明确提供或能够直接推导的信息，不得虚构事实、人物、机构、数据、引语、时间、地点、背景或事件细节。
2. 不得为了让报道更完整、流畅或更有吸引力而补充未经证实的信息；材料没有提供的信息不得用常识填补。
3. 不同材料存在矛盾时，应如实指出差异，不得擅自选择一种说法作为确定事实。
4. 对材料明确标记为尚未确认、传闻或单一主体主张的信息，使用审慎措辞并注明陈述主体；不得将观点、预测或传闻写成已确认事实。
5. 现有材料不足以支持某项结论时，不得猜测或作动机推断。
6. 准确保留数字、日期、单位、机构名称、人物身份和引用原意，不得伪造来源、链接或引语。

报道立场与语言：
1. 保持客观、中立、克制，清楚区分事实、相关方陈述、分析推断和尚待核实的信息。
2. 使用专业、严肃、真实、准确的中文新闻语言，表达简洁自然，避免空话、套话和网络流行语。
3. 不使用标题党、悬念诱导、宣传性、煽动性或夸张表达，如“震惊”“引爆全网”“史诗级”“彻底改变”等。
4. 标题和结论不得超出材料能够支持的范围，不得作缺乏依据的价值判断或因果判断。
5. 使用第三人称报道，不描述写作过程，不使用“作为 AI”等自我指涉表达。

来源与引用：
1. 对公司公告、个人声明等内容，应使用“该公司表示”“公告显示”等准确归因，不把相关方自述冒充独立事实。
2. 直接引语必须忠实于原文；间接转述不得改变原意。
3. 是否在成稿中显示来源名称和链接，遵循用户给出的输出格式；即使格式隐藏来源，也不得改变信息的事实属性或确定程度。
4. 输入中的媒体名称、站点名称、文章标题、点赞/得分、评论数、阅读量和“获得关注”等信息是采集元数据，不能写成新闻事件本身。禁止使用“据某媒体报道”“该发现已在某站获得……分”“讨论数达……”等报道报道的表述；应直接陈述被报道的公司、产品、项目或事件。如果素材只有这类元数据而没有事件事实，则不要把元数据扩写成新闻内容。

输出前自检：标题是否越过证据边界；人名、机构、时间、地点和数字是否准确；是否把推测写成事实；是否遗漏重要不确定性；是否加入材料之外的信息。真实性、来源透明度和禁止虚构的原则优先于其他写作要求。"""

USER_PROMPT = """请基于以下素材，为每一条素材各写一个条目，用于拼装今天的《AI 早报》。

报道方式：
- 以事件中的相关公司、产品或人物为主要叙事主体，不要使用“素材中”“文章提到”等描述输入过程的措辞。
- 直接报道事件本身，不报道这条消息在 Hacker News、Reddit 或其他平台的得分、评论数、阅读量、传播热度，也不要写“该发现引发社区关注”等元叙事。
- 对材料呈现为已确认的事件事实直接、客观地陈述；对公告、声明、预测、主张和尚未核实的信息保留必要归因和审慎措辞。
- 不要添加“社区用户报告”“尚未获官方确认”等通用免责声明。需要体现不确定性时，应明确写出具体陈述主体和具体主张。
- 禁止在标题、TLDR、正文里出现任何媒体的名字（如量子位、TechCrunch、The Verge 等），
  来源标注由系统自动附在文末。
  （例外：如果新闻本身就是关于某篇文章/某个人的，按事实陈述该文章/人物的观点。）

对每条素材输出一个条目块，格式严格如下（块与块之间不留空行）：

===ITEM===
URL: <原样复制该素材的链接>
标题: <15~30字的中文短标题，概括事件核心；专有名词/产品名保留英文>
分类: <要闻/开发生态/产品应用/行业动态 四选一，按内容判断>
TLDR: <60~120字的一段话摘要，概括整个事件的关键信息>
BODY:
<正文：2~6个短段落，每段只讲一个事实，段落之间用空行分隔；关键人名/公司/产品名用**加粗**，关键数字/版本号/专有名词用`反引号`>
===END===

硬性要求：
1. 条目数量与素材条数完全一致，一条不多不少，按素材给出的顺序。
2. 严格基于素材写作：禁止编造素材中不存在的数字、结论和细节；素材里没有的信息不要用"常识"补齐。
3. URL 必须原样复制素材中的链接，禁止改写、拼接、杜撰；URL 只用于回填字段，不要出现在标题、TLDR 和正文里。
4. 客观陈述，不夸大；中文写作，专有名词保留英文原名。
5. 除条目块外不要输出任何解释、标题或代码围栏。

素材：
---
{material}
---"""

PLACEHOLDER_TMPL = (
    "<!-- 📷 截图占位 | {desc}\n"
    "     操作：打开原文链接，截取页面首屏，保存为 output/{date}/{path}，刷新预览即可看到图片 -->\n"
    "![待补充截图：{desc}]({path})"
)

FIELD_PREFIXES = ("URL:", "url:", "标题:", "标题：", "分类:", "分类：", "TLDR:", "tldr:", "BODY:", "body:")


def slugify(text: str, max_len: int = 40) -> str:
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip().lower()
    slug = re.sub(r"[\s_-]+", "-", text).strip("-")
    return (slug or "item")[:max_len].rstrip("-")


def assign_screenshot_paths(items: list[dict], date_str: str, count: int) -> None:
    """给排序后的前 count 条分配截图保存路径（相对 output/ 目录）。"""
    for i, item in enumerate(items[: max(0, count)], 1):
        item["screenshot_path"] = f"assets/{date_str}/{i:02d}-{slugify(item['title'])}.jpg"


def _desc(item: dict, limit: int = 60) -> str:
    text = f"{item['source']}｜{item['title']}"
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_material(items: list[dict]) -> str:
    """提供来源、证据性质及时间口径，保留社区消息和文档变更的不确定性。"""
    blocks = []
    for i, it in enumerate(items, 1):
        pub = it["published"].strftime("%Y-%m-%d %H:%M UTC") if it.get("published") else "未知"
        observed = it.get("observed_at")
        # 将“未获官方确认”作为给模型的证据元数据，而不是要求成稿机械添加免责声明；
        # 这样既保留社区消息的事实边界，也允许输出按具体主体归因的自然措辞。
        provenance = "该信息未经官方确认；只转述具体主体的具体主张，不得扩写为全体用户或官方公告。" if it.get("evidence_type") == "community" else "按原文限定表述。"
        observation = f"首次检测时间：{observed.isoformat()}（不代表发布时间）；仅描述所附差异。\n" if observed else ""
        blocks.append(
            f"来源：{it['source']}；{provenance}\n{observation}"
            f"[{i}] 参考标题：{it['title']}\n"
            f"链接：{it['url']}\n"
            f"发布时间：{pub}\n"
            f"信息：{(it.get('summary') or '（无）')[:600]}\n"
            f"详情：{(it.get('text') or '（无）')[:1200]}"
        )
    return "\n-----\n".join(blocks)


def call_llm(cfg: dict, material: str) -> str:
    resp = httpx.post(
        cfg["base_url"].rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {cfg['api_key']}"},
        json={
            "model": cfg["model"],
            "temperature": cfg.get("temperature", 0.4),
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_PROMPT.format(material=material)},
            ],
        },
        timeout=300,
    )
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"].strip()
    return re.sub(r"^```(?:markdown)?\s*|\s*```$", "", text).strip()


def parse_llm_items(text: str) -> list[dict]:
    """解析 ===ITEM=== 分隔的条目块；容错处理全角/半角冒号与大小写。"""
    parsed = []
    for block in text.split("===ITEM===")[1:]:
        block = block.split("===END===")[0].strip("\n")
        url = cat = tldr = title = ""
        body_lines: list[str] = []
        in_body = False
        for line in block.splitlines():
            s = line.strip()
            hit = next((f for f in FIELD_PREFIXES if s.startswith(f)), None)
            if hit:
                value = s[len(hit):].strip()
                key = hit.rstrip(":：").lower()
                if key == "url":
                    url, in_body = value, False
                elif key == "标题":
                    title, in_body = value.strip("*`# "), False
                elif key == "分类":
                    cat, in_body = value.strip("*` "), False
                elif key == "tldr":
                    tldr, in_body = value, False
                else:  # BODY:
                    in_body = True
            elif in_body:
                body_lines.append(line)
        if url:
            parsed.append({
                "url": url,
                "title": title,
                "category": cat if cat in CATEGORIES else "要闻",
                "tldr": clean_meta_reporting(re.sub(r"\s*\n\s*", " ", tldr)),
                "body": clean_meta_reporting("\n".join(body_lines).strip()),
            })
    return parsed


META_REPORTING_RE = re.compile(
    r"[^。！？!?；;\n]*(?:获得|收获|拿到|取得)\s*`?\d[\d,]*`?\s*(?:分|票|个赞|点赞|热度)[^。！？!?；;\n]*"
    r"(?:[，,]\s*[^。！？!?；;\n]*(?:讨论数|评论数|讨论量|阅读量)[^。！？!?；;\n]*(?:达|为|有)\s*`?\d[\d,]*`?)?"
    r"[。！？!?；;]?",
    re.I,
)
META_PLATFORM_RE = re.compile(
    r"[^。！？!?；;\n]*(?:在|于)\s*(?:Hacker\s*News|Reddit|Product\s*Hunt)[^。！？!?；;\n]*"
    r"(?:得分|分数|讨论数|评论数|阅读量|热度|引发社区关注)[^。！？!?；;\n]*[。！？!?；;]?",
    re.I,
)


def clean_meta_reporting(text: str) -> str:
    """删除把来源平台热度/讨论量当成新闻事实的句子。"""
    cleaned = META_REPORTING_RE.sub("", text)
    cleaned = META_PLATFORM_RE.sub("", cleaned)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()


def merge_changelog_updates(items: list[dict]) -> list[dict]:
    """同一工具同日的多个 changelog 版本合并为一条：
    保留排序最前的版本作主条目，其余版本的链接与变更内容并入。"""
    by_tool: dict[str, dict] = {}
    out: list[dict] = []
    for it in items:
        if it.get("kind") != "changelog":
            out.append(it)
            continue
        primary = by_tool.get(it["source"])
        if primary is None:
            by_tool[it["source"]] = it
            out.append(it)
            continue
        have = {u for _, u in primary["sources"]}
        primary["sources"].extend((s, u) for s, u in it.get("sources", []) if u not in have)
        primary["summary"] = "；".join(x for x in (primary.get("summary", ""), it.get("summary", "")) if x)
    return out


def assemble_digest(parsed: list[dict], items: list[dict], date_str: str) -> str:
    """按 URL 把 LLM 条目对齐到素材条目上，编号并装配早报版式。
    LLM 漏写的条目用摘要兜底，确保概览与条目一一对应。"""
    by_url: dict[str, dict] = {}
    for it in items:
        by_url.setdefault(normalize_url(it["url"]), it)
        for _, u in it.get("sources", []):
            by_url.setdefault(normalize_url(u), it)

    entries = []
    for it in items:
        p = next(
            (p for p in parsed if normalize_url(p["url"]) == normalize_url(it["url"])),
            None,
        )
        title = (p["title"] if p and p["title"] else it["title"])
        it["display_title"] = title
        category = p["category"] if p else CATEGORY_FALLBACK.get(it.get("category", "news"), "要闻")
        tldr = p["tldr"] if p else clean_meta_reporting((it.get("summary") or "")[:150])
        body = p["body"] if p else clean_meta_reporting((it.get("text") or it.get("summary") or "")[:400])
        if it.get("observed_at"):
            body = f"首次检测：{it['observed_at']:%Y-%m-%d %H:%M UTC}；原始发布时间未知。\n\n" + body
        links = [u for _, u in it.get("sources", [(it["source"], it["url"])])]
        entries.append({
            "title": title,
            "category": category,
            "tldr": tldr,
            "body": body,
            "links": links,
            "screenshot_path": it.get("screenshot_path"),
            "source": it["source"],
        })

    # 按分类分组（组间按 CATEGORIES 顺序，组内保持原有排序）
    entries.sort(key=lambda e: CATEGORIES.index(e["category"]) if e["category"] in CATEGORIES else 99)
    for no, e in enumerate(entries, 1):
        e["no"] = no

    lines = ["## 概览", ""]
    for cat in CATEGORIES:
        group = [e for e in entries if e["category"] == cat]
        if not group:
            continue
        lines += [f"### {cat}", ""]
        lines += [f"- {e['title']} `#{e['no']}`" for e in group]
        lines.append("")
    lines += ["---", ""]

    for e in entries:
        lines += [f"## {e['title']} `#{e['no']}`", ""]
        if e["tldr"]:
            lines += [f"> {e['tldr']}", ""]
        if e["body"]:
            lines += [e["body"], ""]
        if e["screenshot_path"]:
            lines += [
                PLACEHOLDER_TMPL.format(
                    path=e["screenshot_path"], date=date_str,
                    desc=f"{e['source']}｜{e['title'][:50]}"
                ),
                "",
            ]
        if e["links"]:
            lines += ["```"] + e["links"] + ["```", ""]
        lines += ["---", ""]
    return "\n".join(lines).rstrip() + "\n"


def generate_digest(items: list[dict], date_str: str, llm_cfg: Optional[dict]) -> str:
    parsed: list[dict] = []
    if llm_cfg:
        try:
            parsed = parse_llm_items(call_llm(llm_cfg, build_material(items)))
            if parsed:
                print(f"       LLM 条目：{len(parsed)}/{len(items)} 条解析成功")
        except Exception as e:
            print(f"[warn] LLM 生成失败（{type(e).__name__}: {e}），退化为摘要版")
    return assemble_digest(parsed, items, date_str)


def resolve_llm(cfg: dict, disabled: bool = False) -> Optional[dict]:
    """enabled=auto 时只要拿到 key 就启用。key 优先读环境变量 LLM_API_KEY。"""
    if disabled or cfg.get("enabled") is False:
        return None
    key = os.getenv("LLM_API_KEY", "").strip() or str(cfg.get("api_key") or "").strip()
    if not key:
        return None
    return {**cfg, "api_key": key}
