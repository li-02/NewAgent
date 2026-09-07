"""AI 早报 · 本地 Web 控制中心

功能：手动采集/成稿、编辑草稿（实时预览）、截图 Ctrl+V 粘贴入库、
勾选条目、一键导出终稿、复制发布版富文本。

启动：
    python webui.py                # 启动并自动打开浏览器（http://127.0.0.1:8765）
    python webui.py --no-browser   # 只启动服务
"""
from __future__ import annotations

import argparse
import base64
import binascii
import os
import random
import re
import subprocess
import sys
import threading
import webbrowser
from collections import deque
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
import yaml

from finalize import (
    IMAGE_SLOT,
    ITEM_HEAD,
    PLACEHOLDER_START,
    build_final,
    build_single,
    insert_placeholder,
    next_path,
    parse_draft_text,
    strip_placeholder,
)
from pdf_export import markdown_to_pdf
from src.fetchers import run_source
from src.source_config import (
    SourceConfigError,
    load_source_config,
    normalize_source,
    save_source_config,
)

ROOT = Path(__file__).parent
OUTPUT = ROOT / "output"
SOURCES_FILE = ROOT / "config" / "sources.yaml"
DRAFT_RE = re.compile(r"^AI早报-(\d{4}-\d{2}-\d{2})\.md$")
DRAFT_FILE_RE = re.compile(r"^AI早报-(\d{4}-\d{2}-\d{2})(?:-\d+)?\.md$")
FINAL_FILE_RE = re.compile(r"^AI早报-(\d{4}-\d{2}-\d{2})-终稿(?:-\d+)?\.md$")
RUN_LOG_LIMIT = 300
MAX_IMAGE_BYTES = 15 * 1024 * 1024
DAILY_HEADING_RE = re.compile(r"^# AI 早报 \d{4}-\d{2}-\d{2}\s*\n+", re.M)
AUDIT_CHECKLIST_RE = re.compile(
    r"^## ✅ 审核清单[^\n]*\n.*?(?=^---\s*$)",
    re.M | re.S,
)

app = Flask(__name__, static_folder=str(ROOT / "static"), static_url_path="/static")
run_lock = threading.Lock()
run_state = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "returncode": None,
    "error": "",
    "logs": deque(maxlen=RUN_LOG_LIMIT),
}


def draft_path(date: str) -> Path:
    candidates = []
    date_dir = OUTPUT / date
    if date_dir.exists():
        candidates.extend(
            p for p in date_dir.iterdir()
            if p.is_file() and DRAFT_FILE_RE.match(p.name)
        )
    legacy = OUTPUT / f"AI早报-{date}.md"
    if legacy.exists():
        candidates.append(legacy)
    if candidates:
        return max(candidates, key=lambda p: p.stat().st_mtime)
    return date_dir / f"AI早报-{date}.md"


def final_path(date: str) -> Path:
    return OUTPUT / date / f"AI早报-{date}-终稿.md"


def latest_final_path(date: str) -> Path:
    date_dir = OUTPUT / date
    if not date_dir.exists():
        return final_path(date)
    candidates = [
        p for p in date_dir.iterdir()
        if p.is_file() and FINAL_FILE_RE.match(p.name)
    ]
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else final_path(date)


def output_rel(path: Path) -> str:
    return path.relative_to(OUTPUT).as_posix()


def available_dates() -> list[str]:
    if not OUTPUT.exists():
        return []
    dates = [
        m.group(1)
        for d in OUTPUT.iterdir() if d.is_dir()
        for p in d.iterdir() if p.is_file() and (m := DRAFT_FILE_RE.match(p.name))
    ]
    dates += [m.group(1) for p in OUTPUT.iterdir() if p.is_file() and (m := DRAFT_RE.match(p.name))]
    return sorted(set(dates), reverse=True)


def without_daily_heading(text: str) -> str:
    """Hide retired generated header content in drafts made by older versions."""
    text = DAILY_HEADING_RE.sub("", text, count=1)
    return AUDIT_CHECKLIST_RE.sub("", text, count=1)


def _markdown_image_path(line: str) -> str | None:
    match = re.match(r"!\[[^\]]*\]\(([^)]+)\)", line.lstrip())
    return match.group(1).strip() if match else None


