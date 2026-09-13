"""Daily filtered-draft snapshots and exported-article tracking."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path

from finalize import ITEM_HEAD, link_fence, parse_draft_text

_LEDGER_LOCK = threading.Lock()


def article_key(title: str, block: list[str]) -> str:
    """Return a stable identity, preferring the article's source URL."""
    urls = link_fence(block)
    identity = urls[0].strip() if urls else " ".join(title.split()).casefold()
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def article_keys_from_text(text: str) -> set[str]:
    overview, blocks = parse_draft_text(text)
    return {
        article_key(overview.get(no, {}).get("ov_title") or _block_title(block), block)
        for no, block in blocks.items()
    }


def item_key(item: dict) -> str:
    identity = str(item.get("url") or " ".join(str(item.get("title", "")).split()).casefold()).strip()
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def snapshot_filtered_items(date: str, items: list[dict], archive_root: Path) -> Path:
    """Persist every ranked, non-blocked item before the daily top-N cutoff."""
    target_dir = archive_root / date
    target_dir.mkdir(parents=True, exist_ok=True)
    base = target_dir / "filtered-items.json"
    target = base
    number = 1
    while target.exists():
        target = target_dir / f"filtered-items-{number}.json"
        number += 1
    serializable = []
    for position, item in enumerate(items, 1):
        row = {
            key: item.get(key)
            for key in ("title", "url", "source", "category", "summary", "text", "score")
        }
        row["position"] = position
        published = item.get("published")
        row["published"] = published.isoformat() if hasattr(published, "isoformat") else (str(published) if published else None)
        row["sources"] = [list(source) for source in item.get("sources", [])]
        row["key"] = item_key(item)
        serializable.append(row)
    target.write_text(json.dumps({"date": date, "items": serializable}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def backup_filtered_draft(path: Path, date: str, archive_root: Path) -> Path:
    """Keep an immutable copy of every generated, filtered daily draft."""
    target_dir = archive_root / date
    target_dir.mkdir(parents=True, exist_ok=True)
    base = target_dir / "filtered.md"
    target = base
    number = 1
    while target.exists():
        target = target_dir / f"filtered-{number}.md"
        number += 1
    shutil.copy2(path, target)
    return target


def latest_filtered_draft(date: str, output_root: Path, archive_root: Path) -> Path | None:
    """Read the newest archive; support pre-feature daily drafts as fallback."""
    archive_dir = archive_root / date
    archived = list(archive_dir.glob("filtered*.md")) if archive_dir.is_dir() else []
    if archived:
        return max(archived, key=lambda item: item.stat().st_mtime_ns)
    date_dir = output_root / date
    drafts = []
    if date_dir.is_dir():
        drafts = [
            item for item in date_dir.glob(f"AI早报-{date}*.md")
            if "终稿" not in item.name and "单条" not in item.name
        ]
    legacy = output_root / f"AI早报-{date}.md"
    if legacy.is_file():
        drafts.append(legacy)
    return max(drafts, key=lambda item: item.stat().st_mtime_ns) if drafts else None


def _ledger_path(archive_root: Path) -> Path:
    return archive_root / "exported.json"


def _read_ledger(archive_root: Path) -> dict:
    path = _ledger_path(archive_root)
    if not path.is_file():
        return {"version": 1, "exports": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"version": 1, "exports": []}
    return data if isinstance(data, dict) and isinstance(data.get("exports"), list) else {"version": 1, "exports": []}


def _write_ledger(archive_root: Path, data: dict) -> None:
    archive_root.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".exported-", suffix=".json.tmp", dir=str(archive_root))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, _ledger_path(archive_root))
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def record_export(
    date: str,
    overview: dict,
    blocks: dict,
    picks: list[int],
    export_name: str,
    archive_root: Path,
) -> None:
    keys = []
    for no in picks:
        if no not in blocks:
            continue
        title = overview.get(no, {}).get("ov_title") or _block_title(blocks[no])
        keys.append(article_key(title, blocks[no]))
    if not keys:
        return
    with _LEDGER_LOCK:
        ledger = _read_ledger(archive_root)
        ledger["exports"].append({
            "date": date,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "file": export_name,
            "article_keys": keys,
        })
        _write_ledger(archive_root, ledger)


def exported_keys(archive_root: Path) -> set[str]:
    with _LEDGER_LOCK:
        ledger = _read_ledger(archive_root)
    return {str(key) for export in ledger.get("exports", []) for key in export.get("article_keys", [])}


def _block_title(block: list[str]) -> str:
    if block and (match := ITEM_HEAD.match(block[0])):
        return match.group(1).strip()
    return "未命名条目"


def _latest_item_snapshot(date: str, archive_root: Path) -> Path | None:
    folder = archive_root / date
    snapshots = list(folder.glob("filtered-items*.json")) if folder.is_dir() else []
    return max(snapshots, key=lambda item: item.stat().st_mtime_ns) if snapshots else None


def _category_label(value: str) -> str:
    return {"news": "要闻", "paper": "论文", "tool": "工具", "product": "产品"}.get(value, value or "昨日补选")


