"""从当日草稿中挑选条目生成终稿。

命令行用法：
    python finalize.py 1 2 4 5 7            # 选取草稿概览中的 #1 #2 #4 #5 #7
    python finalize.py 1 2 --date 2026-08-30  # 指定日期的草稿

Web 端（webui.py）复用 parse_draft_text / build_final 完成同样的装配。

规则：
- 条目文字原样保留（终稿不做任何改写）；
- 终稿按选定顺序重新编号 #1..#N；概览可选，默认不导出；
- 正文条目不带链接块（草稿里保留链接块是为了截图时对照原文），
  所有信息源统一放到文末「🔗 信息源」小节；
- 条目开头的引用摘要（TLDR 引言块）不导出到终稿；
- 已含图片（用户手动插入的 ![[ ]] 或 ![]()）的条目保留图片，并统一移到条目开头
  （先图后文）；未粘贴图片的条目在终稿中不输出空白图片占位符。
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent

# 复用成稿阶段的标题宽度计算，保证「生成时约束」和「导出时校验」用同一把尺子
from src.pipeline.generate import TITLE_CHAR_LIMIT, count_title_chars  # noqa: E402

ITEM_HEAD = re.compile(r"^## (.+?)(?:\s+`#(\d+)`)?$")
OV_ITEM = re.compile(r"^- (.+?)(?:\s+`#(\d+)`)?$")
OV_GROUP = re.compile(r"^### (.+)$")
# 草稿文件名：科技日报-2026-09-27.md、科技日报-2026-09-27-1.md（重跑加序号）、
# 以及迁移前的 AI早报-*。不匹配终稿/单条稿，避免把它们当草稿读进来。
DRAFT_FILE_RE = re.compile(r"^(?:科技日报|AI早报)-\d{4}-\d{2}-\d{2}(?:-\d+)?\.md$")
PLACEHOLDER_START = "<!-- 📷 截图占位"
IMAGE_SLOT = "<!-- 📷 图片区域 -->"
TITLE_MAX_LEN = 120  # 终稿标题单行上限，与导出框 maxlength 保持一致
# 推荐标题长度：取三个平台的共同下限。公众号手机列表页约 17 个汉字后截断，
# 小红书标题框硬限 20 字，头条约 30 字。按 17 字写三家都能完整显示。
TITLE_SOFT_LEN = 17


def slugify(text: str, max_len: int = 40) -> str:
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip().lower()
    slug = re.sub(r"[\s_-]+", "-", text).strip("-")
    return (slug or "item")[:max_len].rstrip("-")


def parse_draft_text(text: str) -> tuple[dict, dict]:
    """解析草稿文本。返回 (概览 {编号: {标题, 分类}}, 条目块 {编号: [行]})"""
    lines = text.splitlines()
    overview: dict[int, dict] = {}
    blocks: dict[int, list[str]] = {}
    in_overview = False
    cat = ""
    current: int | None = None
    next_no = 1
    for ln in lines:
        if in_overview:
            if ITEM_HEAD.match(ln):
                in_overview = False  # 概览结束，进入条目区
            else:
                m = OV_GROUP.match(ln)
                if m:
                    cat = m.group(1).strip()
                    continue
                m = OV_ITEM.match(ln)
                if m:
                    no = int(m.group(2)) if m.group(2) else next_no
                    overview[no] = {
                        "ov_title": m.group(1).strip(),
                        "category": cat,
                    }
                    next_no = max(next_no, no + 1)
                    continue
        if ln.startswith("## 概览"):
            in_overview = True
            continue
        if ln.startswith("## 🗞️ 今日来源"):
            current = None
            continue
        m = ITEM_HEAD.match(ln)
        if m:
            if m.group(2):
                current = int(m.group(2))
            else:
                used = set(blocks)
                current = next((n for n in sorted(overview) if n not in used), next_no)
            blocks[current] = [ln]
            continue
        if current is not None:
            blocks[current].append(ln)
    for blk in blocks.values():
        while blk and blk[-1].strip() in ("", "---"):
            blk.pop()
    return overview, blocks


def parse_draft(path: Path) -> tuple[dict, dict]:
    return parse_draft_text(path.read_text(encoding="utf-8"))


def strip_placeholder(block: list[str]) -> list[str]:
    out, skipping = [], False
    for ln in block:
        if ln.strip() == IMAGE_SLOT:
            continue
        if ln.startswith(PLACEHOLDER_START):
            skipping = True
            continue
        if skipping:
            if ln.startswith("!["):
                skipping = False
            continue
        out.append(ln)
    return out


def link_fence_lines(block: list[str]) -> list[tuple[int, int, list[str]]]:
    """逐个代码块返回 (起始行, 结束行, 其中的 http 链接)。

    只按「是否含 http 链接」识别来源块，不能简单取最后一个代码块——
    正文里出现代码示例时，取最后一个会把文章的代码块当成来源删掉。

    围栏要同时支持裸 ``` 和带语言标识的 ```text：稿件里的来源块两种写法都有，
    只认裸围栏会让来源识别失败，进而让 article_key 退化成标题哈希、
    与快照按 URL 生成的 key 对不上（表现为已导出的文章仍出现在「昨日未导出」里）。
    """
    fences: list[tuple[int, int, list[str]]] = []
    start: int | None = None
    for i, ln in enumerate(block):
        s = ln.strip()
        if not s.startswith("```"):
            continue
        if start is None:
            start = i  # 开围栏（可带语言标识，如 ```text）
            continue
        if s != "```":
            continue  # 闭围栏必须是裸 ```
        inner = block[start + 1:i]
        urls = [u.strip() for u in inner if u.strip().startswith("http")]
        if urls:
            fences.append((start, i, urls))
        start = None
    return fences


def link_fence(block: list[str]) -> list[str]:
    fences = link_fence_lines(block)
    if not fences:
        return []
    urls = fences[-1][2]
    return list(dict.fromkeys(urls))  # 保序去重：同一来源常被多条素材重复登记


def strip_link_fence(lines: list[str]) -> list[str]:
    """去掉条目末尾的来源链接代码块（终稿正文不带链接，来源统一放到文末）。

    只会删掉真正含 http 链接的代码块，避免误删正文里的代码示例。
    """
    fences = link_fence_lines(lines)
    if fences:
        start, end, _ = fences[-1]
        # 仅当该块之后没有实质正文时才视为条目末尾的来源块
        if not any(ln.strip() and ln.strip() != "---" for ln in lines[end + 1:]):
            lines = lines[:start]
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def insert_placeholder(lines: list[str], ph: list[str]) -> list[str]:
    """把图片区域插在条目标题之后（先图后文）；lines[0] 为条目标题行。"""
    if not lines:
        return list(ph)
    rest = lines[1:]
    while rest and not rest[0].strip():
        rest.pop(0)
    return lines[:1] + [""] + ph + [""] + rest


def next_path(base: Path) -> Path:
    """不覆盖已有文件：base 存在时返回 base-1、base-2…"""
    if not base.exists():
        return base
    n = 1
    while base.with_name(f"{base.stem}-{n}{base.suffix}").exists():
        n += 1
    return base.with_name(f"{base.stem}-{n}{base.suffix}")


def newest_draft(date_dir: Path, date_str: str, explicit: str | None = None) -> Path | None:
    """选出要导出的草稿，默认取当天最新的一份。

    main.py 重跑时不覆盖历史，会依次写成 科技日报-{date}.md、-1.md、-2.md…，
    所以不能硬编码文件名：否则重跑之后导出的仍是旧稿（实测出现过「草稿里明明
    是新标题，导出结果却是旧标题」）。默认按修改时间取最新，与 WebUI 的
    draft_path() 行为一致；需要指定某一份时用 --draft。
    """
    if explicit:
        for cand in (Path(explicit), date_dir / explicit):
            if cand.is_file():
                return cand
        return None
    candidates = [
        p for p in date_dir.iterdir()
        if p.is_file() and DRAFT_FILE_RE.match(p.name)
    ] if date_dir.is_dir() else []
    # 兼容迁移前的历史稿件和旧目录结构
    for legacy in (date_dir / f"AI早报-{date_str}.md", ROOT / "output" / f"AI早报-{date_str}.md"):
        if legacy.is_file():
            candidates.append(legacy)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def is_pending_shot(line: str) -> bool:
    return "待补充截图" in line


def split_images(body: list[str]) -> tuple[list[str], list[str]]:
    """先图后文：抽出正文中的真实图片行（剔除待补充占位），文本行清理首尾空行。"""
    images: list[str] = []
    text: list[str] = []
    for ln in body:
        s = ln.strip()
        if s.startswith("![[") or re.match(r"!\[[^\]]*\]\(", s):
            if not is_pending_shot(s):
                images.append(s)
        else:
            text.append(ln)
    while text and not text[0].strip():
        text.pop(0)
    while text and not text[-1].strip():
        text.pop()
    return images, text


def strip_leading_quote(lines: list[str]) -> list[str]:
    """删除条目开头的引用摘要（> 引言块）。"""
    idx = 0
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    end = idx
    while end < len(lines) and lines[end].lstrip().startswith(">"):
        end += 1
    return lines[end:] if end > idx else lines


def strip_why_section(lines: list[str]) -> list[str]:
    """删除正文里的「为什么重要」引用段。

    该字段已停用（实测只是复述正文事实，零新增信息）。但历史草稿里已经写入了
    这些段落，而导出是逐行搬运草稿内容——只删生成端不够，导出端必须一并过滤，
    否则旧草稿导出的单条稿仍会带上它。
    """
    return [ln for ln in lines if "为什么重要" not in ln]


def display_date(date_str: str) -> str:
    """将 ISO 日期显示为标题使用的不补零格式。"""
    date = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{date.year}-{date.month}-{date.day}"


def date_suffix(date_str: str) -> str:
    """标题末尾的日期后缀：` | 科技日报MMDD`。"""
    date = datetime.strptime(date_str, "%Y-%m-%d")
    return f" | 科技日报{date:%m%d}"


def fit_title(body: str, suffix: str) -> str:
    """标题主体压进单行上限；超长时优先整条丢弃，保证末尾日期后缀不被截掉。"""
    room = TITLE_MAX_LEN - len(suffix)
    parts = str(body or "").split("；")
    while len(parts) > 1 and len("；".join(parts)) > room:
        parts.pop()
    joined = "；".join(parts)
    return (joined[:room].rstrip("； ").rstrip() or "今日资讯") + suffix


def default_final_title(date_str: str, overview: dict | None = None, picks: list[int] | None = None) -> str:
    """Return the default editable title used for final exports.

    默认取首条条目的标题，不再把多条标题用「；」拼成一行。
    拼接标题（原实现可达 120 字、塞 3 条互不相关的新闻）会被公众号列表页
    截到前 17 字、被头条腰斩、在小红书根本无法输入，是点击率最大的杀手。
    多焦点标题还会让推荐算法无法给文章打单一标签，直接失去定向能力。
    需要合辑标题时可在导出框里手动改，或显式传 title。
    """
    body = "今日资讯"
    if overview is not None and picks:
        first = str(overview.get(picks[0], {}).get("ov_title") or "").strip()
        if first:
            body = first
    return fit_title(body, date_suffix(date_str))


def normalize_final_title(
    title: str | None,
    date_str: str,
    overview: dict | None = None,
    picks: list[int] | None = None,
) -> str:
    """Keep an exported Markdown title on one bounded heading line."""
    clean = " ".join(str(title or "").splitlines()).strip().lstrip("#").strip()
    if not clean:
        return default_final_title(date_str, overview, picks)
    suffix = date_suffix(date_str)
    if clean.endswith(suffix):
        return fit_title(clean[: -len(suffix)].rstrip(), suffix)
    return clean[:TITLE_MAX_LEN].rstrip()


def existing_image(block: list[str], asset_root: Path | None) -> tuple[str, str] | None:
    """返回块中实际存在的本地图片（Markdown 行、相对路径）。"""
    for line in block:
        match = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", line.lstrip())
        if not match:
            continue
        path = match.group(2).strip()
        if asset_root is not None and not re.match(r"^(?:https?:|data:|/|#)", path, re.I):
            expected = asset_root / path.replace("/", os.sep)
            actual = expected if expected.is_file() else None
            if actual is None:
                # 终稿会重新编号；允许沿用同一图片但编号不同的文件。
                stem = re.sub(r"^\d+-", "", expected.name).lower()
                if expected.parent.is_dir():
                    actual = next(
                        (
                            candidate
                            for candidate in expected.parent.iterdir()
                            if candidate.is_file()
                            and re.sub(r"^\d+-", "", candidate.name).lower() == stem
                        ),
                        None,
                    )
            if actual is not None:
                rel = actual.relative_to(asset_root).as_posix()
                return line.replace(path, rel), rel
    return None


def build_final(
    overview: dict,
    blocks: dict,
    picks: list[int],
    date_str: str,
    asset_root: Path | None = None,
    title: str | None = None,
    include_sources: bool = False,
    include_overview: bool = False,
) -> tuple[str, list[dict]]:
    """按 picks 顺序装配终稿（条目文字原样保留，重新编号 #1..#N；先图后文，去掉开头引用摘要）。
    返回 (markdown 文本, rebuilt 元信息列表)。"""
    picked = [n for n in picks if n in blocks]
    if asset_root is None:
        asset_root = ROOT / "output" / date_str
    out_lines = [f"# {normalize_final_title(title, date_str, overview, picked)}", ""]
    rebuilt = []
    for new_no, old_no in enumerate(picked, 1):
        info = overview.get(old_no, {})
        title = info.get("ov_title") or f"条目{old_no}"
        cat = info.get("category", "今日头条")
        source_image = existing_image(blocks[old_no], asset_root)
        blk = strip_placeholder(blocks[old_no])
        links = link_fence(blk)
        body = strip_why_section(strip_leading_quote(strip_link_fence(blk[1:])))  # 去标题行 + 去链接块 + 去引用摘要/已停用字段
        images, text = split_images(body)  # 先图后文
        if not images and source_image:
            images = [source_image[0].lstrip()]
        lines = (images + [""] + text) if images else text
        rebuilt.append({
            "no": new_no, "old_no": old_no, "title": title, "cat": cat,
            "lines": lines, "links": links, "has_img": bool(images),
            # 草稿中的空图片槽位只服务于审核界面，终稿不输出不存在的图片链接。
            "shot": "",
        })

    if include_overview:
        out_lines += ["## 概览", ""]
        for cat in dict.fromkeys(r["cat"] for r in rebuilt):  # 保序去重
            out_lines += [f"### {cat}", ""]
            out_lines += [f"- {r['title']} `#{r['no']}`" for r in rebuilt if r["cat"] == cat]
            out_lines.append("")
        out_lines += ["---", ""]

    for r in rebuilt:
        out_lines += [f"## {r['title']} `#{r['no']}`", ""]
        if r["lines"]:
            out_lines += r["lines"]
            out_lines.append("")
        out_lines += ["---", ""]

    if include_sources:
        # 正文条目不携带链接块；需要时将信息源统一放在文末。
        out_lines += ["## 🔗 信息源", ""]
        for r in rebuilt:
            if not r["links"]:
                continue
            out_lines += [f"**#{r['no']} {r['title']}**", ""]
            out_lines += [f"- {u}" for u in r["links"]]
            out_lines.append("")

    return "\n".join(out_lines).rstrip() + "\n", rebuilt


def single_meta(overview: dict, blocks: dict, no: int, date_str: str) -> dict | None:
    """单条导出所需的元信息（标题、来源链接、截图路径），供 CLI 与 WebUI 共用。"""
    if no not in blocks:
        return None
    info = overview.get(no, {})
    title = info.get("ov_title") or f"条目{no}"
    blk = strip_placeholder(blocks[no])
    links = link_fence(blk)
    images, _ = split_images(strip_why_section(strip_leading_quote(strip_link_fence(blk[1:]))))
    shot = "" if images else f"assets/{date_str}/single-{no:02d}-{slugify(title)}.jpg"
    return {"title": title, "links": links, "shot": shot}


def build_single(overview: dict, blocks: dict, no: int, date_str: str):
    """单条导出：只取一条，轻量结构（标题 + 图片 + 正文 + 来源，先图后文）。

    返回 (markdown, 元信息)；编号不存在时返回 (None, None)。

    这是「单条新闻」主流程的产物：一条素材一个焦点，标题就是条目自身的短标题
    （≤17 字，不再拼接、不加日期后缀），文末保留原文链接。
    链接必须保留——没有外链的稿件在算法平台上既无法被评估质量，也留不住读者。
    """
    if no not in blocks:
        return None, None
    meta = single_meta(overview, blocks, no, date_str)
    title, links, shot = meta["title"], meta["links"], meta["shot"]
    blk = strip_placeholder(blocks[no])
    images, text = split_images(strip_why_section(strip_leading_quote(strip_link_fence(blk[1:]))))

    out = [f"# {title}", ""]
    if images:  # 先图后文
        out += images + [""]
    elif shot:
        desc = title[:50]
        out += [
            f"<!-- 📷 截图占位 | {desc}",
            f"     操作：打开原文链接，截取页面首屏，保存为 output/{date_str}/{shot} -->",
            f"![待补充截图：{desc}]({shot})",
            "",
        ]
    out += text
    if links:
        out += ["", "**🔗 来源**", ""] + [f"- {u}" for u in links]
    return "\n".join(out).rstrip() + "\n", meta


def title_warnings(meta: dict) -> list[str]:
    """导出前提示标题问题，但绝不自动改写——手工导出时截断只会切出残句。"""
    warns = []
    title = meta.get("title", "")
    if not title:
        return ["标题为空"]
    n = count_title_chars(title)
    if n > TITLE_SOFT_LEN:
        warns.append(
            f"标题 {n:.0f} 字，超过平台列表页约 {TITLE_SOFT_LEN} 字的显示长度，"
            f"会被截断（建议改成单一焦点）"
        )
    if not meta.get("links"):
        warns.append("缺来源链接")
    if meta.get("shot"):
        warns.append("缺配图")
    return warns


def export_singles(overview, blocks, picks: list[int], date_str: str,
                   archive_root: Path | None = None, explicit_out: str | None = None) -> dict:
    """把每个编号各导出一篇独立单条稿（单条新闻主流程），CLI 与 WebUI 共用。

    Returns: {"exported": [{"no", "name", "path", "title", "meta"}], "failed": [no]}

    一篇一个焦点，标题即条目短标题，读者在列表页能看全，算法也能打准标签。
    explicit_out 只在导出单条时生效（多条会互相覆盖）。
    """
    from src.article_archive import record_export

    if archive_root is None:
        archive_root = ROOT / "data" / "article-archive"
    date_dir = ROOT / "output" / date_str
    exported, failed = [], []
    for no in picks:
        md, meta = build_single(overview, blocks, no, date_str)
        if md is None:
            failed.append(no)
            continue
        if explicit_out and len(picks) == 1:
            out = Path(explicit_out)
        else:
            out = next_path(date_dir / f"科技日报-{date_str}-单条-{no}.md")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md, encoding="utf-8")
        record_export(date_str, overview, blocks, [no], out.name, archive_root)
        exported.append({
            "no": no,
            "name": out.name,
            "path": out.relative_to(ROOT / "output").as_posix(),
            "title": meta["title"],
            "meta": meta,
        })
    return {"exported": exported, "failed": failed}


def _export_singles(overview, blocks, picks: list[int], args, date_dir: Path, explicit_out: str | None = None) -> int:
    """命令行入口：导出并打印每条的配图/来源/标题告警。"""
    if explicit_out and len(picks) > 1:
        print("[warn] 导出多条时忽略 --out，避免相互覆盖")
    result = export_singles(
        overview, blocks, picks, args.date,
        ROOT / "data" / "article-archive",
        explicit_out,
    )
    exported, failed = result["exported"], result["failed"]
    for row in exported:
        meta = row["meta"]
        # meta["shot"] 非空表示「还没有图，这是待补的截图路径」，不是有图
        flags = "🖼 有图" if not meta["shot"] else "⚠️ 缺图"
        links = f"{len(meta['links'])} 个来源" if meta["links"] else "⚠️ 无来源链接"
        print(f"  #{row['no']} {flags} {links}  {row['name']}\n      {row['title']}")
        for w in title_warnings(meta):
            print(f"      ⚠️  {w}")
    if failed:
        print(f"[warn] 编号 {failed} 不在草稿中，已跳过")
    if not exported:
        print("没有可导出的条目")
        return 1
    print(f"\n已导出 {len(exported)} 篇单条稿到 {date_dir}")
    missing = [r["no"] for r in exported if r["meta"]["shot"]]
    if missing:
        print(f"提示：#{missing} 还没有配图，可在控制中心的「资讯截图存放区」补图后重新导出。")
    return 0


def main() -> int:
    # 延迟导入避免 article_archive 复用本模块解析器时形成模块级循环依赖。
    from src.article_archive import record_export

    ap = argparse.ArgumentParser(
        description="从当日草稿导出稿件（默认：每条新闻导出一篇独立单条稿）"
    )
    ap.add_argument("picks", nargs="*", type=int, help="草稿概览中的条目编号，按顺序给出")
    ap.add_argument("--single", type=int, default=None, help="只导出指定编号的一条")
    ap.add_argument("--digest", action="store_true", help="改用合辑模式（一篇含多条），默认是单条模式")
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"), help="草稿日期")
    ap.add_argument("--draft", default=None, help="指定草稿文件（默认取当天最新的一份）")
    ap.add_argument("--out", default=None, help="输出路径（单条模式且选了多条时忽略）")
    ap.add_argument("--title", default=None, help="合辑标题（默认取首条标题，不再拼接多条）")
    ap.add_argument("--include-sources", action="store_true", help="在终稿末尾附带信息源小节")
    ap.add_argument("--include-overview", action="store_true", help="在终稿开头附带概览，默认不导出")
    args = ap.parse_args()

    date_dir = ROOT / "output" / args.date
    draft = newest_draft(date_dir, args.date, args.draft)
    if draft is None:
        print(f"找不到草稿：{date_dir / f'科技日报-{args.date}.md'}")
        return 1
    overview, blocks = parse_draft(draft)
    print(f"草稿：{draft.name}")

    if args.single is not None:
        return _export_singles(overview, blocks, [args.single], args, date_dir, explicit_out=args.out)

    skipped = [n for n in args.picks if n not in blocks]
    if skipped:
        print(f"[warn] 编号 {skipped} 在草稿中不存在，已忽略")
    picked = [n for n in args.picks if n in blocks]
    if not picked:
        print("没有可用的条目")
        return 1

    if not args.digest:
        return _export_singles(overview, blocks, picked, args, date_dir)

    md, rebuilt = build_final(
        overview, blocks, picked, args.date, ROOT / "output" / args.date,
        args.title, args.include_sources, args.include_overview
    )
    if not rebuilt:
        print("没有可用的条目")
        return 1

    if args.out:
        out = Path(args.out)  # 显式指定路径时按用户要求覆盖
    else:
        out = next_path(date_dir / f"科技日报-{args.date}-终稿.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    (out.parent / "assets" / args.date).mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    record_export(
        args.date, overview, blocks, picked, out.name,
        ROOT / "data" / "article-archive",
    )

    print(f"终稿已生成：{out}")
    print("已选条目：")
    for r in rebuilt:
        print(f"  #{r['no']}（原#{r['old_no']}·{r['cat']}）{r['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
