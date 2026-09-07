from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import yaml

SOURCE_TYPES = ("rss", "hackernews", "changelog", "html_updates", "page_watch", "article_index", "huggingface", "github_org", "x_account", "model_catalog")
CATEGORIES = ("news", "paper", "community", "dev", "product")
URL_FIELDS = ("url", "api_url", "link_base")
ALLOWED_FIELDS = {
    "name",
    "type",
    "enabled",
    "url",
    "api_url",
    "link_base",
    "site",
    "code",
    "format",
    "item_limit",
    "min_score",
    "require_ai",
    "weight",
    "category",
    "content_xpath",
    "link_pattern",
}

FIELD_META = [
    {"name": "content_xpath", "label": "正文 XPath", "kind": "text"},
    {"name": "link_pattern", "label": "文章链接正则", "kind": "text"},
    {"name": "name", "label": "名称", "kind": "text", "required": True},
    {"name": "type", "label": "类型", "kind": "select", "required": True, "options": list(SOURCE_TYPES)},
    {"name": "enabled", "label": "启用", "kind": "boolean", "default": True},
    {"name": "url", "label": "URL", "kind": "url", "required_for": ["rss", "changelog", "html_updates"]},
    {"name": "api_url", "label": "API URL", "kind": "url"},
    {"name": "link_base", "label": "链接基址", "kind": "url"},
    {"name": "site", "label": "站点适配器", "kind": "text"},
    {"name": "code", "label": "接口代码", "kind": "text"},
    {"name": "format", "label": "格式", "kind": "text"},
    {"name": "item_limit", "label": "条目上限", "kind": "integer", "min": 1},
    {"name": "min_score", "label": "最低分", "kind": "integer", "min": 0},
    {"name": "require_ai", "label": "AI 关键词过滤", "kind": "boolean", "default": False},
    {"name": "weight", "label": "权重", "kind": "number", "default": 1},
    {"name": "category", "label": "分类", "kind": "select", "default": "news", "options": list(CATEGORIES)},
]


class SourceConfigError(ValueError):
    pass


def load_source_config(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    sources = data.get("sources")
    if not isinstance(sources, list):
        raise SourceConfigError("sources.yaml 必须包含 sources 列表")
    return {
        "sources": [normalize_source(source, idx) for idx, source in enumerate(sources)],
        "fields": FIELD_META,
        "types": list(SOURCE_TYPES),
        "categories": list(CATEGORIES),
    }


def save_source_config(path: Path, sources: list[dict]) -> list[dict]:
    normalized = validate_sources(sources)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        backup = path.with_name(f"{path.name}.{timestamp}.bak")
        shutil.copy2(path, backup)

    tmp = path.with_name(f".{path.name}.tmp")
    text = yaml.safe_dump(
        {"sources": normalized},
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return normalized


def validate_sources(sources: object) -> list[dict]:
    if not isinstance(sources, list):
        raise SourceConfigError("sources 必须是列表")
    normalized = [normalize_source(source, idx) for idx, source in enumerate(sources)]
    seen_names: set[str] = set()
    for source in normalized:
        folded_name = source["name"].casefold()
        if folded_name in seen_names:
            raise SourceConfigError(f"信息源名称不能重复: {source['name']}")
        seen_names.add(folded_name)
    return normalized


def normalize_source(source: object, idx: int = 0) -> dict:
    if not isinstance(source, dict):
        raise SourceConfigError(f"第 {idx + 1} 个信息源必须是对象")

    unknown = sorted(set(source) - ALLOWED_FIELDS)
    if unknown:
        raise SourceConfigError(f"第 {idx + 1} 个信息源包含不支持字段: {', '.join(unknown)}")

    normalized = {key: value for key, value in source.items() if value not in (None, "")}
    name = str(normalized.get("name", "")).strip()
    source_type = str(normalized.get("type", "rss")).strip() or "rss"
    if not name:
        raise SourceConfigError(f"第 {idx + 1} 个信息源缺少 name")
    if source_type not in SOURCE_TYPES:
        raise SourceConfigError(f"{name} 的 type 不支持: {source_type}")

    normalized["name"] = name
    normalized["type"] = source_type
    normalized["enabled"] = _to_bool(normalized.get("enabled", True))
    normalized["weight"] = _to_number(normalized.get("weight", 1), f"{name} 的 weight")
    if not 0 <= normalized["weight"] <= 5:
        raise SourceConfigError(f"{name} 的 weight 必须在 0 到 5 之间")
    if "category" in normalized and normalized["category"] not in CATEGORIES:
        raise SourceConfigError(f"{name} 的 category 不支持: {normalized['category']}")

    if source_type != "hackernews" and not normalized.get("url"):
        raise SourceConfigError(f"{name} 缺少 url")
    for field in URL_FIELDS:
        if field in normalized:
            normalized[field] = _validate_url(str(normalized[field]).strip(), f"{name} 的 {field}")

    if source_type == "article_index":
        if not normalized.get("link_pattern"):
            raise SourceConfigError(f"{name} 缺少 link_pattern")
        import re
        try:
            re.compile(normalized["link_pattern"])
        except (re.error, TypeError) as exc:
            raise SourceConfigError(f"{name} 链接匹配规则无效") from exc
    if normalized.get("content_xpath"):
        from lxml.etree import XPath, XPathSyntaxError
        try:
            XPath(normalized["content_xpath"])
        except (XPathSyntaxError, TypeError) as exc:
            raise SourceConfigError(f"{name} 正文 XPath 无效") from exc
    if "item_limit" in normalized:
        normalized["item_limit"] = _to_int(normalized["item_limit"], f"{name} 的 item_limit", minimum=1)
    if "min_score" in normalized:
        normalized["min_score"] = _to_int(normalized["min_score"], f"{name} 的 min_score", minimum=0)
    if "require_ai" in normalized:
        normalized["require_ai"] = _to_bool(normalized["require_ai"])

    return normalized


def _validate_url(value: str, label: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SourceConfigError(f"{label} 仅支持 http/https URL")
    return value


def _to_number(value: object, label: str) -> int | float:
    if isinstance(value, bool):
        raise SourceConfigError(f"{label} 必须是数字")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SourceConfigError(f"{label} 必须是数字") from exc
    return int(number) if number.is_integer() else number


def _to_int(value: object, label: str, *, minimum: int) -> int:
    if isinstance(value, bool):
        raise SourceConfigError(f"{label} 必须是整数")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise SourceConfigError(f"{label} 必须是整数") from exc
    if number < minimum:
        raise SourceConfigError(f"{label} 不能小于 {minimum}")
    return number


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return bool(value)
