from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from src.pipeline.generate import SYSTEM_PROMPT, assemble_digest, call_llm, clean_meta_reporting
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


if __name__ == "__main__":
    unittest.main()
