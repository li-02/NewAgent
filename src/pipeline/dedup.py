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


def is_same_story(a: str, b: str, threshold: float = 0.75) -> bool:
    # 两个标题都带版本号且版本不同 → 不同的发布，直接排除合并
    va = set(VERSION_RE.findall(a))
    vb = set(VERSION_RE.findall(b))
    if va and vb and va != vb:
        return False
    ta = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", a.lower())
    tb = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", b.lower())
    if ta and tb and SequenceMatcher(None, ta, tb).ratio() >= threshold:
        return True
    # 兜底：标题措辞不同但共享关键实体（人名/公司/产品名）也视为同一事件，
    # 如 "Sony Music, Warner sue Anthropic..." vs "Sony Music and Warner Chappell are suing Anthropic"
    wa = {w for w in re.findall(r"[a-z0-9]{3,}|[\u4e00-\u9fff]+", a.lower()) if w not in STOPWORDS}
    wb = {w for w in re.findall(r"[a-z0-9]{3,}|[\u4e00-\u9fff]+", b.lower()) if w not in STOPWORDS}
    if not wa or not wb:
        return False
    overlap = wa & wb
    return len(overlap) >= 3 and len(overlap) / min(len(wa), len(wb)) >= 0.5


def dedup(items: list[dict], known: set[str]) -> list[dict]:
    """known 为数据库中已见过的 url_hash，命中直接丢弃；
    同事件/同 URL 的条目合并进第一条，各来源保留在 sources 列表中。"""
    merged: list[dict] = []
    for item in items:
        h = url_hash(item["url"])
        if h in known:
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