def _item_image_state(block: list[str], date: str | None = None) -> tuple[bool, bool, str | None]:
    """Return (has screenshot slot, has actual image, previewable path)."""
    has_slot = any(ln.startswith(PLACEHOLDER_START) or ln.strip() == IMAGE_SLOT for ln in block)
    in_placeholder = False
    for line in block:
        if line.lstrip().startswith("![["):
            return has_slot, True, None
        if line.startswith(PLACEHOLDER_START):
            in_placeholder = True
            continue
        path = _markdown_image_path(line)
        if not path:
            continue
        if in_placeholder:
            in_placeholder = False
            if date and not re.match(r"^(?:https?:|data:|/|#)", path, re.I):
                if (OUTPUT / date / path.replace("/", os.sep)).is_file():
                    return has_slot, True, path
            continue
        return has_slot, True, path
    return has_slot, False, None


def items_from_text(text: str, date: str | None = None) -> list[dict]:
    overview, blocks = parse_draft_text(text)
    items = []
    for no in sorted(blocks):
        info = overview.get(no, {})
        blk = blocks[no]
        needs_image, has_img, image_path = _item_image_state(blk, date)
        items.append({
            "no": no,
            "title": info.get("ov_title") or f"条目{no}",
            "category": info.get("category", "要闻"),
            "has_img": has_img,
            "needs_image": needs_image,
            "image_path": image_path,
        })
    return items


def attach_item_image(text: str, no: int, path: str) -> str:
    """Replace one item's screenshot placeholder/app screenshot with a stable image slot."""
    lines = text.splitlines()
    start = next((
        i for i, line in enumerate(lines)
        if (m := ITEM_HEAD.match(line)) and (
            (m.group(2) and int(m.group(2)) == no)
            or (not m.group(2) and sum(1 for prior in lines[:i] if ITEM_HEAD.match(prior)) == no)
        )
    ), None)
    if start is None:
        raise ValueError(f"编号 #{no} 不在草稿中")
    end = next((i for i in range(start + 1, len(lines)) if ITEM_HEAD.match(lines[i]) or lines[i].startswith("## 🗞️ 今日来源")), len(lines))
    block = strip_placeholder(lines[start:end])
    block = [
        line for line in block
        if not (
            (image_path := _markdown_image_path(line))
            and re.match(r"assets/\d{4}-\d{2}-\d{2}/item-\d+-", image_path)
        )
    ]
    block = insert_placeholder(block, [IMAGE_SLOT, f"![截图]({path})"])
    return "\n".join(lines[:start] + block + lines[end:]).rstrip() + "\n"


def snapshot_run_state() -> dict:
    with run_lock:
        return {
            "running": run_state["running"],
            "started_at": run_state["started_at"],
            "finished_at": run_state["finished_at"],
            "returncode": run_state["returncode"],
            "error": run_state["error"],
            "logs": list(run_state["logs"]),
        }


def append_run_log(line: str) -> None:
    with run_lock:
        run_state["logs"].append(line.rstrip())