def _snapshot_block(row: dict) -> list[str]:
    title = str(row.get("title") or "未命名条目")
    content = str(row.get("text") or row.get("summary") or "昨日筛选文章，正文待补充。").strip()
    urls = [str(source[1]) for source in row.get("sources", []) if isinstance(source, list) and len(source) > 1 and source[1]]
    if row.get("url") and row["url"] not in urls:
        urls.insert(0, str(row["url"]))
    block = [f"## {title}", "", content]
    if urls:
        block.extend(["", "```text", *urls, "```"])
    return block


def _source_articles(date: str, output_root: Path, archive_root: Path) -> list[dict]:
    rich_by_key = {}
    draft = latest_filtered_draft(date, output_root, archive_root)
    if draft is not None:
        overview, blocks = parse_draft_text(draft.read_text(encoding="utf-8"))
        for no, block in blocks.items():
            title = overview.get(no, {}).get("ov_title") or _block_title(block)
            key = article_key(title, block)
            rich_by_key[key] = {
                "key": key, "no": no, "title": title,
                "category": overview.get(no, {}).get("category") or "昨日补选",
                "block": block,
            }
    snapshot = _latest_item_snapshot(date, archive_root)
    if snapshot is None:
        return list(rich_by_key.values())
    try:
        rows = json.loads(snapshot.read_text(encoding="utf-8")).get("items", [])
    except (OSError, ValueError, TypeError, AttributeError):
        return list(rich_by_key.values())
    articles = []
    for row in rows:
        key = str(row.get("key") or item_key(row))
        rich = rich_by_key.get(key)
        articles.append(rich or {
            "key": key,
            "no": int(row.get("position") or len(articles) + 1),
            "title": str(row.get("title") or "未命名条目"),
            "category": _category_label(str(row.get("category") or "")),
            "block": _snapshot_block(row),
        })
    return articles


def carryover_candidates(today: str, output_root: Path, archive_root: Path) -> tuple[str, list[dict]]:
    source_date = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    done = exported_keys(archive_root)
    rows = []
    for article in _source_articles(source_date, output_root, archive_root):
        key = article["key"]
        if key in done:
            continue
        rows.append({
            "key": key,
            "no": article["no"],
            "title": article["title"],
            "category": article["category"],
            "has_img": any(line.lstrip().startswith(("![[", "![")) for line in article["block"]),
        })
    return source_date, rows


def _copy_block_images(block: list[str], source_date: str, today: str, output_root: Path) -> list[str]:
    source_root = (output_root / source_date).resolve()
    target_dir = output_root / today / "assets" / today
    target_dir.mkdir(parents=True, exist_ok=True)
    image_re = re.compile(r"(!\[[^\]]*\]\()([^)]+)(\))")

    def replace(match: re.Match) -> str:
        raw = match.group(2).strip()
        if re.match(r"^(?:https?:|data:|/|#)", raw, re.I):
            return match.group(0)
        source = (source_root / raw.replace("/", os.sep)).resolve()
        if not source.is_file() or source_root not in source.parents:
            return match.group(0)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()[:10]
        target = target_dir / f"carryover-{digest}{source.suffix.lower()}"
        if not target.exists():
            shutil.copy2(source, target)
        return f"{match.group(1)}assets/{today}/{target.name}{match.group(3)}"

    return [image_re.sub(replace, line) for line in block]


def append_carryover(
    today: str,
    source_date: str,
    selected_keys: list[str],
    current_text: str,
    output_root: Path,
    archive_root: Path,
) -> tuple[str, int]:
    expected = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    if source_date != expected:
        raise ValueError("只能补选昨天的文章")
    source_articles = _source_articles(source_date, output_root, archive_root)
    if not source_articles:
        raise ValueError("没有找到昨天的筛选备份")
    current_overview, current_blocks = parse_draft_text(current_text)
    existing = {
        article_key(current_overview.get(no, {}).get("ov_title") or _block_title(block), block)
        for no, block in current_blocks.items()
    }
    allowed = {row["key"] for row in carryover_candidates(today, output_root, archive_root)[1]}
    wanted = set(selected_keys) & allowed
    chosen = []
    for article in source_articles:
        title, key = article["title"], article["key"]
        if key in wanted and key not in existing:
            chosen.append((title, article["block"]))
    if not chosen:
        return current_text, 0

    next_no = max(current_blocks, default=0) + 1
    overview_lines = ["", "### 昨日补选"]
    appended_blocks = []
    for offset, (title, source_block) in enumerate(chosen):
        no = next_no + offset
        overview_lines.append(f"- {title} `#{no}`")
        block = _copy_block_images(source_block, source_date, today, output_root)
        block[0] = f"## {title} `#{no}`"
        appended_blocks.extend(["", "---", "", *block])

    lines = current_text.rstrip().splitlines()
    first_item = next((
        index for index, line in enumerate(lines)
        if ITEM_HEAD.match(line)
        and not line.startswith(("## 概览", "## 🗞️ 今日来源", "## ✅ 审核清单"))
    ), None)
    if any(line.startswith("## 概览") for line in lines) and first_item is not None:
        lines[first_item:first_item] = overview_lines + [""]
    else:
        lines = ["## 概览", *overview_lines, "", *lines]
    source_heading = next((index for index, line in enumerate(lines) if line.startswith("## 🗞️ 今日来源")), len(lines))
    lines[source_heading:source_heading] = appended_blocks + [""]
    return "\n".join(lines).rstrip() + "\n", len(chosen)
