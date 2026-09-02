"""从当日草稿中挑选条目生成终稿。

命令行用法：
    python finalize.py 1 2 4 5 7            # 选取草稿概览中的 #1 #2 #4 #5 #7
    python finalize.py 1 2 --date 2026-08-30  # 指定日期的草稿

Web 端（webui.py）复用 parse_draft_text / build_final 完成同样的装配。

规则：
- 条目文字原样保留（终稿不做任何改写）；
- 终稿按选定顺序重新编号 #1..#N，概览按草稿分类重排；
- 正文条目不带链接块（草稿里保留链接块是为了截图时对照原文），
  所有信息源统一放到文末「🔗 信息源」小节；
- 已含图片（用户手动插入的 ![[ ]] 或 ![]()）的条目跳过占位符，
  其余条目在正文末尾重建截图占位符。
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent

ITEM_HEAD = re.compile(r"^## (.+) `#(\d+)`$")
OV_ITEM = re.compile(r"^- (.+) `#(\d+)`$")
OV_GROUP = re.compile(r"^### (.+)$")
PLACEHOLDER_START = "<!-- 📷 截图占位"
IMAGE_SLOT = "<!-- 📷 图片区域 -->"


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
                    overview[int(m.group(2))] = {
                        "ov_title": m.group(1).strip(),
                        "category": cat,
                    }
                    continue
        if ln.startswith("## 概览"):
            in_overview = True
            continue
        m = ITEM_HEAD.match(ln)
        if m:
            current = int(m.group(2))
            blocks[current] = [ln]
            continue
        if ln.startswith("## 🗞️ 今日来源"):
            current = None
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


def link_fence(block: list[str]) -> list[str]:
    text = "\n".join(block)
    fences = re.findall(r"```(.*?)```", text, re.S)
    if not fences:
        return []
    return [u.strip() for u in fences[-1].strip().splitlines() if u.strip().startswith("http")]


def strip_link_fence(lines: list[str]) -> list[str]:
    """去掉条目末尾的链接代码块（终稿正文不带链接，来源统一放到文末）"""
    idx = last_fence_start(lines)
    if idx is not None:
        lines = lines[:idx]
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def last_fence_start(lines: list[str]) -> int | None:
    idx, inside = None, False
    for i, ln in enumerate(lines):
        if ln.strip() == "```":
            if not inside:
                idx = i
            inside = not inside
    return idx


def insert_placeholder(lines: list[str], ph: list[str]) -> list[str]:
    idx = last_fence_start(lines)
    if idx is None:
        return lines + [""] + ph
    while idx > 0 and lines[idx - 1].strip() == "":
        idx -= 1
    return lines[:idx] + ph + [""] + lines[idx:]


def next_path(base: Path) -> Path:
    """不覆盖已有文件：base 存在时返回 base-1、base-2…"""
    if not base.exists():
        return base
    n = 1
    while base.with_name(f"{base.stem}-{n}{base.suffix}").exists():
        n += 1
    return base.with_name(f"{base.stem}-{n}{base.suffix}")


def has_user_image(block: list[str]) -> bool:
    return any(
        ln.lstrip().startswith("![[") or re.match(r"!\[[^\]]*\]\(", ln.lstrip())
        for ln in block
    )


def display_date(date_str: str) -> str:
    """将 ISO 日期显示为标题使用的不补零格式。"""
    date = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{date.year}-{date.month}-{date.day}"


def default_final_title(date_str: str) -> str:
    """Return the default editable title used for final exports."""
    date = datetime.strptime(date_str, "%Y-%m-%d")
    return f"今日资讯 | AI日报{date:%m%d}"


def normalize_final_title(title: str | None, date_str: str) -> str:
    """Keep an exported Markdown title on one bounded heading line."""
    clean = " ".join(str(title or "").splitlines()).strip().lstrip("#").strip()
    return (clean or default_final_title(date_str))[:120].rstrip()


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
) -> tuple[str, list[dict]]:
    """按 picks 顺序装配终稿（条目文字原样保留，重新编号 #1..#N）。
    返回 (markdown 文本, rebuilt 元信息列表)。"""
    picked = [n for n in picks if n in blocks]
    if asset_root is None:
        asset_root = ROOT / "output" / date_str
    out_lines = [f"# {normalize_final_title(title, date_str)}", ""]

    rebuilt = []
    for new_no, old_no in enumerate(picked, 1):
        info = overview.get(old_no, {})
        title = info.get("ov_title") or f"条目{old_no}"
        cat = info.get("category", "要闻")
        source_image = existing_image(blocks[old_no], asset_root)
        blk = strip_placeholder(blocks[old_no])
        links = link_fence(blk)
        body = strip_link_fence(blk[1:])  # 去标题行 + 去链接块
        while body and not body[0].strip():
            body.pop(0)
        img = has_user_image(body)
        if source_image and not img:
            body += ["", source_image[0].lstrip()]
            img = True
        rebuilt.append({
            "no": new_no, "old_no": old_no, "title": title, "cat": cat,
            "lines": body, "links": links, "has_img": img,
            "shot": "" if img else f"assets/{date_str}/{new_no:02d}-{slugify(title)}.jpg",
        })

    out_lines += ["## 概览", ""]
    for cat in dict.fromkeys(r["cat"] for r in rebuilt):  # 保序去重
        out_lines += [f"### {cat}", ""]
        out_lines += [f"- {r['title']} `#{r['no']}`" for r in rebuilt if r["cat"] == cat]
        out_lines.append("")
    out_lines += ["---", ""]

    for r in rebuilt:
        out_lines += [f"## {r['title']} `#{r['no']}`", ""]
        out_lines += r["lines"]
        if r["shot"]:
            desc = r["title"][:50]
            out_lines += [
                "",
                f"<!-- 📷 截图占位 | {desc}",
                f"     操作：打开原文链接，截取页面首屏，保存为 output/{date_str}/{r['shot']}，刷新预览即可看到图片 -->",
                f"![待补充截图：{desc}]({r['shot']})",
            ]
        out_lines += ["", "---", ""]

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


def build_single(overview: dict, blocks: dict, no: int, date_str: str):
    """单条导出：只取一条，轻量结构（标题 + 正文 + 占位 + 来源）。
    返回 (markdown, 元信息)；编号不存在时返回 (None, None)。"""
    if no not in blocks:
        return None, None
    info = overview.get(no, {})
    title = info.get("ov_title") or f"条目{no}"
    blk = strip_placeholder(blocks[no])
    links = link_fence(blk)
    body = strip_link_fence(blk[1:])
    while body and not body[0].strip():
        body.pop(0)
    img = has_user_image(body)
    shot = "" if img else f"assets/{date_str}/single-{no:02d}-{slugify(title)}.jpg"

    out = [f"# {title}", ""]
    out += body
    if shot:
        desc = title[:50]
        out += [
            "",
            f"<!-- 📷 截图占位 | {desc}",
            f"     操作：打开原文链接，截取页面首屏，保存为 output/{date_str}/{shot} -->",
            f"![待补充截图：{desc}]({shot})",
        ]
    if links:
        out += ["", "**🔗 来源**", ""] + [f"- {u}" for u in links]
    return "\n".join(out).rstrip() + "\n", {"title": title, "links": links, "shot": shot}


def main() -> int:
    ap = argparse.ArgumentParser(description="从当日草稿挑条目生成终稿")
    ap.add_argument("picks", nargs="*", type=int, help="草稿概览中的条目编号，按终稿顺序给出")
    ap.add_argument("--single", type=int, default=None, help="单条导出：只导出指定编号的一条")
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"), help="草稿日期")
    ap.add_argument("--out", default=None, help="输出路径（默认 output/AI早报-{date}-终稿.md）")
    ap.add_argument("--title", default=None, help="终稿标题（默认：今日资讯 | AI日报MMDD）")
    ap.add_argument("--include-sources", action="store_true", help="在终稿末尾附带信息源小节")
    args = ap.parse_args()

    date_dir = ROOT / "output" / args.date
    draft = date_dir / f"AI早报-{args.date}.md"
    if not draft.exists():  # 兼容迁移前的历史稿件
        draft = ROOT / "output" / f"AI早报-{args.date}.md"
    if not draft.exists():
        print(f"找不到草稿：{draft}")
        return 1
    overview, blocks = parse_draft(draft)

    if args.single is not None:
        md, meta = build_single(overview, blocks, args.single, args.date)
        if md is None:
            print(f"编号 #{args.single} 不在草稿中")
            return 1
        if args.out:
            out = Path(args.out)
        else:
            out = next_path(date_dir / f"AI早报-{args.date}-单条-{args.single}.md")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md, encoding="utf-8")
        print(f"单条已导出：{out}\n  {meta['title']}")
        return 0

    skipped = [n for n in args.picks if n not in blocks]
    if skipped:
        print(f"[warn] 编号 {skipped} 在草稿中不存在，已忽略")
    md, rebuilt = build_final(
        overview, blocks, args.picks, args.date, ROOT / "output" / args.date,
        args.title, args.include_sources
    )
    if not rebuilt:
        print("没有可用的条目")
        return 1

    if args.out:
        out = Path(args.out)  # 显式指定路径时按用户要求覆盖
    else:
        out = next_path(date_dir / f"AI早报-{args.date}-终稿.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    (out.parent / "assets" / args.date).mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")

    print(f"终稿已生成：{out}")
    print("已选条目：")
    for r in rebuilt:
        print(f"  #{r['no']}（原#{r['old_no']}·{r['cat']}）{r['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
