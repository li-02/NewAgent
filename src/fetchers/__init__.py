"""抓取层：各源适配器统一产出 dict（title/url/source/summary/published/category/weight）"""
from __future__ import annotations

import re
from datetime import datetime
from html import unescape
from typing import Callable

FETCHERS: dict[str, Callable] = {}


def register(source_type: str):
    def deco(fn):
        FETCHERS[source_type] = fn
        return fn
    return deco


def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", unescape(text)).strip()


# AI 相关性关键词：供综合类源（如 Hacker News）做准入过滤
AI_KEYWORDS = re.compile(
    r"\bai\b|artificial intelligence|人工智能|机器学习|machine learning"
    r"|深度学习|deep learning|neural|神经网络|llm|large language|大模型"
    r"|gpt|gemini|claude|llama|qwen|deepseek|kimi|glm|混元|transformer"
    r"|diffusion|多模态|multimodal|agent|智能体|rlhf|fine.?tun|微调"
    r"|chatbot|chatgpt|copilot|agi|open.?weights",
    re.IGNORECASE,
)


def ai_relevant(text: str) -> bool:
    return bool(AI_KEYWORDS.search(text or ""))


def run_source(source: dict, limit: int) -> list[dict]:
    fn = FETCHERS.get(source.get("type", "rss"))
    if fn is None:
        raise ValueError(f"未知的源类型: {source.get('type')}")
    rows = fn(source, limit)
    out = []
    for row in rows:
        row.setdefault("source", source["name"])
        row.setdefault("category", source.get("category", "news"))
        row.setdefault("weight", float(source.get("weight", 1)))
        row.setdefault("summary", "")
        if source.get("category") == "community":
            row["evidence_type"] = "community"
        if not isinstance(row.get("published"), datetime):
            row["published"] = None
        # 综合类源可配 require_ai: true，只保留 AI 相关条目
        if source.get("require_ai") and not ai_relevant(
            f"{row['title']} {row['summary']}"
        ):
            continue
        out.append(row)
    return out


# 导入子模块以触发 @register 装饰器，完成抓取器注册
from . import changelog, hackernews, html_updates, rss, extended  # noqa: E402,F401