def run_main_task() -> None:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.Popen(
            [sys.executable, "-u", str(ROOT / "main.py")],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            append_run_log(line)
        code = proc.wait()
        with run_lock:
            run_state["returncode"] = code
            run_state["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            run_state["running"] = False
    except Exception as exc:
        with run_lock:
            run_state["returncode"] = -1
            run_state["error"] = f"{type(exc).__name__}: {exc}"
            run_state["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            run_state["running"] = False


def _json_error(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


def _jsonable_item(item: dict) -> dict:
    return {
        "title": item.get("title", ""),
        "url": item.get("url", ""),
        "source": item.get("source", ""),
        "category": item.get("category", "news"),
        "summary": item.get("summary", ""),
        "published": item["published"].isoformat() if item.get("published") else None,
    }


@app.get("/")
def index():
    return send_from_directory(str(ROOT / "static"), "index.html")


@app.get("/settings")
def settings_page():
    return send_from_directory(str(ROOT / "static"), "settings.html")


@app.get("/output/<path:name>")
def output_file(name: str):
    """草稿、终稿、截图都从 output/ 直接出（相对路径 assets/... 因此可预览）"""
    return send_from_directory(str(OUTPUT), name)


@app.get("/api/state")
def api_state():
    dates = available_dates()
    date = request.args.get("date") or (dates[0] if dates else datetime.now().strftime("%Y-%m-%d"))
    p = draft_path(date)
    text = without_daily_heading(p.read_text(encoding="utf-8")) if p.exists() else ""
    final = latest_final_path(date)
    return jsonify({
        "dates": dates,
        "date": date,
        "content": text,
        "items": items_from_text(text, date),
        "final_exists": final.exists(),
        "final_name": final.name if final.exists() else None,
        "final_path": output_rel(final) if final.exists() else None,
    })


@app.post("/api/run")
def api_run():
    with run_lock:
        if run_state["running"]:
            return jsonify({"ok": False, "error": "采集/成稿任务正在运行，请等待完成"}), 409
        run_state["running"] = True
        run_state["started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        run_state["finished_at"] = None
        run_state["returncode"] = None
        run_state["error"] = ""
        run_state["logs"].clear()
        run_state["logs"].append("开始运行 main.py ...")
    threading.Thread(target=run_main_task, daemon=True).start()
    return jsonify({"ok": True, "state": snapshot_run_state()})


@app.get("/api/run-state")
def api_run_state():
    state = snapshot_run_state()
    state["ok"] = True
    return jsonify(state)


@app.get("/api/sources")
def api_sources():
    try:
        payload = load_source_config(SOURCES_FILE)
    except (OSError, SourceConfigError, yaml.YAMLError) as exc:
        return _json_error(str(exc), 500)
    payload["ok"] = True
    return jsonify(payload)


@app.put("/api/sources")
def api_save_sources():
    data = request.get_json(force=True)
    try:
        saved = save_source_config(SOURCES_FILE, data.get("sources"))
    except (SourceConfigError, yaml.YAMLError) as exc:
        return _json_error(str(exc), 400)
    except OSError as exc:
        return _json_error(str(exc), 500)
    return jsonify({"ok": True, "sources": saved})


@app.post("/api/sources/test")
def api_test_source():
    data = request.get_json(force=True)
    try:
        limit = min(max(int(data.get("limit", 3)), 1), 3)
        source = normalize_source(data.get("source"), 0)
        rows = run_source(source, limit)
    except (TypeError, ValueError, SourceConfigError) as exc:
        return _json_error(str(exc), 400)
    except Exception as exc:
        return _json_error(f"{type(exc).__name__}: {exc}", 502)
    return jsonify({
        "ok": True,
        "source": source,
        "count": len(rows),
        "items": [_jsonable_item(row) for row in rows[:limit]],
    })


@app.get("/api/final")
def api_final():
    date = request.args.get("date") or datetime.now().strftime("%Y-%m-%d")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        return jsonify({"ok": False, "error": "日期格式不合法"}), 400
    final = latest_final_path(date)
    if not final.exists():
        return jsonify({"ok": False, "error": "该日期还没有终稿"}), 404
    return jsonify({
        "ok": True,
        "date": date,
        "name": final.name,
        "path": output_rel(final),
        "content": final.read_text(encoding="utf-8"),
    })


@app.post("/api/save")
def api_save():
    data = request.get_json(force=True)
    date, text = data.get("date", ""), data.get("content", "")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        return jsonify({"ok": False, "error": "日期格式不合法"}), 400
    p = draft_path(date)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text.replace("\r\n", "\n"), encoding="utf-8")
    return jsonify({"ok": True, "items": items_from_text(text, date)})


@app.post("/api/upload-image")
def api_upload_image():
    """粘贴的截图（dataURL）落盘到 output/assets/{日期}/，返回相对路径"""
    data = request.get_json(force=True)
    date = data.get("date", "")
    m = re.match(r"data:image/(png|jpeg|jpg|webp|gif);base64,(.+)", data.get("data", ""), re.S)
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date) or not m:
        return jsonify({"ok": False, "error": "参数不合法"}), 400
    ext = "jpg" if m.group(1) == "jpeg" else m.group(1)
    asset_dir = OUTPUT / date / "assets" / date
    asset_dir.mkdir(parents=True, exist_ok=True)
    name = f"{datetime.now():%H%M%S}-{random.randint(1000, 9999)}.{ext}"
    (asset_dir / name).write_bytes(base64.b64decode(m.group(2)))
    return jsonify({"ok": True, "path": f"assets/{date}/{name}"})


@app.post("/api/item-image")
def api_item_image():
    """Paste a screenshot into a specific news item's managed image slot."""
    data = request.get_json(force=True)
    date = data.get("date", "")
    no = int(data.get("no", 0))
    match = re.match(r"data:image/(png|jpeg|jpg|webp|gif);base64,(.+)", data.get("data", ""), re.S)
    draft = draft_path(date)
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date) or not match or no <= 0 or not draft.exists():
        return jsonify({"ok": False, "error": "参数不合法或草稿不存在"}), 400
    try:
        image_bytes = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError):
        return jsonify({"ok": False, "error": "截图数据损坏"}), 400
    if not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES:
        return jsonify({"ok": False, "error": "截图为空或超过 15MB"}), 400
    ext = "jpg" if match.group(1) == "jpeg" else match.group(1)
    asset_dir = OUTPUT / date / "assets" / date
    asset_dir.mkdir(parents=True, exist_ok=True)
    name = f"item-{no:02d}-{datetime.now():%H%M%S}-{random.randint(1000, 9999)}.{ext}"
    relative = f"assets/{date}/{name}"
    target = asset_dir / name
    target.write_bytes(image_bytes)
    try:
        old_text = without_daily_heading(draft.read_text(encoding="utf-8"))
        updated = attach_item_image(old_text, no, relative)
    except ValueError as exc:
        target.unlink(missing_ok=True)
        return jsonify({"ok": False, "error": str(exc)}), 400
    draft.write_text(updated, encoding="utf-8")
    return jsonify({
        "ok": True, "path": relative, "content": updated,
        "items": items_from_text(updated, date),
    })


@app.post("/api/export")
def api_export():
    data = request.get_json(force=True)
    date, picks = data.get("date", ""), data.get("picks", [])
    title = data.get("title")
    include_sources = data.get("include_sources") is True
    include_overview = data.get("include_overview") is True
    p = draft_path(date)
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date) or not p.exists():
        return jsonify({"ok": False, "error": "草稿不存在"}), 400
    overview, blocks = parse_draft_text(p.read_text(encoding="utf-8"))
    md, rebuilt = build_final(
        overview, blocks, [int(n) for n in picks], date, OUTPUT / date,
        title, include_sources, include_overview
    )
    if not rebuilt:
        return jsonify({"ok": False, "error": "没有可用的条目（编号不在草稿中）"}), 400

    # 不覆盖历史导出：已存在则追加序号 终稿-1、终稿-2…
    out = next_path(final_path(date))
    out.parent.mkdir(parents=True, exist_ok=True)
    (out.parent / "assets" / date).mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    pdf_out = out.with_suffix(".pdf")
    markdown_to_pdf(md, pdf_out, out.parent)
    return jsonify({
        "ok": True,
        "name": out.name,
        "path": output_rel(out),
        "pdf_name": pdf_out.name,
        "pdf_path": output_rel(pdf_out),
        "title": md.splitlines()[0].removeprefix("# "),
        "includes_sources": include_sources,
        "includes_overview": include_overview,
        "selected": [f"#{r['no']}（原#{r['old_no']}·{r['cat']}）{r['title']}" for r in rebuilt],
    })


