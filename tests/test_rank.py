import unittest

from src.pipeline.rank import rank


class RankPreferenceTests(unittest.TestCase):
    def test_blocked_items_do_not_consume_top_n_after_filter(self):
        items = [
            {"title": "屏蔽消息", "summary": "noise", "weight": 1},
            {"title": "保留消息", "summary": "useful", "weight": 1},
        ]
        ranked = rank(items, {"block_keywords": ["屏蔽"]})
        visible = [it for it in ranked if not it["ranking_matches"]["blocked"]][:1]
        self.assertEqual([it["title"] for it in visible], ["保留消息"])


if __name__ == "__main__":
    unittest.main()
