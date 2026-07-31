"""Dubai Estate — Windows desktop launcher.

Runs the app as a native window using pywebview (Edge WebView2 on Windows,
which ships with Win10/11 — no bundled Chromium, which keeps the exe small).

What it does, in order:
  1. Locates the bundled UI directory (works in dev and when frozen by
     PyInstaller).
  2. Starts the single-origin HTTP server (UI + /ai/* API) in a background
     thread, reusing tools/ai_proxy.py's Handler with STATIC_DIR set.
  3. Waits for the port to come up, then opens a pywebview window pointed at it.
  4. Writes the user's settings to %APPDATA%/DubaiEstate/.ai.env (writable per-
     user location, not inside Program Files).

Run (dev):
    python packaging/app.py

Frozen by PyInstaller (see dxb_app.spec) into DubaiEstate.exe.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path


def app_root() -> Path:
    """The directory containing bundled app files.

    - Frozen (PyInstaller onefile): bundled data (including ui/) is extracted
      to a temp dir at sys._MEIPASS at startup — that's where files live, NOT
      next to the exe.
    - Dev: the repo root.
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def ui_dir() -> Path:
    """The static UI folder.

    - Frozen (onefile): bundled under sys._MEIPASS/ui.
    - Frozen (onedir) / manual dist: next to the exe (./ui or ./_internal/ui).
    - Dev: repo root / ui.
    """
    root = app_root()
    for cand in (root / "ui", root / "_internal" / "ui"):
        if cand.is_dir():
            return cand
    # Fallback: look beside the script (dev tree).
    dev = Path(__file__).resolve().parent.parent / "ui"
    return dev


def user_data_dir() -> Path:
    """Per-user writable dir for .ai.env (so settings save even from
    Program Files, which is read-only for standard users)."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = Path(base) / "DubaiEstate"
    d.mkdir(parents=True, exist_ok=True)
    return d


def wait_for_port(host: str, port: int, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.15)
    return False


def main() -> None:
    # Defer the heavy import so a bad pywebview install doesn't hide the
    # server-startup error that matters more.
    import webview  # type: ignore

    # Import the proxy module. It lives at tools/ai_proxy.py; add tools/ to path.
    root = app_root()
    tools = root / "tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    import ai_proxy  # noqa: E402

    # Redirect the settings env file to a per-user writable location so the
    # Settings page can save even when the exe is in Program Files.
    ai_proxy.ENV_FILE = user_data_dir() / ".ai.env"
    # Re-read settings now that ENV_FILE points at the user dir; merge with any
    # values already loaded from the bundle's default .ai.env.
    ai_proxy.SETTINGS.update(ai_proxy.load_settings())
    # Serve the bundled UI from the same origin as the API.
    ai_proxy.STATIC_DIR = ui_dir()

    port = ai_proxy.SETTINGS["port"]
    server = ThreadingHTTPServer(("127.0.0.1", port), ai_proxy.Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    url = f"http://127.0.0.1:{port}/"
    if not wait_for_port("127.0.0.1", port):
        # Last resort: open in the default browser if the window fails.
        import webbrowser

        webbrowser.open(url)
        return

    # pywebview window. EdgeChromium backend uses the system WebView2 runtime.
    webview.create_window(
        title="Dubai Estate Analytics",
        url=url,
        width=1280,
        height=840,
        min_size=(960, 600),
        text_select=True,
    )
    try:
        webview.start(gui="edgechrom" if os.name == "nt" else None)
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
