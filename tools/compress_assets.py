"""把历史 output/ 目录里的截图压成 JPEG，并把稿件里的图片引用同步改成 .jpg。

为什么必须改后缀：压出来的数据是 JPEG，如果仍挂在 .png 后缀下，严格按后缀
校验的工具会直接拒绝（本项目的图片读取器就报了
「the .png extension declares image/png, but the bytes use a different image format」）。
公众号/头条的图片上传同样会按后缀判定格式。所以必须真正改名，并同步更新
草稿与终稿里已经写死的相对路径，否则稿件会指向不存在的图片。

用法：
    python tools/compress_assets.py --dry-run     # 只报告，不动文件
    python tools/compress_assets.py               # 执行：压图 + 改名 + 改引用
    python tools/compress_assets.py --min-kb 200  # 只处理大于 200KB 的图
    python tools/compress_assets.py --purge-orig  # 确认无恙后删除 .orig 原图备份
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.image_ops import compress_to_jpeg  # noqa: E402

IMAGE_EXTS = {".png", ".webp", ".gif"}
MD_EXTS = {".md"}


def iter_images(root: Path):
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTS and not path.name.endswith(".orig"):
            yield path


def iter_markdown(root: Path):
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in MD_EXTS:
            yield path


def rewrite_references(root: Path, renames: dict[str, str], dry_run: bool) -> int:
    """把稿件里对 <旧相对路径> 的引用替换成 <新相对路径>。

    只替换出现在 Markdown 图片/链接语法中的路径，避免误伤正文里碰巧相同的字符串。
    """
    out_root = root.parent  # 稿件位于 output/<日期>/ 与 output/ 之下，按 output/ 为基
    touched = 0
    for md in iter_markdown(out_root):
        text = md.read_text(encoding="utf-8")
        original = text
        for old_rel, new_rel in renames.items():
            if old_rel not in text:
                continue
            # 同时命中 output/ 相对路径与稿件同级的相对路径两种写法
            text = text.replace(f"({old_rel})", f"({new_rel})")
            text = text.replace(f"]({old_rel})", f"]({new_rel})")
        if text != original:
            touched += 1
            print(f"  引用更新：{md.relative_to(out_root)}")
            if not dry_run:
                md.write_text(text, encoding="utf-8")
    return touched


def main() -> int:
    ap = argparse.ArgumentParser(description="压缩 output/ 下的历史截图并同步改名")
    ap.add_argument("--root", default=str(ROOT / "output"), help="素材根目录")
    ap.add_argument("--dry-run", action="store_true", help="只报告，不修改文件")
    ap.add_argument("--min-kb", type=float, default=150.0, help="只处理大于该体积的图（KB）")
    ap.add_argument("--purge-orig", action="store_true", help="删除 .orig 原图备份后退出")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        print(f"目录不存在：{root}")
        return 1

    if args.purge_orig:
        backups = [p for p in root.rglob("*.orig") if p.is_file()]
        freed = sum(p.stat().st_size for p in backups)
        for p in backups:
            p.unlink()
        print(f"已删除 {len(backups)} 个 .orig 备份，释放 {freed / 1048576:.2f} MB")
        return 0

    total_before = total_after = 0
    renames: dict[str, str] = {}
    changed = skipped = 0
    for path in iter_images(root):
        before = path.stat().st_size
        if before < args.min_kb * 1024:
            skipped += 1
            continue
        payload, compressed = compress_to_jpeg(path.read_bytes())
        if not compressed:
            skipped += 1
            continue
        target = path.with_suffix(".jpg")
        old_rel = path.relative_to(root).as_posix()
        new_rel = target.relative_to(root).as_posix()
        renames[old_rel] = new_rel
        total_before += before
        total_after += len(payload)
        changed += 1
        print(f"  {old_rel}  {before / 1024:8.1f} KB → {len(payload) / 1024:7.1f} KB → {target.name}")
        if args.dry_run:
            continue
        backup = path.with_name(path.name + ".orig")
        if not backup.exists():
            backup.write_bytes(path.read_bytes())
        target.write_bytes(payload)
        path.unlink()

    print(f"\n共处理 {changed} 张，跳过 {skipped} 张（小于 {args.min_kb} KB 或无法压缩）")
    if changed:
        saved = total_before - total_after
        print(
            f"体积：{total_before / 1048576:.2f} MB → {total_after / 1048576:.2f} MB"
            f"（省 {saved / 1048576:.2f} MB，{saved / max(total_before, 1) * 100:.0f}%）"
        )
    if args.dry_run:
        print("（--dry-run：未修改任何文件）")
        return 0

    print("\n同步稿件中的图片引用：")
    touched = rewrite_references(root, renames, dry_run=False)
    print(f"  共更新 {touched} 个稿件文件")
    remaining = sum(1 for p in root.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTS and not p.name.endswith(".orig"))
    print(f"\n仍有 {remaining} 张非 JPEG 图（多为小图），原图备份为 .orig")
    print("确认无恙后可运行：python tools/compress_assets.py --purge-orig")
    return 0


if __name__ == "__main__":
    sys.exit(main())