@app.post("/api/export-single")
def api_export_single():
    """单条导出：只导出指定编号的一条，轻量结构，同样不覆盖历史"""
    data = request.get_json(force=True)
    date, no = data.get("date", ""), int(data.get("no", 0))
    p = draft_path(date)
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date) or not p.exists():
        return jsonify({"ok": False, "error": "草稿不存在"}), 400
    overview, blocks = parse_draft_text(p.read_text(encoding="utf-8"))
    md, meta = build_single(overview, blocks, no, date)
    if md is None:
        return jsonify({"ok": False, "error": f"编号 #{no} 不在草稿中"}), 400
    out = next_path(OUTPUT / date / f"AI早报-{date}-单条-{no}.md")
    out.write_text(md, encoding="utf-8")
    return jsonify({"ok": True, "name": out.name, "path": output_rel(out), "title": meta["title"]})


if __name__ == "__main__":
    import socket
    import sys

    ap = argparse.ArgumentParser(description="AI 早报 Web 控制中心")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true", help="只启动服务，不开浏览器")
    args = ap.parse_args()

    url = f"http://127.0.0.1:{args.port}"

    # Windows 上 SO_REUSEADDR 允许重复绑定，不能用 bind 报错判断，只能主动连接探测
    with socket.socket() as probe:
        probe.settimeout(0.5)
        running = probe.connect_ex(("127.0.0.1", args.port)) == 0

    if running:
        print(f"控制中心已在运行，直接打开 {url}")
        if not args.no_browser:
            webbrowser.open(url)
        sys.exit(0)

    try:
        if not args.no_browser:
            threading.Timer(1.5, lambda: webbrowser.open(url)).start()
        print(f"控制中心：{url}  （服务运行期间请保持本窗口开启；Ctrl+C 停止）")
        app.run(host="127.0.0.1", port=args.port, debug=False)
    except OSError:
        print(f"端口 {args.port} 绑定失败。若页面打不开，请关掉之前所有本项目的控制台窗口后重新双击 webui.bat。")
