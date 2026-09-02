"""AI 早报桌面控制中心。

用 pywebview 打开现有 Flask WebUI，保留 Web 端代码路径，便于快速修改和排查。
"""
from __future__ import annotations

import argparse
import socket
import threading

import webview
from werkzeug.serving import make_server

from webui import app


class ServerThread(threading.Thread):
    def __init__(self, host: str, port: int):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.server = make_server(host, port, app, threaded=True)

    def run(self) -> None:
        self.server.serve_forever()

    def shutdown(self) -> None:
        self.server.shutdown()


def is_running(host: str, port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex((host, port)) == 0


def main() -> int:
    parser = argparse.ArgumentParser(description="AI 早报桌面控制中心")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    host = "127.0.0.1"
    server = None
    if not is_running(host, args.port):
        server = ServerThread(host, args.port)
        server.start()

    window = webview.create_window(
        "AI 早报 · 控制中心",
        f"http://{host}:{args.port}",
        width=1280,
        height=820,
        min_size=(1024, 680),
    )

    if server is not None:
        window.events.closed += server.shutdown

    webview.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
