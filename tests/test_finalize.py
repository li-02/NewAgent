from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()
