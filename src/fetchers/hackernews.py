"""Hacker News 官方 API 抓取，作为热度信号源"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from . import register, strip_html

API = "https://hacker-news.firebaseio.com/v0"


@register("hackernews")
def fetch_hackernews(source: dict, limit: int) -> list[dict]:
    min_score = int(source.get("min_score", 100))
    rows = []
    with httpx.Client(timeout=20, headers={"User-Agent": "ai-news-daily/0.1"}) as client:
        ids = client.get(f"{API}/topstories.json").json()[: limit * 2]
        for story_id in ids:
            try:
                item = client.get(f"{API}/item/{story_id}.json").json()
            except httpx.HTTPError:
                continue
            if not item or item.get("type") != "story":
                continue
            if item.get("score", 0) < min_score or not item.get("url"):
                continue
            rows.append({
                "title": strip_html(item.get("title", "")),
                "url": item["url"],
                "summary": (
                    f"HN 热度 {item.get('score')} 分、{item.get('descendants', 0)} 条讨论。"
                    f"讨论帖：https://news.ycombinator.com/item?id={story_id}"
                ),
                "published": datetime.fromtimestamp(item.get("time", 0), tz=timezone.utc),
            })
            if len(rows) >= limit:
                break
    return rows
