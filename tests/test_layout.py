# -*- coding: utf-8 -*-
"""文章版式约束：
1. 每篇文章删除开头的“引用”（TLDR 引言块）；
2. 每篇文章先放图、后文字（草稿截图占位、终稿/单条导出、粘贴截图槽位一致生效）。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import finalize
import webui
from finalize import build_final, build_single
from src.pipeline.generate import assemble_digest


class DraftLayoutTests(unittest.TestCase):
    def test_draft_item_is_image_first_without_quote_intro(self) -> None:
        item = {
            "title": "测试资讯",
            "url": "https://example.com/news",
            "source": "测试源",
            "category": "news",
            "summary": "一条摘要。",
            "text": "一段正文。",
            "screenshot_path": "assets/2026-09-13/01-test.jpg",
        }

        result = assemble_digest([], [item], "2026-09-13")

        self.assertNotIn("\n> ", result)  # 不再输出开头的引用摘要（引言）
        self.assertLess(
            result.index("![待补充截图"), result.index("一段正文。")
        )


class FinalLayoutTests(unittest.TestCase):
    def test_final_strips_leading_quote_intro(self) -> None:
        overview = {1: {"ov_title": "测试资讯", "category": "要闻"}}
        blocks = {
            1: [
                "## 测试资讯 `#1`",
                "",
                "> 这是开头的引用引言。",
                "",
                "正文第一段。",
                "",
                "```",
                "https://example.com/news",
                "```",
            ]
        }

        result, _ = build_final(overview, blocks, [1], "2026-09-13")

        self.assertNotIn("这是开头的引用引言", result)
        self.assertIn("正文第一段。", result)

    def test_final_puts_image_before_text(self) -> None:
        overview = {1: {"ov_title": "测试资讯", "category": "要闻"}}
        blocks = {
            1: [
                "## 测试资讯 `#1`",
                "",
                "正文第一段。",
                "",
                "![截图](assets/2026-09-13/01-test.png)",
                "",
                "正文第二段。",
            ]
        }

        result, rebuilt = build_final(overview, blocks, [1], "2026-09-13")

        self.assertLess(
            result.index("![截图](assets/2026-09-13/01-test.png)"),
            result.index("正文第一段。"),
        )
        self.assertTrue(rebuilt[0]["has_img"])

    def test_final_rescues_existing_screenshot_to_top(self) -> None:
        """截图已按占位路径落盘但未粘贴时，终稿也应把图片放到条目开头。"""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            date = "2026-09-13"
            asset_root = root / date
            image = asset_root / "assets" / date / "01-test.jpg"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"\xff\xd8fake")

            overview = {1: {"ov_title": "测试资讯", "category": "要闻"}}
            blocks = {
                1: [
                    "## 测试资讯 `#1`",
                    "",
                    "> 开头的引用引言。",
                    "",
                    "正文。",
                    "",
                    "<!-- 📷 截图占位 | 测试源｜测试资讯",
                    f"     操作：打开原文链接，截取页面首屏，保存为 output/{date}/assets/{date}/01-test.jpg -->",
                    f"![待补充截图：测试源｜测试资讯](assets/{date}/01-test.jpg)",
                ]
            }

            result, rebuilt = build_final(overview, blocks, [1], date, asset_root)

            self.assertTrue(rebuilt[0]["has_img"])
            self.assertLess(result.index("01-test.jpg"), result.index("正文。"))


class SingleExportLayoutTests(unittest.TestCase):
    def test_single_strips_quote_and_puts_image_first(self) -> None:
        overview = {1: {"ov_title": "测试资讯", "category": "要闻"}}
        blocks = {
            1: [
                "## 测试资讯 `#1`",
                "",
                "> 开头的引用引言。",
                "",
                "正文。",
                "",
                "![截图](assets/2026-09-13/01-test.png)",
            ]
        }

        result, meta = build_single(overview, blocks, 1, "2026-09-13")

        self.assertNotIn("开头的引用引言", result)
        self.assertLess(
            result.index("![截图](assets/2026-09-13/01-test.png)"),
            result.index("正文。"),
        )
        self.assertEqual(meta["shot"], "")

    def test_single_pending_shot_sits_right_after_title(self) -> None:
        overview = {1: {"ov_title": "测试资讯", "category": "要闻"}}
        blocks = {1: ["## 测试资讯 `#1`", "", "正文。"]}

        result, meta = build_single(overview, blocks, 1, "2026-09-13")

        self.assertTrue(meta["shot"])
        self.assertLess(result.index("![待补充截图"), result.index("正文。"))


class PasteSlotLayoutTests(unittest.TestCase):
    def test_pasted_screenshot_lands_right_after_title(self) -> None:
        text = "## 概览\n\n### 要闻\n\n- 测试资讯 `#1`\n\n## 测试资讯 `#1`\n\n正文\n"

        updated = webui.attach_item_image(text, 1, "assets/2026-09-13/item-01-test.png")

        lines = updated.splitlines()
        title_idx = next(
            i for i, ln in enumerate(lines) if ln.startswith("## 测试资讯")
        )
        self.assertEqual(lines[title_idx + 2], webui.IMAGE_SLOT)
        self.assertEqual(lines[title_idx + 3], "![截图](assets/2026-09-13/item-01-test.png)")

    def test_insert_placeholder_helpers_exposed(self) -> None:
        # webui 从 finalize 复用插入逻辑，保证接口不回退
        self.assertIs(webui.insert_placeholder, finalize.insert_placeholder)


if __name__ == "__main__":
    unittest.main()
