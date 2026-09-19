from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from src.pipeline.generate import (
    SYSTEM_PROMPT,
    USER_PROMPT,
    assemble_digest,
    call_llm,
    clean_meta_reporting,
    normalize_person_names,
)
from src.outputs.markdown import render_digest


class GenerateTests(unittest.TestCase):
    def test_render_digest_omits_daily_heading(self) -> None:
        result = render_digest(
            [], "2026-09-01", "## 概览\n", {"fetched": 0, "kept": 0, "source_count": 0}
        )

        self.assertNotIn("# AI 早报 2026-09-01", result)
        self.assertTrue(result.startswith("> 生成时间："))

    def test_render_digest_omits_audit_checklist_when_screenshots_are_needed(self) -> None:
        result = render_digest(
            [{
                "title": "测试资讯",
                "url": "https://example.com/news",
                "source": "测试源",
                "screenshot_path": "assets/2026-09-01/01-test.jpg",
            }],
            "2026-09-01",
            "## 概览\n",
            {"fetched": 1, "kept": 1, "source_count": 1},
        )

        self.assertNotIn("审核清单", result)
        self.assertNotIn("需要的截图", result)
        self.assertIn("## 概览", result)

    @patch("src.pipeline.generate.httpx.post")
    def test_call_llm_sends_news_role_as_system_message(self, post: Mock) -> None:
        response = Mock()
        response.json.return_value = {
            "choices": [{"message": {"content": "===ITEM===\nURL: https://example.com\n===END==="}}]
        }
        post.return_value = response

        call_llm(
            {
                "base_url": "https://api.example.com/v1/",
                "api_key": "test-key",
                "model": "test-model",
            },
            "测试素材",
        )

        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["messages"][0], {"role": "system", "content": SYSTEM_PROMPT})
        self.assertEqual(payload["messages"][1]["role"], "user")
        self.assertIn("测试素材", payload["messages"][1]["content"])
        response.raise_for_status.assert_called_once_with()

    def test_clean_meta_reporting_removes_source_platform_metrics(self) -> None:
        text = "一个名为 Collusion 的新站点被发现。该发现已在 Hacker News 上获得`1483`分热度，讨论数达`1191`条。"
        result = clean_meta_reporting(text)
        self.assertEqual(result, "一个名为 Collusion 的新站点被发现。")

    def test_community_item_does_not_add_generic_disclaimer(self) -> None:
        item = {
            "title": "用户分享开发工具",
            "url": "https://example.com/post",
            "source": "社区",
            "category": "community",
            "evidence_type": "community",
            "summary": "一名开发者分享了自己制作的工具。",
            "text": "该开发者介绍了工具的主要用途。",
            "sources": [("社区", "https://example.com/post")],
        }

        result = assemble_digest([], [item], "2026-09-05")

        self.assertNotIn("社区用户报告", result)
        self.assertNotIn("尚未获官方确认", result)
        self.assertIn("该开发者介绍了工具的主要用途。", result)

    def test_source_categories_fall_back_to_technology_sections(self) -> None:
        items = []
        for index, category in enumerate(("ai", "chips", "hardware", "internet", "frontier", "business", "policy"), 1):
            items.append({
                "title": f"测试资讯{index}",
                "url": f"https://example.com/{index}",
                "source": "测试源",
                "category": category,
                "summary": "测试摘要",
                "sources": [("测试源", f"https://example.com/{index}")],
            })

        result = assemble_digest([], items, "2026-09-16")

        for section in ("AI", "芯片与硬件", "互联网与产品", "前沿科技", "商业与资本", "政策与产业"):
            self.assertIn(f"### {section}", result)

    def test_english_person_names_are_rewritten_to_chinese(self) -> None:
        item = {
            "title": "Jensen Huang 谈下一代加速卡",
            "url": "https://example.com/nvidia",
            "source": "测试源",
            "category": "chips",
            "summary": "NVIDIA 首席执行官 Jensen Huang 表示，新产品将于年内出货。",
            "text": "Jensen Huang 还提到 Lisa Su 所在公司的竞争。",
            "sources": [("测试源", "https://example.com/nvidia")],
        }

        result = assemble_digest([], [item], "2026-09-19")

        self.assertIn("黄仁勋", result)
        self.assertIn("苏姿丰", result)
        self.assertNotIn("Jensen Huang", result)
        self.assertNotIn("Lisa Su", result)
        self.assertEqual(item["display_title"], "黄仁勋谈下一代加速卡")

    def test_chinese_annotated_person_names_keep_only_the_chinese_form(self) -> None:
        self.assertEqual(
            normalize_person_names("黄仁勋（Jensen Huang）在会上发言，Sam Altman's 计划暂未公布。"),
            "黄仁勋在会上发言，萨姆·奥尔特曼的计划暂未公布。",
        )
        self.assertEqual(normalize_person_names("Fei-Fei Li (李飞飞) 团队发布了新模型。"), "李飞飞团队发布了新模型。")

    def test_unknown_person_names_are_left_untouched(self) -> None:
        self.assertEqual(
            normalize_person_names("工程师 Zhang Wei 与 John Doe 参与了测试。"),
            "工程师 Zhang Wei 与 John Doe 参与了测试。",
        )

    def test_prompts_require_chinese_person_names(self) -> None:
        for prompt in (SYSTEM_PROMPT, USER_PROMPT):
            self.assertIn("人名一律用中文", prompt)
        self.assertIn("Jensen Huang 写作黄仁勋", SYSTEM_PROMPT)
        self.assertIn("“黄仁勋”", USER_PROMPT)


if __name__ == "__main__":
    unittest.main()
