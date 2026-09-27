"""条目正文里出现代码块时，不能把代码块当成「来源链接块」删掉。

原实现取「最后一个代码块」，正文含代码示例时会把文章代码删掉。
新实现只认含 http 链接的代码块，且要求它之后没有实质正文。
"""
from __future__ import annotations

import unittest

from finalize import link_fence, strip_link_fence


class LinkFenceTests(unittest.TestCase):
    def test_collects_urls_from_link_block(self) -> None:
        block = [
            "## 标题 `#1`",
            "",
            "正文内容。",
            "",
            "```",
            "https://example.com/a",
            "https://example.com/b",
            "```",
        ]
        self.assertEqual(link_fence(block), ["https://example.com/a", "https://example.com/b"])

    def test_deduplicates_repeated_urls(self) -> None:
        block = ["```", "https://example.com/a", "https://example.com/a", "```"]
        self.assertEqual(link_fence(block), ["https://example.com/a"])

    def test_empty_when_no_fence(self) -> None:
        self.assertEqual(link_fence(["## 标题", "正文"]), [])


class StripLinkFenceTests(unittest.TestCase):
    def test_strips_trailing_source_block(self) -> None:
        lines = ["正文内容。", "", "```", "https://example.com/a", "```"]
        self.assertEqual(strip_link_fence(lines), ["正文内容。"])

    def test_keeps_code_block_in_body(self) -> None:
        lines = [
            "正文说明：",
            "",
            "```python",
            "print('hello')",
            "```",
            "",
            "更多正文。",
        ]
        self.assertEqual(strip_link_fence(lines), lines)

    def test_keeps_body_code_block_and_strips_trailing_source_block(self) -> None:
        lines = [
            "示例代码：",
            "```python",
            "x = 1",
            "```",
            "结论段落。",
            "",
            "```",
            "https://example.com/src",
            "```",
        ]
        result = strip_link_fence(lines)
        self.assertIn("x = 1", result)
        self.assertIn("结论段落。", result)
        self.assertNotIn("https://example.com/src", result)

    def test_link_block_in_the_middle_is_kept(self) -> None:
        # 链接块之后还有正文 → 不是条目末尾的来源块，不能删
        lines = ["```", "https://example.com/a", "```", "后面还有正文。"]
        self.assertEqual(strip_link_fence(lines), lines)


if __name__ == "__main__":
    unittest.main()
