from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import base64

import webui


class WebUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)
        self.output_patch = patch.object(webui, "OUTPUT", self.output)
        self.output_patch.start()
        webui.app.config.update(TESTING=True)
        self.client = webui.app.test_client()

    def tearDown(self) -> None:
        self.output_patch.stop()
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

    def test_index_includes_image_shelf_count_marker(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("image-shelf-count", response.get_data(as_text=True))

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


if __name__ == "__main__":
    unittest.main()
