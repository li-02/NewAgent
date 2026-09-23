import unittest

from src.pipeline.rank import rank, select_balanced


class RankPreferenceTests(unittest.TestCase):
    def test_technology_topics_are_ranked_above_unrelated_items(self):
        items = [
            {"title": "城市周末餐厅推荐", "summary": "美食与旅行", "weight": 1},
            {"title": "新一代半导体芯片采用先进制程", "summary": "GPU 硬件正式发布", "weight": 1},
        ]

        ranked = rank(items)

        self.assertEqual(ranked[0]["title"], "新一代半导体芯片采用先进制程")

    def test_balanced_selection_reserves_space_for_available_sections(self):
        items = [
            {"title": "AI 1", "category": "ai", "score": 10},
            {"title": "AI 2", "category": "ai", "score": 9},
            {"title": "芯片", "category": "chips", "score": 8},
            {"title": "机器人", "category": "frontier", "score": 7},
        ]

        selected = select_balanced(items, 3)

        self.assertEqual([item["title"] for item in selected], ["AI 1", "芯片", "机器人"])

    def test_blocked_items_do_not_consume_top_n_after_filter(self):
        items = [
            {"title": "屏蔽消息", "summary": "noise", "weight": 1},
            {"title": "保留消息", "summary": "useful", "weight": 1},
        ]
        ranked = rank(items, {"block_keywords": ["屏蔽"]})
        visible = [it for it in ranked if not it["ranking_matches"]["blocked"]][:1]
        self.assertEqual([it["title"] for it in visible], ["保留消息"])

    def test_priority_keywords_outrank_ordinary_high_score_items(self):
        items = [
            {"title": "芯片发布", "summary": "GPU 芯片正式发布", "weight": 3},
            {"title": "OpenAI 发布 GPT-6 Sol 与 Luna", "summary": "新模型上线", "weight": 1},
        ]

        ranked = rank(items, {"priority_keywords": ["openai", "gpt-6"]})

        self.assertEqual(ranked[0]["title"], "OpenAI 发布 GPT-6 Sol 与 Luna")
        self.assertEqual(ranked[0]["ranking_matches"]["priority"], ["openai", "gpt-6"])

    def test_priority_items_are_selected_before_category_representatives(self):
        items = [
            {"title": "普通硬件新闻", "category": "chips", "score": 20},
            {"title": "OpenAI 发布模型", "category": "ai", "score": 10,
             "ranking_matches": {"priority": ["openai"]}},
        ]

        selected = select_balanced(items, 1)

        self.assertEqual(selected[0]["title"], "OpenAI 发布模型")


if __name__ == "__main__":
    unittest.main()
