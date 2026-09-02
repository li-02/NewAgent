from __future__ import annotations

import unittest
from unittest.mock import patch

from src.fetchers.html_updates import (
    _parse_component_updates,
    _parse_deepseek_api,
    _parse_heading_updates,
    fetch_html_updates,
)


class HtmlUpdatesTests(unittest.TestCase):
    def test_component_updates_parse_date_title_and_summary(self) -> None:
        html = """
        <div data-component-part="update-label">2026-08-26</div>
        <div data-component-part="update-title">GLM-5.3-Flash 原生多模态模型上线</div>
        <div data-component-part="update-content">
          <p>原生融入视觉能力。</p><p>支持代码和浏览器协同。</p>
        </div>
        """

        rows = _parse_component_updates(
            html,
            {"name": "智谱 AI", "site": "zhipu", "url": "https://example.com"},
            5,
        )

        self.assertEqual(len(rows), 1)
        self.assertIn("GLM-5.3-Flash", rows[0]["title"])
        self.assertIn("视觉能力", rows[0]["summary"])
        self.assertEqual(rows[0]["published"].date().isoformat(), "2026-08-26")

    def test_heading_updates_parse_workbuddy_style_changelog(self) -> None:
        html = """
        <h2>WorkBuddy 更新日志</h2>
        <h2>5.4.7 版本发布（2026-09-01）</h2>
        <p>新增订阅和用量设置页。</p>
        <h2>5.4.5 版本发布（2026-08-30）</h2>
        <p>优化长对话浏览。</p>
        """

        rows = _parse_heading_updates(
            html,
            {"name": "腾讯 WorkBuddy", "url": "https://example.com"},
            5,
        )

        self.assertEqual(
            [row["published"].date().isoformat() for row in rows],
            ["2026-09-01", "2026-08-30"],
        )
        self.assertIn("订阅和用量", rows[0]["summary"])

    def test_deepseek_api_groups_h3_titles_under_date(self) -> None:
        html = """
        <h1>Change Log</h1>
        <h2>Date: 2026-08-21</h2>
        <h3>DeepSeek-V4-Flash-Vision-Exp Release</h3>
        <p>Model released.</p>
        <h2>Date: 2026-08-13</h2>
        <h3>DeepSeek-V4-Pro Update</h3>
        """

        rows = _parse_deepseek_api(
            html,
            {"name": "DeepSeek API", "url": "https://example.com"},
            5,
        )

        self.assertEqual(len(rows), 2)
        self.assertIn("Vision", rows[0]["title"])
        self.assertIn("Model released", rows[0]["summary"])

    @patch("src.fetchers.html_updates._request_json")
    def test_qwen_fetches_page_config_api(self, request_json) -> None:
        request_json.return_value = [
            {
                "title": "Older Qwen update",
                "date": "2024-01-01T00:00:00.000Z",
                "tokenLinks": "https://docs.qwenlm.ai/news/older/index.json",
            },
            {
                "title": "QVQ-Max: Think with Evidence",
                "date": "2025-03-25T16:00:04.000Z",
                "description": "Visual reasoning model release.",
                "tokenLinks": "https://docs.qwenlm.ai/news/qvq-max-preview/index.json",
            }
        ]

        rows = fetch_html_updates(
            {"name": "阿里千问", "site": "qwen", "url": "https://qwen.ai/news"},
            5,
        )

        self.assertEqual(rows[0]["url"], "https://qwen.ai/news/qvq-max-preview")
        self.assertEqual(rows[0]["published"].year, 2025)


if __name__ == "__main__":
    unittest.main()
