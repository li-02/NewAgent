from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import base64
import yaml

import webui
from src.article_archive import snapshot_filtered_items


class WebUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)
        self.output_patch = patch.object(webui, "OUTPUT", self.output)
        self.output_patch.start()
        self.log_dir_patch = patch.object(webui, "RUN_LOG_DIR", self.output / "logs")
        self.log_dir_patch.start()
        self.archive_patch = patch.object(webui, "ARTICLE_ARCHIVE", self.output / "article-archive")
        self.archive_patch.start()
        webui.app.config.update(TESTING=True)
        self.client = webui.app.test_client()

    def tearDown(self) -> None:
        self.archive_patch.stop()
        self.output_patch.stop()
        self.log_dir_patch.stop()
        self.temp.cleanup()

    def test_state_uses_latest_numbered_draft(self) -> None:
        date = "2026-08-31"
        date_dir = self.output / date
        date_dir.mkdir(parents=True)
        (date_dir / f"AI早报-{date}.md").write_text("old", encoding="utf-8")
        latest = date_dir / f"AI早报-{date}-1.md"
        latest.write_text("new", encoding="utf-8")
        latest.touch()

        payload = self.client.get(f"/api/state?date={date}").get_json()

        self.assertEqual(payload["content"], "new")

    def test_index_exposes_toggle_for_run_log(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="toggleLogBtn"', html)
        self.assertIn("查看运行日志", html)
        self.assertIn('id="copyRunLogBtn"', html)

    def test_each_run_log_is_persisted_to_a_separate_file(self) -> None:
        with webui.run_lock:
            webui.run_state["logs"].clear()
            webui.run_state["log_file"] = None
        webui.start_run_log()
        webui.append_run_log("测试日志")

        state = webui.snapshot_run_state()
        log_file = Path(state["log_file"])
        self.assertTrue(log_file.is_file())
        self.assertIn("测试日志", log_file.read_text(encoding="utf-8"))

    def test_index_includes_image_shelf_count_marker(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("image-shelf-count", response.get_data(as_text=True))

    def test_index_item_picker_is_expanded_and_carryover_collapsed_by_default(self) -> None:
        html = self.client.get("/").get_data(as_text=True)

        self.assertIn('<details id="itemPicker" class="item-picker" open>', html)
        self.assertIn('<details id="carryoverPanel" class="carryover-panel" hidden>', html)
        self.assertNotIn('id="carryoverPanel" class="carryover-panel" hidden open', html)
        self.assertIn('<button id="addCarryoverBtn" type="button">加入今天</button>', html)
        self.assertIn('className = "source-link"', (webui.ROOT / "static" / "app.js").read_text(encoding="utf-8"))

    def test_items_expose_original_links(self) -> None:
        text = """## 概览

### 要闻

- 测试资讯 `#1`

## 测试资讯 `#1`

正文

```text
https://example.com/article
```
"""

        item = webui.items_from_text(text)[0]

        self.assertEqual(item["links"], ["https://example.com/article"])

    def test_image_shelf_renders_every_article(self) -> None:
        app_js = (webui.ROOT / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn("const imageItems = items;", app_js)
        self.assertNotIn("items.filter((it) => it.needs_image)", app_js)

    def test_state_exposes_all_draft_dates_for_history_selector(self) -> None:
        for date in ("2026-08-29", "2026-08-31", "2026-08-30"):
            date_dir = self.output / date
            date_dir.mkdir(parents=True)
            (date_dir / f"AI早报-{date}.md").write_text(date, encoding="utf-8")

        payload = self.client.get("/api/state?date=2026-08-31").get_json()

        self.assertEqual(payload["dates"], ["2026-08-31", "2026-08-30", "2026-08-29"])
        self.assertEqual(payload["date"], "2026-08-31")

    def test_state_hides_legacy_daily_heading(self) -> None:
        date = "2026-09-01"
        date_dir = self.output / date
        date_dir.mkdir(parents=True)
        (date_dir / f"AI早报-{date}.md").write_text(
            f"# AI 早报 {date}\n\n> 生成时间：测试\n\n## 概览\n", encoding="utf-8"
        )

        payload = self.client.get(f"/api/state?date={date}").get_json()

        self.assertNotIn(f"# AI 早报 {date}", payload["content"])
        self.assertTrue(payload["content"].startswith("> 生成时间：测试"))

    def test_state_hides_legacy_audit_checklist_from_editor_and_preview_source(self) -> None:
        date = "2026-09-01"
        date_dir = self.output / date
        date_dir.mkdir(parents=True)
        (date_dir / f"AI早报-{date}.md").write_text(
            "> 生成时间：测试\n\n"
            "## ✅ 审核清单（补充完截图后可删除本节）\n\n"
            "操作说明\n\n"
            "| # | 需要的截图 | 原文 | 保存路径 |\n"
            "|---|---|---|---|\n"
            "| 1 | 测试 | [打开](https://example.com) | `assets/test.jpg` |\n"
            "---\n\n"
            "## 概览\n",
            encoding="utf-8",
        )

        payload = self.client.get(f"/api/state?date={date}").get_json()

        self.assertNotIn("审核清单", payload["content"])
        self.assertNotIn("需要的截图", payload["content"])
        self.assertIn("## 概览", payload["content"])

    def test_final_endpoint_returns_latest_final(self) -> None:
        date = "2026-08-31"
        date_dir = self.output / date
        date_dir.mkdir(parents=True)
        (date_dir / f"AI早报-{date}-终稿.md").write_text("first", encoding="utf-8")
        latest = date_dir / f"AI早报-{date}-终稿-1.md"
        latest.write_text("latest", encoding="utf-8")
        latest.touch()

        response = self.client.get(f"/api/final?date={date}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["content"], "latest")

    def test_app_settings_default_to_twelve_and_can_update_daily_limit(self) -> None:
        config = self.output / "config.yaml"
        config.write_text("# keep this comment\ntop_n: 12\ntime_window_hours: 26\n", encoding="utf-8")
        with patch.object(webui, "CONFIG_FILE", config):
            initial = self.client.get("/api/settings")
            updated = self.client.put("/api/settings", json={"top_n": 18})

        self.assertEqual(initial.status_code, 200)
        self.assertEqual(initial.get_json()["top_n"], 12)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["top_n"], 18)
        self.assertIn("# keep this comment", config.read_text(encoding="utf-8"))
        self.assertIn("top_n: 18", config.read_text(encoding="utf-8"))

    def test_app_settings_save_multiple_fields_and_reject_bad_llm_url(self) -> None:
        config = self.output / "config.yaml"
        config.write_text("# keep\ntime_window_hours: 26\ntop_n: 12\nscreenshot_count: 5\nmax_text_chars: 2500\nllm:\n  enabled: auto\n  base_url: https://example.com\n  model: test\n  temperature: 0.7\n", encoding="utf-8")
        with patch.object(webui, "CONFIG_FILE", config):
            response = self.client.put("/api/settings", json={"time_window_hours": 48, "screenshot_count": 3, "max_text_chars": 4000, "llm": {"enabled": "auto", "base_url": "https://api.example.com", "model": "model-x", "temperature": 0.4}, "preferences": {"boost_keywords": ["a"], "downrank_keywords": ["b"], "block_keywords": ["c"]}})
            bad = self.client.put("/api/settings", json={"llm": {"base_url": "ftp://bad", "model": "x"}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["time_window_hours"], 48)
        saved = yaml.safe_load(config.read_text(encoding="utf-8"))
        self.assertEqual(saved["preferences"]["block_keywords"], ["c"])
        self.assertTrue(list(self.output.glob("config.yaml.bak-*")))
        self.assertEqual(bad.status_code, 400)

    def test_run_endpoint_starts_background_task(self) -> None:
        fake_thread = unittest.mock.Mock()
        with patch("webui.threading.Thread", return_value=fake_thread):
            with webui.run_lock:
                webui.run_state["running"] = False
            response = self.client.post("/api/run", json={})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["state"]["running"])
        fake_thread.start.assert_called_once_with()
        with webui.run_lock:
            webui.run_state["running"] = False

    def test_run_state_reads_persisted_summary_after_restart(self) -> None:
        summary_file = self.output / "last-run.json"
        summary_file.write_text('{"fetched": 20, "kept": 5}', encoding="utf-8")
        with patch.object(webui, "RUN_SUMMARY_FILE", summary_file):
            with webui.run_lock:
                webui.run_state["summary"] = None
            payload = self.client.get("/api/run-state").get_json()
        self.assertEqual(payload["summary"]["kept"], 5)

    def test_export_check_reports_missing_content(self) -> None:
        date = "2026-08-31"
        date_dir = self.output / date
        date_dir.mkdir(parents=True)
        (date_dir / f"AI早报-{date}.md").write_text("## 概览\n\n## 条目 #1\n\n<!-- 截图占位 -->\n", encoding="utf-8")
        response = self.client.post("/api/export-check", json={"date": date, "picks": [1]})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["warnings"])

    def test_carryover_api_adds_yesterday_unexported_article(self) -> None:
        yesterday, today = "2026-09-09", "2026-09-10"
        today_dir = self.output / today
        today_dir.mkdir(parents=True)
        (today_dir / f"AI早报-{today}.md").write_text(
            "## 概览\n\n### 要闻\n\n- 今日文章 `#1`\n\n## 今日文章 `#1`\n\n今日正文\n\n```text\nhttps://example.com/today\n```\n",
            encoding="utf-8",
        )
        snapshot_filtered_items(yesterday, [{
            "title": "昨日剩余", "url": "https://example.com/yesterday",
            "category": "news", "summary": "昨日摘要",
        }], webui.ARTICLE_ARCHIVE)

        available = self.client.get(f"/api/carryover?date={today}").get_json()
        response = self.client.post("/api/carryover", json={
            "date": today,
            "source_date": yesterday,
            "keys": [available["items"][0]["key"]],
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["added"], 1)
        self.assertIn("昨日剩余", response.get_json()["content"])
        self.assertEqual(response.get_json()["items"][1]["title"], "昨日剩余")
        self.assertEqual(self.client.get(f"/api/carryover?date={today}").get_json()["items"], [])

    def test_placeholder_is_exposed_as_empty_item_image_slot(self) -> None:
        text = """## 概览

### 要闻

- 测试资讯 `#1`

## 测试资讯 `#1`

正文

<!-- 📷 截图占位 | 测试资讯
     操作说明 -->
![待补充截图](assets/2026-08-31/01-test.jpg)
"""

        item = webui.items_from_text(text, "2026-08-31")[0]

        self.assertTrue(item["needs_image"])
        self.assertFalse(item["has_img"])
        self.assertIsNone(item["image_path"])

    def test_pasting_item_image_adds_slot_when_article_has_no_placeholder(self) -> None:
        text = """## 概览

### 要闻

- 测试资讯 `#1`

## 测试资讯 `#1`

正文
"""

        updated = webui.attach_item_image(
            text, 1, "assets/2026-09-08/item-01-test.png"
        )

        self.assertIn(webui.IMAGE_SLOT, updated)
        self.assertIn("![截图](assets/2026-09-08/item-01-test.png)", updated)

    def test_pasting_item_image_replaces_placeholder_and_saves_draft(self) -> None:
        date = "2026-08-31"
        date_dir = self.output / date
        date_dir.mkdir(parents=True)
        draft = date_dir / f"AI早报-{date}.md"
        draft.write_text("""## 概览

### 要闻

- 测试资讯 `#1`

## 测试资讯 `#1`

正文

<!-- 📷 截图占位 | 测试资讯
     操作说明 -->
![待补充截图](assets/2026-08-31/01-test.jpg)

```text
https://example.com
```
""", encoding="utf-8")
        png = base64.b64encode(
            base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
        ).decode("ascii")

        response = self.client.post("/api/item-image", json={
            "date": date, "no": 1, "data": f"data:image/png;base64,{png}",
        })

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn(webui.IMAGE_SLOT, payload["content"])
        self.assertNotIn("截图占位", payload["content"])
        self.assertIn("![截图](assets/", payload["content"])
        self.assertTrue(payload["items"][0]["has_img"])
        self.assertTrue((date_dir / payload["path"]).is_file())

    def test_export_creates_pdf_with_embedded_image(self) -> None:
        date = "2026-08-31"
        date_dir = self.output / date
        asset_dir = date_dir / "assets" / date
        asset_dir.mkdir(parents=True)
        image = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        (asset_dir / "item-01-test.png").write_bytes(image)
        (date_dir / f"AI早报-{date}.md").write_text("""## 概览

### 要闻

- 测试资讯 `#1`

## 测试资讯 `#1`

正文

<!-- 📷 图片区域 -->
![截图](assets/2026-08-31/item-01-test.png)
""", encoding="utf-8")

        response = self.client.post("/api/export", json={
            "date": date, "picks": [1], "title": "重点资讯 | AI日报0831",
        })

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        pdf = self.output / payload["pdf_path"]
        markdown = self.output / payload["path"]
        self.assertTrue(markdown.read_text(encoding="utf-8").startswith("# 重点资讯 | AI日报0831\n"))
        self.assertNotIn("## 🔗 信息源", markdown.read_text(encoding="utf-8"))
        self.assertEqual(payload["title"], "重点资讯 | AI日报0831")
        self.assertFalse(payload["includes_sources"])
        self.assertTrue(pdf.is_file())
        self.assertTrue(pdf.read_bytes().startswith(b"%PDF"))
        self.assertIn(b"/Subtype /Image", pdf.read_bytes())

    def test_export_keeps_cover_as_resource_without_adding_it_to_document(self) -> None:
        date = "2026-08-31"
        date_dir = self.output / date
        asset_dir = date_dir / "assets" / date
        asset_dir.mkdir(parents=True)
        image = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        (asset_dir / "item-01-cover.png").write_bytes(image)
        (date_dir / f"AI早报-{date}.md").write_text("""## 概览

### 要闻

- 第一篇 `#1`

## 第一篇 `#1`

正文
![截图](assets/2026-08-31/item-01-cover.png)
""", encoding="utf-8")

        response = self.client.post("/api/export", json={"date": date, "picks": [1]})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["cover_path"], "assets/2026-08-31/item-01-cover.png")
        markdown = (self.output / payload["path"]).read_text(encoding="utf-8")
        self.assertNotIn("📕 导出封面", markdown)
        self.assertNotIn("![封面]", markdown)

    def test_export_cover_upload_is_saved(self) -> None:
        date = "2026-08-31"
        date_dir = self.output / date
        date_dir.mkdir(parents=True)
        (date_dir / f"AI早报-{date}.md").write_text(
            "## 概览\n\n### 要闻\n\n- 无图资讯 `#1`\n\n"
            "## 无图资讯 `#1`\n\n正文\n",
            encoding="utf-8",
        )
        png = base64.b64encode(
            base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
        ).decode("ascii")

        response = self.client.post("/api/export-cover", json={
            "date": date, "data": f"data:image/png;base64,{png}",
        })

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue((self.output / date / payload["path"]).is_file())
        self.assertTrue(payload["path"].startswith(f"assets/{date}/cover-"))

        exported = self.client.post("/api/export", json={
            "date": date, "picks": [1], "cover_path": payload["path"],
        }).get_json()
        markdown = (self.output / exported["path"]).read_text(encoding="utf-8")
        pdf = (self.output / exported["pdf_path"]).read_bytes()
        self.assertNotIn(payload["path"], markdown)
        self.assertNotIn(b"/Subtype /Image", pdf)


if __name__ == "__main__":
    unittest.main()
