"""关键词粗排打分（先规则后 LLM 的两步走里，这里是零成本的规则步）"""
from __future__ import annotations

import re

RULES = [
    (r"\bai\b|artificial intelligence|人工智能", 2.0),
    (r"model|llm|gpt|gemini|claude|llama|qwen|deepseek|kimi|glm|混元|大模型", 3.0),
    (r"发布|launch|release|announc|unveil|introduc|上线|现在可用", 2.0),
    (r"open.?sourc|开源", 2.0),
    (r"agent|智能体|coding|编程", 1.5),
    (r"funding|融资|acquisition|收购|估值|billion", 1.5),
    (r"benchmark|sota|论文|paper|arxiv", 1.0),
    (r"regulat|法案|policy|政策|ban|禁令|safety|安全", 1.0),
    (r"pricing|降价|免费|free tier", 0.5),
]


def score_item(item: dict, preferences: dict | None = None) -> float:
    text = f"{item['title']} {item.get('summary', '')}".lower()
    bonus = sum(w for pattern, w in RULES if re.search(pattern, text, re.IGNORECASE))
    preferences = preferences or {}
    hits = {"boost": [], "downrank": [], "blocked": []}
    for key, factor in (("boost_keywords", 2.0), ("downrank_keywords", -2.0), ("block_keywords", -1000.0)):
        for keyword in preferences.get(key, []) or []:
            if str(keyword).strip().lower() in text:
                hits["blocked" if key == "block_keywords" else ("downrank" if key == "downrank_keywords" else "boost")].append(str(keyword))
                bonus += factor
    item["ranking_matches"] = hits
    return bonus + float(item.get("weight", 1))


def rank(items: list[dict], preferences: dict | None = None) -> list[dict]:
    for it in items:
        it["score"] = round(score_item(it, preferences), 2)
    items.sort(key=lambda it: it["score"], reverse=True)
    return items
