from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.article_archive import (
    append_carryover,
    backup_filtered_draft,
    carryover_candidates,
    record_export,
    snapshot_filtered_items,
)
from finalize import parse_draft_text


def draft(*rows: tuple[str, str]) -> str:
    overview = ["## 概览", "", "### 要闻", ""]
    blocks = []
    for no, (title, url) in enumerate(rows, 1):
        overview.append(f"- {title} `#{no}`")
        blocks.extend(["", "---", "", f"## {title} `#{no}`", "", f"{title}正文", "", "```text", url, "```"])
    return "\n".join([*overview, *blocks, ""]) + "\n"


class ArticleArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = self.root / "output"
        self.archive = self.root / "archive"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_snapshot_keeps_items_beyond_daily_top_n(self) -> None:
        path = snapshot_filtered_items("2026-09-09", [
            {"title": "一", "url": "https://example.com/1", "category": "news"},
            {"title": "二", "url": "https://example.com/2", "category": "news"},
            {"title": "三", "url": "https://example.com/3", "category": "paper"},
        ], self.archive)

        saved = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(len(saved["items"]), 3)
        self.assertEqual([row["position"] for row in saved["items"]], [1, 2, 3])

    def test_yesterday_candidates_exclude_every_successfully_exported_article(self) -> None:
        date = "2026-09-09"
        date_dir = self.output / date
        date_dir.mkdir(parents=True)
        source = date_dir / f"AI早报-{date}.md"
        source.write_text(draft(
            ("第一篇", "https://example.com/1"),
            ("第二篇", "https://example.com/2"),
        ), encoding="utf-8")
        backup_filtered_draft(source, date, self.archive)
        snapshot_filtered_items(date, [
            {"title": "第一篇", "url": "https://example.com/1", "category": "news"},
            {"title": "第二篇", "url": "https://example.com/2", "category": "news"},
            {"title": "未进 Top N", "url": "https://example.com/3", "category": "paper", "summary": "候选摘要"},
        ], self.archive)
        overview, blocks = parse_draft_text(source.read_text(encoding="utf-8"))
        record_export(date, overview, blocks, [1], "终稿.md", self.archive)

        source_date, rows = carryover_candidates("2026-09-10", self.output, self.archive)

        self.assertEqual(source_date, date)
        self.assertEqual([row["title"] for row in rows], ["第二篇", "未进 Top N"])

    def test_selected_carryover_is_added_to_today_draft(self) -> None:
        yesterday = "2026-09-09"
        today = "2026-09-10"
        snapshot_filtered_items(yesterday, [
            {"title": "昨日候选", "url": "https://example.com/yesterday", "category": "news", "summary": "昨日摘要"},
        ], self.archive)
        current = draft(("今日文章", "https://example.com/today"))
        _, rows = carryover_candidates(today, self.output, self.archive)

        updated, added = append_carryover(
            today, yesterday, [rows[0]["key"]], current, self.output, self.archive
        )

        self.assertEqual(added, 1)
        self.assertIn("### 昨日补选", updated)
        self.assertIn("- 昨日候选 `#2`", updated)
        self.assertIn("## 昨日候选 `#2`", updated)
        self.assertIn("https://example.com/yesterday", updated)
        overview, blocks = parse_draft_text(updated)
        self.assertEqual(overview[2]["ov_title"], "昨日候选")
        self.assertIn(2, blocks)


if __name__ == "__main__":
    unittest.main()
