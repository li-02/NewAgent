from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import webui


class SourcesApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.sources_file = Path(self.temp.name) / "sources.yaml"
        self.sources_file.write_text(
            """sources:
  - name: Existing RSS
    type: rss
    url: https://example.com/feed.xml
    weight: 2
  - name: Hacker News
    type: hackernews
    min_score: 150
""",
            encoding="utf-8",
        )
        self.path_patch = patch.object(webui, "SOURCES_FILE", self.sources_file)
        self.path_patch.start()
        webui.app.config.update(TESTING=True)
        self.client = webui.app.test_client()

    def tearDown(self) -> None:
        self.path_patch.stop()
        self.temp.cleanup()

    def test_get_sources_returns_config_and_field_metadata(self) -> None:
        payload = self.client.get("/api/sources").get_json()

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["sources"][0]["name"], "Existing RSS")
        self.assertTrue(payload["sources"][0]["enabled"])
        self.assertIn("rss", payload["types"])
        self.assertIn("product", payload["categories"])
        self.assertIn({"name": "name", "label": "名称", "kind": "text", "required": True}, payload["fields"])

    def test_settings_page_is_available(self) -> None:
        response = self.client.get("/settings")
        try:
            self.assertEqual(response.status_code, 200)
            self.assertIn("信息源设置", response.get_data(as_text=True))
        finally:
            response.close()

    def test_put_sources_rejects_unknown_fields(self) -> None:
        response = self.client.put("/api/sources", json={
            "sources": [{
                "name": "Bad",
                "type": "rss",
                "url": "https://example.com/feed.xml",
                "extra": "nope",
            }]
        })

        self.assertEqual(response.status_code, 400)
        self.assertIn("不支持字段", response.get_json()["error"])

    def test_put_sources_allows_only_http_urls(self) -> None:
        response = self.client.put("/api/sources", json={
            "sources": [{
                "name": "Bad",
                "type": "rss",
                "url": "ftp://example.com/feed.xml",
            }]
        })

        self.assertEqual(response.status_code, 400)
        self.assertIn("http/https", response.get_json()["error"])

    def test_put_sources_rejects_duplicate_names(self) -> None:
        response = self.client.put("/api/sources", json={
            "sources": [
                {"name": "AI News", "type": "rss", "url": "https://example.com/a.xml"},
                {"name": "ai news", "type": "rss", "url": "https://example.com/b.xml"},
            ]
        })

        self.assertEqual(response.status_code, 400)
        self.assertIn("不能重复", response.get_json()["error"])

    def test_put_sources_rejects_weight_outside_supported_range(self) -> None:
        response = self.client.put("/api/sources", json={
            "sources": [{
                "name": "Too Heavy",
                "type": "rss",
                "url": "https://example.com/feed.xml",
                "weight": 6,
            }]
        })

        self.assertEqual(response.status_code, 400)
        self.assertIn("0 到 5", response.get_json()["error"])

    def test_put_sources_saves_normalized_config_and_creates_backup(self) -> None:
        response = self.client.put("/api/sources", json={
            "sources": [{
                "name": "New RSS",
                "type": "rss",
                "url": "https://example.com/new.xml",
                "enabled": "false",
                "weight": "3",
                "require_ai": "true",
            }]
        })

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertFalse(payload["sources"][0]["enabled"])
        self.assertEqual(payload["sources"][0]["weight"], 3)
        text = self.sources_file.read_text(encoding="utf-8")
        self.assertIn("name: New RSS", text)
        self.assertTrue(list(self.sources_file.parent.glob("sources.yaml.*.bak")))

    def test_source_test_caps_limit_and_does_not_save_config(self) -> None:
        with patch("webui.run_source", return_value=[{
            "title": "Item",
            "url": "https://example.com/item",
            "source": "Unsaved RSS",
            "category": "news",
            "summary": "Summary",
            "published": datetime(2026, 9, 1, tzinfo=timezone.utc),
        }]) as run_source:
            response = self.client.post("/api/sources/test", json={
                "limit": 99,
                "source": {
                    "name": "Unsaved RSS",
                    "type": "rss",
                    "url": "https://example.com/feed.xml",
                },
            })

        self.assertEqual(response.status_code, 200)
        run_source.assert_called_once()
        self.assertEqual(run_source.call_args.args[1], 3)
        payload = response.get_json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["items"][0]["published"], "2026-09-01T00:00:00+00:00")
        self.assertIn("Existing RSS", self.sources_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
