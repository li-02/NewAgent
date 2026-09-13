"""AI 每日资讯生成器：抓取 → 去重 → 排序 → 正文提取 → 成稿（含截图占位符）

用法：
    python main.py                 # 正式运行（有 LLM_API_KEY 则成稿，否则列表版）
    python main.py --no-llm        # 强制列表版
    python main.py --hours 48      # 临时放宽时间窗口
    python main.py --demo          # 用内置示例数据预览成稿格式
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src.db import DB
from src.article_archive import backup_filtered_draft, snapshot_filtered_items
from src.fetchers import run_source
from src.pipeline.dedup import dedup, url_hash
from src.pipeline.extract import fetch_text
from src.pipeline.generate import (
    assign_screenshot_paths,
    generate_digest,
    merge_changelog_updates,
    resolve_llm,
)
from src.pipeline.rank import rank
from src.pipeline.observe import observe, event_time
from src.outputs.markdown import render_digest, write_digest

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def fetch_all(sources: list[dict], limit: int) -> list[dict]:
    items: list[dict] = []
    for src in sources:
        try:
            rows = run_source(src, limit)
            print(f"  [ok]   {src['name']:<24} {len(rows)} 条")
            items.extend(rows)
        except Exception as e:
            print(f"  [fail] {src['name']:<24} {type(e).__name__}: {e}")
    return items


DEMO_ITEMS = [
    {
        "title": "OpenAI 发布新一代推理模型 o5：编程与数学能力大幅提升",
        "url": "https://openai.com/news/o5-release/",
        "source": "OpenAI News",
        "category": "news",
        "weight": 3,
        "summary": "OpenAI 今日发布 o5 系列，官方称其在 SWE-bench 与 AIME 上刷新纪录，API 同步开放，定价与上代持平。",
        "published": datetime.now(timezone.utc) - timedelta(hours=3),
        "sources": [
            ("OpenAI News", "https://openai.com/news/o5-release/"),
            ("VentureBeat AI", "https://venturebeat.com/ai/openai-o5-reasoning-model/"),
        ],
    },
    {
        "title": "Hugging Face 开源 SmolLM3：面向端侧的 3B 参数小模型",
        "url": "https://huggingface.co/blog/smollm3",
        "source": "Hugging Face Blog",
        "category": "news",
        "weight": 2,
        "summary": "SmolLM3 采用全新蒸馏流程，官方称可在手机端流畅运行，权重与训练配方全部开放。",
        "published": datetime.now(timezone.utc) - timedelta(hours=7),
        "sources": [("Hugging Face Blog", "https://huggingface.co/blog/smollm3")],
    },
    {
        "title": "Google DeepMind：AlphaProof2 达到国际数学奥赛金牌水平",
        "url": "https://deepmind.google/blog/alphaproof2/",
        "source": "Google DeepMind Blog",
        "category": "news",
        "weight": 3,
        "summary": "DeepMind 公布 AlphaProof2 在本年度 IMO 六道题中解出五道，论文与评测细节同步公开。",
        "published": datetime.now(timezone.utc) - timedelta(hours=11),
        "sources": [("Google DeepMind Blog", "https://deepmind.google/blog/alphaproof2/")],
    },
    {
        "title": "NVIDIA 宣布 Blackwell Ultra 平台全面出货",
        "url": "https://blogs.nvidia.com/blog/blackwell-ultra-ga/",
        "source": "NVIDIA Blog",
        "category": "news",
        "weight": 2,
        "summary": "NVIDIA 称 Blackwell Ultra 已向主要云厂商交付，官方博客列出了首批客户与性能数据。",
        "published": datetime.now(timezone.utc) - timedelta(hours=15),
        "sources": [("NVIDIA Blog", "https://blogs.nvidia.com/blog/blackwell-ultra-ga/")],
    },
    {
        "title": "Efficient Long-Context Attention via Hierarchical KV Cache",
        "url": "https://arxiv.org/abs/2608.12345",
        "source": "arXiv cs.AI",
        "category": "paper",
        "weight": 1,
        "summary": "提出分层 KV 缓存结构，官方称在 1M 上下文任务上推理显存降低 60%。",
        "published": datetime.now(timezone.utc) - timedelta(hours=20),
        "sources": [("arXiv cs.AI", "https://arxiv.org/abs/2608.12345")],
    },
]


def main() -> int:
    ap = argparse.ArgumentParser(description="AI 每日资讯生成器")
    ap.add_argument("--hours", type=int, default=None, help="时间窗口（小时），默认读配置")
    ap.add_argument("--top", type=int, default=None, help="最终草稿条数上限，默认读配置")
    ap.add_argument("--limit", type=int, default=30, help="每个源最多抓取条数")
    ap.add_argument("--no-llm", action="store_true", help="强制使用列表版，不调用 LLM")
    ap.add_argument("--demo", action="store_true", help="用内置示例数据预览成稿格式")
    args = ap.parse_args()

    cfg = load_yaml(ROOT / "config" / "config.yaml")
    configured_sources = load_yaml(ROOT / "config" / "sources.yaml")["sources"]
    sources = [src for src in configured_sources if src.get("enabled", True) is not False]
    window = args.hours or int(cfg.get("time_window_hours", 26))
    top_n = args.top or int(cfg.get("top_n", 12))
    date_str = datetime.now().strftime("%Y-%m-%d")

    if args.demo:
        print("[demo] 使用内置示例数据生成预览稿")
        items = rank(DEMO_ITEMS, cfg.get("preferences"))
        snapshot_filtered_items(date_str, items, ROOT / "data" / "article-archive")
        items = items[:top_n]
        assign_screenshot_paths(items, date_str, int(cfg.get("screenshot_count", 5)))
        llm = resolve_llm(cfg.get("llm", {}), disabled=args.no_llm)
        body = generate_digest(items, date_str, llm)
        md = render_digest(items, date_str, body, {"fetched": 6, "kept": 5, "source_count": 5})
        path = write_digest(md, ROOT / cfg["output"]["dir"], cfg["output"]["filename"], date_str)
        backup_filtered_draft(path, date_str, ROOT / "data" / "article-archive")
        print(f"[demo] 已生成：{path}")
        return 0

    disabled_count = len(configured_sources) - len(sources)
    disabled_note = f"，已停用 {disabled_count} 个" if disabled_count else ""
    print(f"[1/6] 抓取 {len(sources)} 个源（时间窗口 {window} 小时{disabled_note}）")
    if not sources:
        print("没有已启用的信息源，请在 WebUI 的“信息源设置”中启用或新增来源")
        return 1
    fetched = fetch_all(sources, args.limit)
    if not fetched:
        print("所有源均抓取失败或无内容，请检查网络后重试")
        return 1

    print("[2/6] 时间过滤 + 去重")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window)
    db = DB(ROOT / cfg["db_path"])
    fetched_count = len(fetched)
    fetched = observe(fetched, db)
    if len(fetched) < fetched_count:
        print(f"       {fetched_count - len(fetched)} 个无日期页面已建立基线，暂无新变更")
    # 有证据的首次观察时间单独标注；普通无日期条目仍排除。
    windowed = [
        it
        for it in fetched
        if event_time(it) is not None and cutoff <= event_time(it) <= datetime.now(timezone.utc)
    ]
    candidates = windowed
    known = db.known_hashes([url_hash(it["url"]) for it in candidates])
    items = dedup(candidates, known)
    if not items and candidates:
        # 去重只用于避免重复入库，不能阻止用户手动生成当天快照。
        items = dedup(candidates, set())
        print("       本次条目均已收录，仍生成当天快照（不覆盖历史文件）")
    print(f"       抓到 {fetched_count} 条 → 窗口内 {len(windowed)} 条 → 本稿候选 {len(items)} 条")
    merged = merge_changelog_updates(items)
    if len(merged) != len(items):
        print(f"       同工具多版本合并：{len(items)} → {len(merged)} 条")
    items = merged
    if not items:
        print(f"最近 {window} 小时内没有可生成的新内容，未生成稿件")
        db.close()
        return 0

    print("[3/6] 关键词排序")
    items = rank(items, cfg.get("preferences"))
    blocked = [it for it in items if it.get("ranking_matches", {}).get("blocked")]
    if blocked:
        items = [it for it in items if not it.get("ranking_matches", {}).get("blocked")]
        print(f"       偏好屏蔽 {len(blocked)} 条")
    snapshot_filtered_items(date_str, items, ROOT / "data" / "article-archive")
    items = items[:top_n]
    print(f"       最终入选 {len(items)} 条")

    print("[4/6] 提取正文（Top 条目，反爬站点自动退回摘要）")
    for it in items:
        if it.get("no_extract"):
            continue
        it["text"] = fetch_text(
            it["url"],
            max_chars=int(cfg.get("max_text_chars", 2500)),
            title=it.get("title", ""),
        )

    print("[5/6] 生成资讯稿")
    llm = resolve_llm(cfg.get("llm", {}), disabled=args.no_llm)
    print(f"       LLM：{('启用（' + llm['model'] + '）') if llm else '未检测到 API key，输出列表版'}")
    assign_screenshot_paths(items, date_str, int(cfg.get("screenshot_count", 5)))
    body = generate_digest(items, date_str, llm)
    stats = {
        "fetched": fetched_count,
        "kept": len(items),
        "source_count": len({it["source"] for it in fetched}),
    }
    md = render_digest(items, date_str, body, stats)

    print("[6/6] 写入文件 + 更新去重库")
    path = write_digest(md, ROOT / cfg["output"]["dir"], cfg["output"]["filename"], date_str)
    backup_filtered_draft(path, date_str, ROOT / "data" / "article-archive")
    now = datetime.now().isoformat(timespec="seconds")
    for it in candidates:
        db.add_seen(url_hash(it["url"]), it["url"], it["title"], now)
    db.commit()
    db.close()

    shots = [it for it in items if it.get("screenshot_path")]
    print(f"\n完成：{path}")
    if shots:
        print(f"截图提示：{len(shots)} 条可在控制中心的「资讯截图存放区」补充截图。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
