from __future__ import annotations

import unittest
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import finalize
from finalize import build_final


class FinalizeTests(unittest.TestCase):
    def test_final_header_is_compact_and_has_no_generation_or_audit_block(self) -> None:
        overview = {1: {"ov_title": "测试资讯", "category": "要闻"}}
        blocks = {
            1: [
                "## 测试资讯 `#1`",
                "",
                "这是正文。",
                "",
                "```text",
                "https://example.com/news",
                "```",
            ]
        }

        result, _ = build_final(overview, blocks, [1], "2026-08-31")

        self.assertTrue(result.startswith("# 今日资讯 | AI日报0831\n\n## 测试资讯"))
        self.assertNotIn("## 概览", result)
        self.assertNotIn("生成时间", result)
        self.assertNotIn("审核清单", result)
        self.assertNotIn("需要的截图", result)
        self.assertNotIn("## 🔗 信息源", result)

    def test_final_omits_empty_image_placeholder_when_item_has_no_pasted_image(self) -> None:
        overview = {1: {"ov_title": "未配图资讯", "category": "要闻"}}
        blocks = {1: ["## 未配图资讯 `#1`", "", "正文"]}

        result, rebuilt = build_final(overview, blocks, [1], "2026-09-01")

        self.assertNotIn("截图占位", result)
        self.assertNotIn("待补充截图", result)
        self.assertNotIn("assets/2026-09-01/", result)
        self.assertEqual(rebuilt[0]["shot"], "")

    def test_final_includes_overview_only_when_requested(self) -> None:
        overview = {1: {"ov_title": "测试资讯", "category": "要闻"}}
        blocks = {1: ["## 测试资讯 `#1`", "", "正文"]}

        result, _ = build_final(
            overview, blocks, [1], "2026-09-01", include_overview=True
        )

        self.assertIn("## 概览", result)

    def test_final_uses_custom_single_line_title(self) -> None:
        overview = {1: {"ov_title": "测试资讯", "category": "要闻"}}
        blocks = {1: ["## 测试资讯 `#1`", "", "正文"]}

        result, _ = build_final(
            overview, blocks, [1], "2026-09-01", title="# 自定义标题\n第二行"
        )

        self.assertTrue(result.startswith("# 自定义标题 第二行\n"))

    def test_final_includes_sources_only_when_requested(self) -> None:
        overview = {1: {"ov_title": "测试资讯", "category": "要闻"}}
        blocks = {
            1: [
                "## 测试资讯 `#1`", "", "正文", "", "```",
                "https://example.com/news", "```",
            ]
        }

        result, _ = build_final(
            overview, blocks, [1], "2026-09-01", include_sources=True
        )

        self.assertIn("## 🔗 信息源", result)
        self.assertIn("- https://example.com/news", result)

    def test_cli_export_records_article_as_exported(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            date = "2026-09-09"
            date_dir = root / "output" / date
            date_dir.mkdir(parents=True)
            (date_dir / f"AI早报-{date}.md").write_text(
                "## 概览\n\n### 要闻\n\n- 测试资讯 `#1`\n\n"
                "## 测试资讯 `#1`\n\n正文\n\n```text\nhttps://example.com/news\n```\n",
                encoding="utf-8",
            )
            with patch.object(finalize, "ROOT", root), patch.object(
                sys, "argv", ["finalize.py", "1", "--date", date]
            ):
                code = finalize.main()

            ledger = json.loads((root / "data" / "article-archive" / "exported.json").read_text(encoding="utf-8"))
            self.assertEqual(code, 0)
            self.assertEqual(ledger["exports"][0]["date"], date)
            self.assertEqual(len(ledger["exports"][0]["article_keys"]), 1)


if __name__ == "__main__":
    unittest.main()
