"""正文提取：trafilatura 解析，失败/反爬时返回空串（退回 RSS 摘要）"""
from __future__ import annotations

import httpx
import trafilatura
import re

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
}


BYLINE_RE = re.compile(
    r"(?:[\w\u4e00-\u9fff·]{1,12}\s+)?发自\s+.*?"
    r"(?:\|\s*公众号\s*[A-Za-z0-9_-]+|公众号\s*[A-Za-z0-9_-]+)",
    re.IGNORECASE,
)


def clean_extracted_text(text: str, title: str = "") -> str:
    """去掉正文提取器常带出的标题、媒体署名和网页导航噪声。"""
    text = " ".join((text or "").split())
    if title:
        text = re.sub(rf"^\s*{re.escape(title)}\s*", "", text, count=1)
    text = BYLINE_RE.sub("", text, count=1)
    return text.strip()


def fetch_text(
    url: str, max_chars: int = 2500, timeout: float = 15.0, title: str = ""
) -> str:
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        text = trafilatura.extract(resp.text, include_comments=False, include_tables=False) or ""
        return clean_extracted_text(text, title=title)[:max_chars]
    except Exception:
        return ""
