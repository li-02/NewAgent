import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import main


class StrictTimeWindowTests(unittest.TestCase):
    def test_empty_window_does_not_fall_back_to_old_items(self) -> None:
        now = datetime.now(timezone.utc)
        old_item = {
            "title": "旧闻",
            "url": "https://example.com/old",
            "source": "测试源",
            "published": now - timedelta(days=2),
        }
        undated_item = {
            "title": "无日期内容",
            "url": "https://example.com/undated",
            "source": "测试源",
            "published": None,
        }

        config = {
            "time_window_hours": 26,
            "top_n": 12,
            "db_path": "data/test-time-window.db",
            "output": {"dir": "output", "filename": "AI早报-{date}.md"},
        }
        sources = {"sources": [{"name": "测试源"}]}

        with (
            patch.object(main, "load_yaml", side_effect=[config, sources]),
            patch.object(main, "fetch_all", return_value=[old_item, undated_item]),
            patch.object(main, "DB") as db_cls,
            patch.object(main, "write_digest") as write_digest,
            patch("sys.argv", ["main.py"]),
        ):
            result = main.main()

        self.assertEqual(result, 0)
        write_digest.assert_not_called()
        db_cls.return_value.known_hashes.assert_called_once_with([])
        db_cls.return_value.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
