"""组装并写入每日 Markdown 稿"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path


def render_digest(items: list[dict], date_str: str, body: str, stats: dict) -> str:
    header = [
        f"> 生成时间：{datetime.now():%Y-%m-%d %H:%M} ｜ "
        f"素材 {stats['fetched']} 条 → 入选 {stats['kept']} 条 ｜ "
        f"来源 {stats['source_count']} 个"
    ]
    header.append("")

    src_counts: dict[str, int] = {}
    for it in items:
        for s, _ in it.get("sources", [(it["source"], it["url"])]):
            src_counts[s] = src_counts.get(s, 0) + 1
    ranked = "、".join(f"{s}({c})" for s, c in sorted(src_counts.items(), key=lambda kv: -kv[1]))

    body = body.rstrip()
    if body.endswith("---"):
        body = body[: -3].rstrip()  # 条目区已带分隔线，避免出现连续两条 ---

    return (
        "\n".join(header)
        + "---\n\n"
        + body
        + "\n\n---\n\n## 🗞️ 今日来源\n\n"
        + ranked
        + f"\n\n*内容由 AI 辅助整理，可能存在错误或遗漏，请以各来源原文为准。生成于 {datetime.now():%Y-%m-%d %H:%M}。*\n"
    )


def write_digest(md_text: str, out_dir: Path, filename_tpl: str, date_str: str) -> Path:
    date_dir = Path(out_dir) / date_str
    (date_dir / "assets" / date_str).mkdir(parents=True, exist_ok=True)
    base = date_dir / filename_tpl.format(date=date_str)
    path = base
    n = 1
    while path.exists():
        path = base.with_name(f"{base.stem}-{n}{base.suffix}")
        n += 1
    path.write_text(md_text, encoding="utf-8")
    return path
