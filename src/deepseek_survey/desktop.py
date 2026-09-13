"""One-click Windows launcher with a local browser UI and an owned server lifetime."""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import webbrowser
from http.server import ThreadingHTTPServer
from pathlib import Path

from .artifacts import write_json
from .web import ResearchLibrary, make_handler
from .web_jobs import ResearchJobs


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        directory = Path(sys.executable).resolve().parent
        # Build lives at <project>/dist/PaperAtlas; a copied portable folder uses itself.
        source = directory.parent.parent
        if (source / "config.toml").is_file() and (source / "src" / "deepseek_survey").is_dir():
            return source
        return directory
    return Path(__file__).resolve().parents[2]


def runtime_paths(root: Path):
    for name in (".tmp", ".app-data", "runs"):
        path = root / name
        if not path.resolve().is_relative_to(root):
            raise ValueError("应用数据路径必须位于应用目录内")
        path.mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = os.environ["TMP"] = str(root / ".tmp")
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"


def acquire_lock(root: Path):
    import msvcrt

    handle = (root / ".app-data" / "desktop.lock").open("a+b")
    handle.seek(0)
    if not handle.read(1):
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        return None
    return handle


class DesktopServer:
    def __init__(self, root: Path, port=0):
        self.root = root.resolve()
        runtime_paths(self.root)
        self.jobs = ResearchJobs(ResearchLibrary(self.root / "runs"), self.root / "config.toml")
        self.server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(self.jobs.library, self.jobs))
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self, *, publish=True):
        self.thread.start()
        if publish:
            write_json(self.root / ".app-data" / "desktop.json", {"url": self.url, "pid": os.getpid()})

    def close(self):
        if self.jobs.active_id:
            self.jobs.cancel(self.jobs.active_id)
        self.jobs.subscription.close()
        if self.jobs.thread:
            self.jobs.thread.join(timeout=7)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


def main():
    parser = argparse.ArgumentParser(description="Paper Atlas desktop app")
    parser.add_argument("--project", type=Path, default=project_root())
    parser.add_argument("--headless", action="store_true", help="Run server without the launcher window")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--smoke-test", action="store_true", help="Check packaged assets and exit")
    args = parser.parse_args()
    root = args.project.resolve()
    runtime_paths(root)
    if args.smoke_test:
        import urllib.request

        from .native_launcher import show_launcher
        from .web import ASSETS
        assert (ASSETS / "index.html").is_file()
        assert (ASSETS / "codex.js").is_file()
        from .config import load_config
        load_config(root / "config.toml")
        show_launcher("http://127.0.0.1", str(root), smoke=True)
        app = DesktopServer(root)
        app.start(publish=False)
        try:
            with urllib.request.urlopen(app.url + "/api/runs") as response:
                run_count = len(json.loads(response.read())["runs"])
            status = app.jobs.subscription.bridge.connect()
            write_json(root / ".tmp" / "desktop-smoke.json", {
                "ok": True, "frozen": bool(getattr(sys, "frozen", False)), "native_window": True,
                "runs": run_count, "codex_connected": status["connected"],
                "codex_authenticated": status["authenticated"]})
        finally:
            app.close()
        return
    handle = acquire_lock(root)
    if handle is None:
        try:
            saved = json.loads((root / ".app-data" / "desktop.json").read_text(encoding="utf-8"))
            from urllib.parse import urlsplit
            address = urlsplit(saved["url"])
            if address.scheme == "http" and address.hostname == "127.0.0.1" and address.port:
                webbrowser.open(saved["url"])
        except (OSError, ValueError, KeyError):
            pass
        return
    app = DesktopServer(root, args.port)
    app.start()
    try:
        if args.headless:
            threading.Event().wait()
            return
        from .native_launcher import show_launcher
        show_launcher(app.url, str(root))
    finally:
        app.close()
        handle.close()


if __name__ == "__main__":
    main()
