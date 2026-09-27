"""去重：URL 归一化精确去重 + 标题相似度合并（同一事件多家报道归为一条）"""
from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

TRACKING_PREFIX = ("utm_", "fbclid", "gclid", "spm", "scm", "ref", "ref_src", "from")


def normalize_url(url: str) -> str:
    try:
        p = urlparse(url.strip())
    except ValueError:
        return url.strip().lower()
    host = p.netloc.lower().removeprefix("www.")
    query = [
        (k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
        if not k.lower().startswith(TRACKING_PREFIX)
    ]
    # 保留 fragment：changelog 等源用 #锚点 区分同页面的不同条目
    return urlunparse(
        (p.scheme or "https", host, p.path.rstrip("/") or "/", "", urlencode(query), p.fragment)
    )


def url_hash(url: str) -> str:
    return hashlib.sha1(normalize_url(url).encode("utf-8")).hexdigest()


STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "at", "by",
    "is", "are", "was", "were", "be", "been", "its", "it", "this", "that", "as", "after",
    "from", "over", "up", "out", "new", "how", "why", "what", "will", "can", "not", "no",
}


VERSION_RE = re.compile(r"\d+(?:\.\d+)+")


def is_same_story(a: str, b: str, threshold: float = 0.75, entity_fallback: bool = True) -> bool:
    """两个标题是否指同一事件。

    entity_fallback 控制是否启用「共享关键实体」兜底规则：该规则为**同日**
    同一事件的多家报道设计（候选集小、可信度高），例如
    "Sony Music, Warner sue Anthropic" vs "Sony Music and Warner Chappell are suing Anthropic"。
    但用在**跨天**比对时会大量误判——它只看是否共享 3 个词且重叠过半，
    而 "APOD: 2026 September 27 – Andromeda" 与
    "APOD: 2026 September 20 – Analemma" 恰好共享 apod/september/2026 三个词，
    就被当成同一事件，导致每日固定发布的系列内容（每日一图、日报）被整体判掉。
    因此跨天判重必须传 entity_fallback=False，只信任标题相似度。
    """
    # 两个标题都带版本号且版本不同 → 不同的发布，直接排除合并
    va = set(VERSION_RE.findall(a))
    vb = set(VERSION_RE.findall(b))
    if va and vb and va != vb:
        return False
    ta = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", a.lower())
    tb = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", b.lower())
    if ta and tb and SequenceMatcher(None, ta, tb).ratio() >= threshold:
        return True
    if not entity_fallback:
        return False
    # 兜底：标题措辞不同但共享关键实体（人名/公司/产品名）也视为同一事件
    wa = {w for w in re.findall(r"[a-z0-9]{3,}|[\u4e00-\u9fff]+", a.lower()) if w not in STOPWORDS}
    wb = {w for w in re.findall(r"[a-z0-9]{3,}|[\u4e00-\u9fff]+", b.lower()) if w not in STOPWORDS}
    if not wa or not wb:
        return False
    overlap = wa & wb
    return len(overlap) >= 3 and len(overlap) / min(len(wa), len(wb)) >= 0.5


def is_recent_story(title: str, recent_titles: list[str], threshold: float = 0.62) -> bool:
    """标题是否与最近若干天已发布的某条报道属于同一事件。

    跨天判重无法靠 URL（同一事件被不同媒体、不同 URL 反复报道），只能靠标题。
    实测本项目真实标题的相似度分布后取 0.62：
      - 同事件不同媒体：「调查称 OpenAI 智能体借短链藏匿攻击载荷…」
        vs「研究人员发现 OpenAI 智能体利用短链接藏匿攻击载荷」→ 0.630 ✓ 判重
      - 同实体不同事件：「TikTok 与阿拉巴马州达成 1 亿美元和解」
        vs「TikTok 在阿拉巴马州面临新的青少年安全诉讼」→ 0.533 ✗ 不判重
    阈值取 0.62 可分开这两类；低于它的同实体标题交给同日 is_same_story 处理。

    必须传 entity_fallback=False：跨天比对时「共享关键实体」兜底会把
    每日固定发布的系列内容（如 "APOD: 2026 September 27 – Andromeda" 与
    "APOD: 2026 September 20 – Analemma"，共享 apod/september/2026）误判为重复。
    """
    return any(
        is_same_story(title, old, threshold, entity_fallback=False)
        for old in recent_titles
        if old
    )


def dedup(items: list[dict], known: set[str], recent_titles: list[str] | None = None) -> list[dict]:
    """known 为数据库中已见过的 url_hash，命中直接丢弃；
    同事件/同 URL 的条目合并进第一条，各来源保留在 sources 列表中。

    recent_titles 为最近若干天已收录的标题：用于拦截「同一事件、不同媒体、
    不同 URL」的跨天重复（这类重复靠 url_hash 抓不到，会让读者连续几天
    看到同一件事，是掉粉主因）。传 None 表示不做跨天标题判重。
    """
    recent = list(recent_titles or [])
    merged: list[dict] = []
    for item in items:
        h = url_hash(item["url"])
        if h in known:
            continue
        if recent and is_recent_story(item["title"], recent):
            continue
        item["_hash"] = h
        same_url = next((k for k in merged if k["_hash"] == h), None)
        if same_url is not None:
            pair = (item["source"], item["url"])
            if pair not in same_url["sources"]:
                same_url["sources"].append(pair)
            continue
        target = next((k for k in merged if is_same_story(k["title"], item["title"])), None)
        if target is None:
            item["sources"] = [(item["source"], item["url"])]
            merged.append(item)
        else:
            target["sources"].append((item["source"], item["url"]))
    return merged
