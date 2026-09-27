"""单条新闻改造：17 字标题上限 + 「为什么重要」停用。

背景：原 Prompt 把标题放宽到 30 字，终稿又把多条标题用「；」拼成 120 字，
而公众号列表页只完整显示约 17 字、小红书标题框硬限 20 字，读者实际看不到重点。
「为什么重要」段曾短暂启用，实测只是复述正文事实，已整体移除。
"""
from __future__ import annotations

import unittest

from src.pipeline.generate import (
    TITLE_CHAR_LIMIT,
    USER_PROMPT,
    assemble_digest,
    count_title_chars,
    parse_llm_items,
    trim_title,
)


def _item(title: str, url: str = "https://example.com/1", **extra) -> dict:
    base = {
        "title": title,
        "url": url,
        "source": "测试源",
        "category": "ai",
        "summary": "测试摘要",
        "sources": [("测试源", url)],
    }
    base.update(extra)
    return base


class TitleLimitTests(unittest.TestCase):
    def test_prompt_requires_short_single_focus_titles(self) -> None:
        self.assertIn("12~17字", USER_PROMPT)
        self.assertIn("单一焦点", USER_PROMPT)

    def test_limit_matches_wechat_truncation_point(self) -> None:
        # 公众号手机列表页约 17 个汉字后截断，是三个平台里最短的
        self.assertEqual(TITLE_CHAR_LIMIT, 17)

    def test_short_title_is_untouched(self) -> None:
        self.assertEqual(trim_title("OpenAI 暂停最强模型训练"), "OpenAI 暂停最强模型训练")

    def test_long_title_is_trimmed_to_limit(self) -> None:
        long_title = "OpenAI 暂停最强模型训练 沙箱模型曾违规接入互联网并调用外部模型"
        trimmed = trim_title(long_title)
        self.assertLessEqual(count_title_chars(trimmed), TITLE_CHAR_LIMIT)
        self.assertTrue(long_title.startswith(trimmed))

    def test_trimming_strips_dangling_punctuation(self) -> None:
        trimmed = trim_title("阿里发布新一代推理模型，算力提升三倍，价格下降一半")
        self.assertFalse(trimmed.endswith(("，", "、", "；", "：", ",")))

    def test_english_tokens_are_not_split_in_half(self) -> None:
        # 长英文词不应被切成 "Open" 这种半截形式
        trimmed = trim_title("Anthropic 发布 Claude Opus 5.5 并强化安全防护机制")
        self.assertNotRegex(trimmed, r"[A-Za-z]$")

    def test_ascii_counts_half_width(self) -> None:
        # 17 个汉字 ≈ 34 个英文字符的显示宽度
        self.assertEqual(count_title_chars("abcdefghij"), 5)
        self.assertEqual(count_title_chars("十个汉字十个字"), 7)


class NoWhySectionTests(unittest.TestCase):
    """「为什么重要」字段已停用：LLM 实际产出的内容是复述正文事实，零新增信息。

    例：正文已写「十个月内从 28% 升至 80%」「每张照片耗时约 3 分钟、未来可能
    用于汽车维修」，该段又把同样三点换个说法重复一遍。已从 Prompt、解析与
    装配中全部移除。
    """

    def test_prompt_no_longer_requests_why_field(self) -> None:
        self.assertNotIn("为什么重要", USER_PROMPT)

    def test_ignores_why_field_if_model_still_emits_it(self) -> None:
        text = (
            "===ITEM===\n"
            "URL: https://example.com/a\n"
            "标题: OpenAI 暂停最强模型训练\n"
            "为什么重要: 这段即便出现也不应进入成稿。\n"
            "分类: AI\n"
            "TLDR: 摘要\n"
            "BODY:\n正文。\n===END==="
        )
        parsed = parse_llm_items(text)
        self.assertEqual(len(parsed), 1)
        self.assertNotIn("why", parsed[0])

    def test_digest_does_not_render_why_section(self) -> None:
        result = assemble_digest([], [_item("测试标题")], "2026-09-27")
        self.assertNotIn("为什么重要", result)

    def test_single_export_filters_why_from_existing_draft(self) -> None:
        """回归：历史草稿里已写入「为什么重要」，导出必须过滤掉。

        只删生成端不够——导出是逐行搬运草稿内容，旧草稿会把它原样带进单条稿。
        """
        from finalize import build_single

        overview = {3: {"ov_title": "GPT-6 Astra找出家具装错", "category": "AI"}}
        blocks = {3: [
            "## GPT-6 Astra找出家具装错 `#3`",
            "",
            "正文第一段。",
            "",
            "> **为什么重要**：正文已经说过的内容再复述一遍。",
            "",
            "```",
            "https://example.com/a",
            "```",
        ]}
        md, _ = build_single(overview, blocks, 3, "2026-09-27")
        self.assertNotIn("为什么重要", md)
        self.assertIn("正文第一段。", md)
        self.assertIn("https://example.com/a", md)


class TitleAssemblyTests(unittest.TestCase):
    def test_assembled_title_respects_limit(self) -> None:
        long_title = "OpenAI 暂停最强模型训练 沙箱模型曾违规接入互联网"
        result = assemble_digest([], [_item(long_title)], "2026-09-27")
        heading = next(line for line in result.splitlines() if line.startswith("## "))
        self.assertLessEqual(count_title_chars(heading[3:].split(" `#")[0]), TITLE_CHAR_LIMIT)


if __name__ == "__main__":
    unittest.main()
