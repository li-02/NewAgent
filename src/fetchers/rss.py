"""通用 RSS/Atom 抓取"""
from __future__ import annotations

from datetime import datetime, timezone

import feedparser

from . import register, strip_html
from .html_updates import _request_text


def _to_datetime(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass
    return None


@register("rss")
def fetch_rss(source: dict, limit: int) -> list[dict]:
    parsed = feedparser.parse(_request_text(source["url"]))
    if not parsed.entries and (parsed.bozo or not parsed.version or parsed.feed.get("title", "").lower() == "resource not found"):
        raise ValueError("RSS 返回内容无法解析或不是有效订阅源")
    items = []
    for entry in parsed.entries[:limit]:
        url = (entry.get("link") or "").strip()
        title = strip_html(entry.get("title", ""))
        if not url or not title:
            continue
        items.append({
            "title": title,
            "url": url,
            "summary": strip_html(entry.get("summary", ""))[:800],
            "published": _to_datetime(entry),
        })
    return items
