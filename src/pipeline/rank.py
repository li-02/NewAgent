"""关键词粗排打分（先规则后 LLM 的两步走里，这里是零成本的规则步）"""
from __future__ import annotations

import re

RULES = [
    (r"\bai\b|artificial intelligence|人工智能|大模型|llm|gpt|gemini|claude|llama|qwen|deepseek|kimi|glm|混元", 2.5),
    (r"chip|semiconductor|芯片|半导体|gpu|cpu|npu|晶圆|光刻|制程", 2.5),
    (r"hardware|device|smartphone|laptop|wearable|硬件|手机|电脑|可穿戴|消费电子", 1.5),
    (r"cloud|software|platform|internet|browser|security|云计算|软件|平台|互联网|浏览器|网络安全", 1.5),
    (r"robot|autonomous|space|quantum|biotech|energy|机器人|自动驾驶|商业航天|量子|生物科技|新能源", 2.0),
    (r"发布|launch|release|announc|unveil|introduc|上线|现在可用", 2.0),
    (r"open.?sourc|开源", 2.0),
    (r"agent|智能体|coding|编程", 1.5),
    (r"funding|融资|acquisition|收购|merger|并购|估值|财报|revenue|billion", 1.5),
    (r"benchmark|sota|论文|paper|arxiv", 1.0),
    (r"regulat|法案|policy|政策|ban|禁令|antitrust|反垄断|出口管制|safety|安全", 1.5),
    (r"pricing|降价|免费|free tier", 0.5),
]

CATEGORY_GROUPS = {
    "news": "headline",
    "ai": "ai",
    "chips": "hardware",
    "hardware": "hardware",
    "internet": "internet",
    "dev": "internet",
    "product": "internet",
    "community": "internet",
    "frontier": "frontier",
    "paper": "frontier",
    "business": "business",
    "policy": "policy",
}


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


def select_balanced(items: list[dict], limit: int) -> list[dict]:
    """优先保留每个已出现科技栏目的最高分条目，再按总分补满名额。"""
    if limit <= 0:
        return []
    representatives: list[dict] = []
    represented: set[str] = set()
    for item in items:
        group = CATEGORY_GROUPS.get(str(item.get("category") or "news"), "headline")
        if group not in represented:
            representatives.append(item)
            represented.add(group)
        if len(representatives) >= limit:
            return representatives

    selected_ids = {id(item) for item in representatives}
    selected = representatives + [item for item in items if id(item) not in selected_ids]
    return selected[:limit]
