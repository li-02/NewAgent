"""HTML/API update page fetcher for official pages without RSS feeds."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from html import unescape
from urllib.parse import urljoin, urlparse

import httpx

from . import register, strip_html

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36 ai-news-daily/0.1"
    ),
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
}

DATE_RE = re.compile(
    r"20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}"
    r"|20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*(?:日)?"
    r"|(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},?\s+20\d{2}",
    re.IGNORECASE,
)

BOT_MARKERS = (
    "cf-chl",
    "cloudflare ray",
    "captcha",
    "recaptcha",
    "hcaptcha",
    "人机验证",
    "安全验证",
    "滑块验证",
)


@register("html_updates")
def fetch_html_updates(source: dict, limit: int) -> list[dict]:
    site = (source.get("site") or "generic").lower()
    if site == "qwen":
        return _fetch_qwen(source, limit)

    html = _request_text(source["url"])
    _raise_if_blocked(source["url"], html)

    if site in {"zhipu", "qoder"}:
        rows = _parse_component_updates(html, source, limit)
    elif site == "workbuddy":
        rows = _parse_heading_updates(html, source, limit)
    elif site == "moonshot":
        rows = _parse_moonshot(html, source, limit)
    elif site == "deepseek":
        if "api-docs.deepseek.com" in urlparse(source["url"]).netloc:
            rows = _parse_deepseek_api(html, source, limit)
        else:
            rows = _parse_deepseek_news(html, source, limit)
    else:
        rows = _parse_generic_links(html, source, limit)

    if rows:
        return rows[:limit]
    return _parse_generic_links(html, source, limit)


def _request_text(url: str) -> str:
    try:
        resp = httpx.get(url, timeout=30, headers=UA, follow_redirects=True)
    except httpx.TransportError as exc:
        if not _is_ssl_proxy_error(exc):
            raise
        with httpx.Client(
            timeout=30,
            headers=UA,
            follow_redirects=True,
            trust_env=False,
        ) as client:
            resp = client.get(url)

    if resp.status_code in {401, 403, 429}:
        raise RuntimeError(f"可能被反爬或限流拦截: HTTP {resp.status_code}")
    resp.raise_for_status()
    return resp.text


def _request_json(url: str):
    text = _request_text(url)
    return json.loads(text)


def _is_ssl_proxy_error(exc: httpx.TransportError) -> bool:
    text = str(exc).lower()
    return "ssl" in text or "unexpected_eof" in text or "eof occurred" in text


def _raise_if_blocked(url: str, html: str) -> None:
    low = html[:5000].lower()
    if any(marker in low for marker in BOT_MARKERS):
        raise RuntimeError(f"可能遇到人机验证或反爬页面: {url}")


def _parse_qwen_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return _parse_date(value)


def _fetch_qwen(source: dict, limit: int) -> list[dict]:
    code = source.get("code", "news.news-list")
    url = source.get("api_url") or f"https://qwen.ai/api/page_config?code={code}"
    data = _request_json(url)
    if isinstance(data, dict):
        data = data.get("data") or data.get("articles") or []

    rows = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        title = strip_html(entry.get("title") or "")
        if not title:
            continue
        article_url = (
            entry.get("url")
            or entry.get("href")
            or _qwen_url_from_token_link(entry.get("tokenLinks"))
            or f"https://qwen.ai/news/{entry.get('id')}"
        )
        rows.append(
            {
                "title": title,
                "url": article_url,
                "summary": strip_html(
                    entry.get("description") or entry.get("introduction") or ""
                )[:800],
                "published": _parse_qwen_date(entry.get("date")),
                "no_extract": True,
            }
        )
    # The page-config API does not guarantee newest-first ordering.
    rows.sort(
        key=lambda row: row.get("published") or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return rows[:limit]


def _qwen_url_from_token_link(token_link: str | None) -> str | None:
    if not token_link:
        return None
    parsed = urlparse(token_link)
    path = parsed.path
    if path.endswith("/index.json"):
        path = path[: -len("/index.json")]
    if path:
        return f"https://qwen.ai{path}"
    return token_link


def _parse_component_updates(html: str, source: dict, limit: int) -> list[dict]:
    blocks = _split_on_component(html, "update-label")
    rows = []
    for label_html, body_html in blocks:
        label = _clean(label_html)
        date = _first_date(label)
        if not date:
            continue
        title = _first_component_text(body_html, "update-title")
        description = _first_component_text(body_html, "update-description")
        content = _first_component_text(body_html, "update-content")
        summary = description or content or body_html
        if not title:
            title = label
        if source.get("site") in {"zhipu", "qoder"} and title == label:
            first = _first_sentence(summary)
            title = first or f"{source['name']} {label}"
        rows.append(
            _item(
                title=title,
                url=_anchor_url(source["url"], f"{date}-{title}"),
                summary=summary,
                published=_parse_date(date),
            )
        )
        if len(rows) >= limit:
            break
    return rows


def _split_on_component(html: str, part: str) -> list[tuple[str, str]]:
    pattern = re.compile(
        rf"<[^>]+data-component-part=[\"']{re.escape(part)}[\"'][^>]*>(.*?)</[^>]+>",
        re.S | re.I,
    )
    matches = list(pattern.finditer(html))
    blocks = []
    for idx, match in enumerate(matches):
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(html)
        blocks.append((match.group(1), html[match.end() : end]))
    return blocks


def _first_component_text(html: str, part: str) -> str:
    match = re.search(
        rf"<[^>]+data-component-part=[\"']{re.escape(part)}[\"'][^>]*>(.*?)</[^>]+>",
        html,
        re.S | re.I,
    )
    return _clean(match.group(1)) if match else ""


def _parse_heading_updates(html: str, source: dict, limit: int) -> list[dict]:
    headings = list(
        re.finditer(r"<h([2-3])[^>]*>(.*?)</h\1>", html, flags=re.S | re.I)
    )
    rows = []
    for idx, match in enumerate(headings):
        title = _clean(match.group(2))
        date = _first_date(title)
        if not date:
            continue
        end = headings[idx + 1].start() if idx + 1 < len(headings) else len(html)
        summary = _clean(html[match.end() : end])
        rows.append(
            _item(
                title=title,
                url=_anchor_url(source["url"], title),
                summary=summary,
                published=_parse_date(date),
            )
        )
        if len(rows) >= limit:
            break
    return rows


def _parse_deepseek_api(html: str, source: dict, limit: int) -> list[dict]:
    h2s = list(re.finditer(r"<h2[^>]*>(.*?)</h2>", html, re.S | re.I))
    rows = []
    for idx, match in enumerate(h2s):
        text = _clean(match.group(1))
        if not text.lower().startswith("date:"):
            continue
        date = _first_date(text)
        if not date:
            continue
        end = h2s[idx + 1].start() if idx + 1 < len(h2s) else len(html)
        titles = [
            _clean(m.group(1))
            for m in re.finditer(r"<h3[^>]*>(.*?)</h3>", html[match.end() : end], re.S | re.I)
        ]
        summary = _clean(html[match.end() : end])
        title = "DeepSeek API 更新"
        if titles:
            title = f"{title}: {' / '.join(titles[:3])}"
        rows.append(
            _item(
                title=title,
                url=_anchor_url(source["url"], text),
                summary=summary,
                published=_parse_date(date),
                extra={"kind": "changelog", "no_extract": True},
            )
        )
        if len(rows) >= limit:
            break
    return rows


def _parse_deepseek_news(html: str, source: dict, limit: int) -> list[dict]:
    rows = []
    for match in re.finditer(
        r"<a\b[^>]*class=[\"'][^\"']*ds-news(?:-hero-card|-list-item)[^\"']*[\"']"
        r"[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
        html,
        flags=re.S | re.I,
    ):
        block = match.group(2)
        title = _first_heading(block) or _clean(block)
        date = _first_date(block)
        if not title or not date:
            continue
        rows.append(
            _item(
                title=title,
                url=urljoin(source["url"], unescape(match.group(1))),
                summary=_summary_from_paragraphs(block),
                published=_parse_date(date),
            )
        )
        if len(rows) >= limit:
            break
    return rows


def _parse_moonshot(html: str, source: dict, limit: int) -> list[dict]:
    rows = []
    seen: set[str] = set()
    for href, body in _iter_links(html):
        if "/blog/" not in href:
            continue
        text = _clean(body)
        date = _first_date(text)
        title = DATE_RE.sub("", text, count=1).strip(" -|")
        if not date or not title or href in seen:
            continue
        seen.add(href)
        rows.append(
            _item(
                title=title,
                url=urljoin(source["url"], href),
                summary=text,
                published=_parse_date(date) if date else None,
                extra={"no_extract": True},
            )
        )
        if len(rows) >= limit:
            break
    return rows


def _parse_generic_links(html: str, source: dict, limit: int) -> list[dict]:
    rows = []
    seen: set[str] = set()
    for href, body in _iter_links(html):
        text = _clean(body)
        if not text or len(text) < 8:
            continue
        date = _first_date(text)
        if not date and not any(k in text.lower() for k in ("release", "update", "发布", "更新")):
            continue
        url = urljoin(source["url"], href)
        if url in seen:
            continue
        seen.add(url)
        rows.append(
            _item(
                title=DATE_RE.sub("", text, count=1).strip(" -|") or text,
                url=url,
                summary=text,
                published=_parse_date(date) if date else None,
            )
        )
        if len(rows) >= limit:
            break
    return rows


def _iter_links(html: str):
    for match in re.finditer(
        r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
        html,
        flags=re.S | re.I,
    ):
        yield unescape(match.group(1)), match.group(2)


def _first_heading(html: str) -> str:
    match = re.search(r"<h[1-4][^>]*>(.*?)</h[1-4]>", html, re.S | re.I)
    return _clean(match.group(1)) if match else ""


def _summary_from_paragraphs(html: str) -> str:
    paragraphs = [_clean(m.group(1)) for m in re.finditer(r"<p[^>]*>(.*?)</p>", html, re.S | re.I)]
    useful = [p for p in paragraphs if p and not DATE_RE.fullmatch(p) and p.lower() != "news"]
    return "；".join(useful[-2:])[:800]


def _item(
    *,
    title: str,
    url: str,
    summary: str,
    published: datetime | None,
    extra: dict | None = None,
) -> dict:
    row = {
        "title": strip_html(title)[:240],
        "url": url,
        "summary": strip_html(summary)[:800],
        "published": published,
    }
    if extra:
        row.update(extra)
    return row


def _clean(value: str) -> str:
    value = re.sub(r"<(script|style|svg)\b.*?</\1>", " ", value or "", flags=re.S | re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", unescape(value)).strip(" \u200b")


def _first_date(value: str) -> str | None:
    text = _clean(value)
    match = DATE_RE.search(text)
    return match.group(0) if match else None


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    text = _clean(value).replace("/", "-").replace(".", "-")
    zh = re.search(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})", text)
    if zh:
        text = f"{zh.group(1)}-{int(zh.group(2)):02d}-{int(zh.group(3)):02d}"
    for fmt in ("%Y-%m-%d", "%Y-%m-%d", "%B %d, %Y", "%B %d %Y"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    match = re.search(r"20\d{2}-\d{1,2}-\d{1,2}", text)
    if match:
        y, m, d = [int(part) for part in match.group(0).split("-")]
        return datetime(y, m, d, tzinfo=timezone.utc)
    return None


def _first_sentence(text: str) -> str:
    text = strip_html(text)
    match = re.match(r"(.{8,80}?[。！？!?])", text)
    return match.group(1) if match else text[:80]


def _anchor_url(base_url: str, text: str) -> str:
    slug = _slug(text)
    return f"{base_url}#{slug}" if slug else base_url


def _slug(text: str) -> str:
    text = _clean(text).lower()
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "-", text, flags=re.UNICODE)
    return text.strip("-")[:80]
