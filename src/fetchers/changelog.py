"""官方 Changelog 抓取
支持 format: markdown（"## 版本号 [日期]" 分段的 CHANGELOG.md，如 GitHub raw 文件）
注意：changelog 一般不带发布时间，published 可能为 None，
     新条目判定依赖 SQLite 的跨天去重（同一版本 URL 只会出现一次）。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import httpx

from . import register, strip_html

UA = {"User-Agent": "ai-news-daily/0.1"}
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
DATE_RE = re.compile(
    r"^(\S+)\s*[({\[]?\s*((?:" + MONTHS + r"\s+\d{1,2},?\s+\d{4}|\d{4}-\d{2}-\d{2}))?\s*[)}\]]?\s*$"
)
BULLET_MD = re.compile(r"[*`_\[\]]")


@register("changelog")
def fetch_changelog(source: dict, limit: int) -> list[dict]:
    fmt = source.get("format", "markdown")
    if fmt != "markdown":
        raise ValueError(f"未知的 changelog 格式: {fmt}")
    return _fetch_markdown(source, limit)


def _fetch_markdown(source: dict, limit: int) -> list[dict]:
    resp = httpx.get(source["url"], timeout=30, headers=UA, follow_redirects=True)
    resp.raise_for_status()

    base_url = source.get("link_base") or source["url"]
    n = min(limit, int(source.get("item_limit", 5)))
    items = []
    for section in re.split(r"^##\s+", resp.text, flags=re.M)[1:]:
        if len(items) >= n:
            break
        lines = section.strip().splitlines()
        if not lines:
            continue
        m = DATE_RE.match(lines[0].strip())
        if not m or not re.match(r"^[vr]?\d", m.group(1)):
            continue  # 不带版本号的段落（Unreleased 等）跳过
        version, date_str = m.group(1), m.group(2)

        bullets = []
        for line in lines[1:]:
            s = line.strip()
            if s.startswith(("-", "*")):
                bullets.append(BULLET_MD.sub("", strip_html(s.lstrip("-*"))).strip())
        summary = "；".join(b for b in bullets if b)[:800]

        published = None
        if date_str:
            for fmt in ("%Y-%m-%d", "%B %d, %Y", "%B %d %Y"):
                try:
                    published = datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
                    break
                except ValueError:
                    pass

        items.append({
            "title": f"{source['name']} v{version} 更新",
            # 用锚点区分版本，否则同 URL 的版本之间会被跨天去重吞掉
            "url": f"{base_url}#{version.replace('.', '')}",
            "summary": summary,
            "published": published,
            # 标记条目类型：同工具多版本在成稿前合并；跳过正文提取（summary 即全部内容）
            "kind": "changelog",
            "no_extract": True,
        })
    return items
