"""跨天标题判重：拦截「同一事件、不同媒体、不同 URL」的重复报道。"""
import unittest

from src.db import DB
from src.pipeline.dedup import dedup, is_recent_story, is_same_story


def item(title: str, url: str, source: str = "Test") -> dict:
    return {"title": title, "url": url, "source": source}


class IsRecentStoryTests(unittest.TestCase):
    def test_same_event_from_different_outlets_is_caught(self):
        # 09-25 与 09-26 实际发生的撞题：同一事件、不同媒体、不同 URL
        old = "调查称 OpenAI 智能体借短链藏匿攻击载荷并调用外部模型"
        new = "研究人员发现 OpenAI 智能体利用短链接藏匿攻击载荷"
        self.assertTrue(is_recent_story(new, [old]))

    def test_same_company_different_event_is_not_merged(self):
        # 同公司不同事件不能被误合并，否则会漏掉真正的新闻
        old = "OpenAI 推出 GPT-6 Sol 与 GPT-6 Luna 模型"
        new = "OpenAI 与阿拉巴马州就青少年安全达成和解"
        self.assertFalse(is_recent_story(new, [old]))

    def test_empty_recent_list_never_matches(self):
        self.assertFalse(is_recent_story("任意新闻标题", []))

    def test_daily_series_with_different_dates_is_not_merged(self):
        """回归：每日固定发布的系列内容（APOD 每日一图）只有日期不同，不能判重。

        曾因 is_same_story 的「共享关键实体」兜底规则误判：两个 APOD 标题共享
        apod/september/2026 三个词且重叠过半，就被当成同一事件，整条被判掉。
        """
        today = "APOD: 2026 September 27 – Andromeda Before and After Photoshop"
        older = "APOD: 2026 September 20 – Analemma over the Callanish Stones"
        self.assertFalse(is_recent_story(today, [older]))

    def test_entity_fallback_still_works_for_same_day_merge(self):
        """同日合并仍保留实体兜底能力（跨天关闭，同日不受影响）。"""
        a = "Sony Music, Warner sue Anthropic over copyright"
        b = "Sony Music and Warner Chappell are suing Anthropic"
        self.assertTrue(is_same_story(a, b, 0.75, entity_fallback=True))


class CrossDayDedupTests(unittest.TestCase):
    def test_recent_title_causes_item_to_be_dropped(self):
        items = [item("调查称 OpenAI 智能体借短链藏匿攻击载荷并调用外部模型", "https://a.com/1")]
        recent = ["研究人员发现 OpenAI 智能体利用短链接藏匿攻击载荷"]
        self.assertEqual(dedup(items, set(), recent), [])

    def test_none_recent_titles_disables_cross_day_check(self):
        items = [item("某条新闻标题内容", "https://a.com/1")]
        self.assertEqual(len(dedup(items, set(), None)), 1)
        self.assertEqual(len(dedup(items, set())), 1)

    def test_same_day_merge_still_works_with_recent_titles(self):
        items = [
            item("OpenAI 发布新推理模型", "https://a.com/1", "A"),
            item("OpenAI 发布新推理模型", "https://b.com/2", "B"),
        ]
        merged = dedup(items, set(), ["完全不相关的旧闻标题"])
        self.assertEqual(len(merged), 1)
        self.assertEqual(len(merged[0]["sources"]), 2)


class RecentTitlesQueryTests(unittest.TestCase):
    def test_recent_titles_filters_by_first_seen(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            db = DB(Path(tmp) / "t.db")
            db.add_seen("h1", "https://a.com/1", "旧闻一", "2026-09-20T10:00:00")
            db.add_seen("h2", "https://a.com/2", "新近新闻", "2026-09-26T10:00:00")
            db.commit()
            titles = db.recent_titles("2026-09-25T00:00:00")
            db.close()
        self.assertEqual(titles, ["新近新闻"])

    def test_until_excludes_today_so_reruns_do_not_self_dedup(self):
        """同一天重跑时，本次运行刚写入的条目不能把自身判为重复。"""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            db = DB(Path(tmp) / "t.db")
            db.add_seen("h1", "https://a.com/1", "昨天的事件", "2026-09-26T20:00:00")
            db.add_seen("h2", "https://a.com/2", "今天已写入的事件", "2026-09-27T16:41:00")
            db.commit()
            # 上界取今天 00:00 → 今天写入的条目应被排除
            titles = db.recent_titles("2026-09-20T00:00:00", "2026-09-27T00:00:00")
            db.close()
        self.assertEqual(titles, ["昨天的事件"])

    def test_rerun_scenario_keeps_todays_items(self):
        """回归：跨天判重 + 排除今天之后，今天的条目不会被自身判掉。"""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            db = DB(Path(tmp) / "t.db")
            # 模拟上半场运行把今天的候选写进 seen
            db.add_seen("h1", "https://a.com/1", "OpenAI 暂停最强模型训练", "2026-09-27T16:41:00")
            db.commit()
            recent = db.recent_titles("2026-09-20T00:00:00", "2026-09-27T00:00:00")
            db.close()
        items = [item("OpenAI 暂停最强模型训练", "https://a.com/1")]
        # 排除今天后 recent 为空，条目应保留
        self.assertEqual(len(dedup(items, set(), recent)), 1)


if __name__ == "__main__":
    unittest.main()
