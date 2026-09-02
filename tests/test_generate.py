from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from src.pipeline.generate import SYSTEM_PROMPT, call_llm
from src.outputs.markdown import render_digest


class GenerateTests(unittest.TestCase):
    def test_render_digest_omits_daily_heading(self) -> None:
        result = render_digest(
            [], "2026-09-01", "## 概览\n", {"fetched": 0, "kept": 0, "source_count": 0}
        )

        self.assertNotIn("# AI 早报 2026-09-01", result)
        self.assertTrue(result.startswith("> 生成时间："))

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


if __name__ == "__main__":
    unittest.main()
