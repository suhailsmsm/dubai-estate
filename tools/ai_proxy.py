#!/usr/bin/env python3
"""Minimal local proxy that lets the browser AI-assistant reach an
OpenAI-compatible chat model (DeepSeek by default) without exposing the API
key in the page.

Why a proxy?
- Keeps the API key server-side (read from env or a gitignored config file).
- Avoids browser CORS restrictions (DeepSeek/OpenAI block cross-origin calls).
- Lets the UI point at any OpenAI-compatible base URL (the running cli-proxy-api,
  DeepSeek directly, OpenAI, a local Ollama, …).

Endpoints
---------
GET  /ai/health                -> {"ok": true, "configured": bool, ...}
POST /ai/ask   {messages, model?, temperature?}
     -> {"content": str, "model": str, "usage": {...}, "ms": int}
     Streams nothing (single-shot) so the browser gets one clean JSON object.

Config (precedence: env > config file > built-in defaults)
- DEEPSEEK_API_KEY or AI_API_KEY  -> the bearer key
- AI_BASE_URL   (default https://api.deepseek.com)
- AI_MODEL      (default deepseek-chat)
- AI_PORT       (default 8787)

Put a key in  dubai-estate/.ai.env  (gitignored):
    AI_API_KEY=sk-...
    AI_BASE_URL=https://api.deepseek.com
    AI_MODEL=deepseek-chat

Run:
    python3 tools/ai_proxy.py
    # or: AI_API_KEY=sk-... python3 tools/ai_proxy.py

Stdlib only — no pip install required. Tested on Python 3.13+.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".ai.env"

DEFAULT_BASE = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_PORT = 8787


def load_settings() -> dict:
    s = {
        "base_url": DEFAULT_BASE,
        "model": DEFAULT_MODEL,
        "key": "",
        "port": DEFAULT_PORT,
    }
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    s["base_url"] = os.environ.get("AI_BASE_URL", s["base_url"]).rstrip("/")
    s["model"] = os.environ.get("AI_MODEL", s["model"])
    s["key"] = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("AI_API_KEY") or s["key"]
    s["port"] = int(os.environ.get("AI_PORT", s["port"]))
    return s


def _mask(key: str) -> str:
    """Show enough to recognize the key, never the whole thing."""
    if not key:
        return ""
    if len(key) <= 10:
        return "•" * len(key)
    return key[:4] + "•" * (len(key) - 8) + key[-4:]


def save_settings(base_url: str, model: str, key: str | None) -> dict:
    """Persist settings to .ai.env and reload the global SETTINGS in place.

    If key is None or empty, the existing key is preserved (so the masked GET
    never forces a wipe). Pass key="" explicitly via the API only when the
    caller intends to clear it — here we treat falsy as "leave unchanged".
    """
    base_url = (base_url or DEFAULT_BASE).rstrip("/")
    model = (model or DEFAULT_MODEL).strip()
    new_key = SETTINGS["key"]
    if key:  # non-empty replacement
        new_key = key.strip()

    lines = [
        "# Written by the AI Assistant settings page. (gitignored)",
        f"AI_API_KEY={new_key}",
        f"AI_BASE_URL={base_url}",
        f"AI_MODEL={model}",
        f"AI_PORT={SETTINGS['port']}",
    ]
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Reflect immediately so subsequent /ai/ask calls use the new values — no
    # restart needed. Port is intentionally NOT changeable at runtime.
    SETTINGS["base_url"] = base_url
    SETTINGS["model"] = model
    SETTINGS["key"] = new_key
    # Update env so a later load_settings() (e.g. proxy restart) agrees.
    os.environ["AI_BASE_URL"] = base_url
    os.environ["AI_MODEL"] = model
    os.environ["AI_API_KEY"] = new_key
    return {
        "configured": bool(new_key),
        "base_url": base_url,
        "model": model,
        "key_masked": _mask(new_key),
    }


def test_connection(base_url: str, model: str, key: str | None) -> tuple[dict, int]:
    """Tiny 1-token call to verify the key/base_url/model actually work.

    Uses the provided values if given, else falls back to current SETTINGS —
    so a test can validate either candidate settings or the saved ones.
    """
    use_key = (key.strip() if key else None) or SETTINGS["key"]
    use_base = (base_url.strip() if base_url else None) or SETTINGS["base_url"]
    use_base = use_base.rstrip("/")
    use_model = (model.strip() if model else None) or SETTINGS["model"]
    if not use_key:
        return {"ok": False, "message": "No API key set — enter one first."}, 200
    payload = {"model": use_model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1, "stream": False}
    data = json.dumps(payload).encode("utf-8")
    url = use_base + "/v1/chat/completions"
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {use_key}"},
        method="POST",
    )
    try:
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=30) as resp:
            obj = json.loads(resp.read().decode("utf-8"))
        return {"ok": True, "model": obj.get("model", use_model), "ms": int((time.time() - t0) * 1000)}, 200
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        return {"ok": False, "status": e.code, "message": _upstream_err(e.code, body)}, 200
    except urllib.error.URLError as e:
        return {"ok": False, "message": f"Could not reach {url}: {e.reason}"}, 200


def _upstream_err(code: int, body: str) -> str:
    if code in (401, 403):
        return f"Auth failed ({code}) — the API key is invalid or unauthorized for this model."
    if code == 404:
        return f"Model not found (404) — the model name isn't served at this base_url."
    try:
        d = json.loads(body)
        msg = d.get("error", {}).get("message") if isinstance(d.get("error"), dict) else str(d.get("error"))
        return f"HTTP {code}: {msg or body[:160]}"
    except json.JSONDecodeError:
        return f"HTTP {code}: {body[:160]}"


SETTINGS = load_settings()

# Optional static UI directory. When set (packaged app, or --serve-ui), the
# server serves the web pages from the same origin as the API.
STATIC_DIR: Path | None = None


def forward_chat(messages: list[dict], model: str | None, temperature: float | None) -> tuple[dict, int]:
    """Call the OpenAI-compatible /v1/chat/completions endpoint. Returns (body, http_status)."""
    if not SETTINGS["key"]:
        return {
            "error": "no_api_key",
            "message": (
                "No API key configured. Set AI_API_KEY (or DEEPSEEK_API_KEY) in the "
                "environment or in dubai-estate/.ai.env, then restart the proxy."
            ),
        }, 503
    payload = {
        "model": model or SETTINGS["model"],
        "messages": messages,
        "stream": False,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    data = json.dumps(payload).encode("utf-8")
    url = SETTINGS["base_url"] + "/v1/chat/completions"
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {SETTINGS['key']}",
        },
        method="POST",
    )
    try:
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read().decode("utf-8")
            obj = json.loads(raw)
        choice = (obj.get("choices") or [{}])[0]
        msg = choice.get("message", {})
        out = {
            "content": msg.get("content", ""),
            "model": obj.get("model", payload["model"]),
            "usage": obj.get("usage", {}),
            "ms": int((time.time() - t0) * 1000),
        }
        return out, 200
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            err = json.loads(body)
        except json.JSONDecodeError:
            err = {"error": body[:500]}
        return {
            "error": "upstream_http_error",
            "status": e.code,
            "message": "The model endpoint returned an error.",
            "detail": err,
            "hint": (
                "Check AI_BASE_URL/AI_MODEL/AI_API_KEY. If pointing at the local "
                "cli-proxy-api, use AI_BASE_URL=http://127.0.0.1:8317 and "
                "AI_API_KEY=sk-local-proxy-key-2024."
            ),
        }, 502
    except urllib.error.URLError as e:
        return {
            "error": "upstream_unreachable",
            "message": f"Could not reach {url}: {e.reason}",
            "hint": "Is AI_BASE_URL correct and reachable from this machine?",
        }, 502


class Handler(BaseHTTPRequestHandler):
    def _json(self, status: int, obj: dict):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):  # CORS preflight
        self._json(204, {})

    def do_GET(self):
        if self.path.startswith("/ai/health"):
            self._json(200, {
                "ok": True,
                "configured": bool(SETTINGS["key"]),
                "base_url": SETTINGS["base_url"],
                "model": SETTINGS["model"],
                "port": SETTINGS["port"],
            })
            return
        if self.path.startswith("/ai/settings"):
            # Never return the raw key — only a masked hint of it.
            self._json(200, {
                "configured": bool(SETTINGS["key"]),
                "base_url": SETTINGS["base_url"],
                "model": SETTINGS["model"],
                "key_masked": _mask(SETTINGS["key"]),
                "env_file": str(ENV_FILE),
                "env_file_exists": ENV_FILE.exists(),
            })
            return
        # When a static UI dir is configured (packaged app / --serve-ui), serve
        # the web pages from the same origin as the API — avoids file:// CORS
        # quirks and lets the AI calls work with zero config.
        if STATIC_DIR:
            self._serve_static(self.path)
            return
        self._json(404, {"error": "not_found", "path": self.path})

    def _serve_static(self, path: str):
        from urllib.parse import unquote, urlsplit
        # Map "/" -> index.html; block path traversal.
        rel = unquote(urlsplit(path).path).lstrip("/")
        if rel in ("", "app", "index"):
            rel = "index.html"
        target = (STATIC_DIR / rel).resolve()
        try:
            target.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self._json(403, {"error": "forbidden"})
            return
        if not target.is_file():
            self._json(404, {"error": "not_found", "path": path})
            return
        mime = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".ico": "image/x-icon",
        }.get(target.suffix, "application/octet-stream")
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(length) or "{}") if length else {}
        except json.JSONDecodeError:
            self._json(400, {"error": "bad_json"})
            return

        if self.path == "/ai/ask":
            messages = req.get("messages")
            if not isinstance(messages, list) or not messages:
                self._json(400, {"error": "bad_request", "message": "messages[] required"})
                return
            body, status = forward_chat(
                messages, model=req.get("model"), temperature=req.get("temperature"),
            )
            self._json(status, body)
            return

        if self.path == "/ai/settings":
            # Empty/missing key => keep existing (the UI sends the masked value
            # back; we never treat a masked string as a real key).
            raw_key = (req.get("key") or "").strip()
            if raw_key and ("•" in raw_key or raw_key.startswith("sk-•")):
                raw_key = ""  # masked placeholder — don't overwrite the real key
            result = save_settings(
                base_url=req.get("base_url", ""),
                model=req.get("model", ""),
                key=raw_key or None,
            )
            self._json(200, {"ok": True, **result})
            return

        if self.path == "/ai/test":
            body, status = test_connection(
                base_url=req.get("base_url", ""),
                model=req.get("model", ""),
                key=req.get("key") or None,
            )
            self._json(status, body)
            return

        self._json(404, {"error": "not_found", "path": self.path})

    def log_message(self, fmt, *args):  # quieter logging
        if "/ai/ask" in (args[0] if args else ""):
            return
        super().log_message(fmt, *args)


def main():
    global STATIC_DIR
    import argparse
    ap = argparse.ArgumentParser(description="Dubai Estate AI proxy / app server")
    ap.add_argument("--serve-ui", metavar="DIR", help="Also serve the UI from DIR (same origin as /ai/*)")
    args = ap.parse_args()
    if args.serve_ui:
        STATIC_DIR = Path(args.serve_ui).resolve()
        if not STATIC_DIR.is_dir():
            raise SystemExit(f"--serve-ui dir not found: {STATIC_DIR}")
    addr = ("127.0.0.1", SETTINGS["port"])
    srv = ThreadingHTTPServer(addr, Handler)
    print("=" * 64)
    print(" Dubai Estate AI proxy" + (" + app server" if STATIC_DIR else ""))
    print(f"   listening : http://127.0.0.1:{SETTINGS['port']}")
    print(f"   base_url  : {SETTINGS['base_url']}")
    print(f"   model     : {SETTINGS['model']}")
    print(f"   api key   : {'configured ✓' if SETTINGS['key'] else 'MISSING — set AI_API_KEY or use .ai.env'}")
    if STATIC_DIR:
        print(f"   ui served : {STATIC_DIR}")
    if not SETTINGS["key"]:
        print("   hint      : or point at the running cli-proxy-api:")
        print("                AI_BASE_URL=http://127.0.0.1:8317 \\")
        print("                AI_API_KEY=sk-local-proxy-key-2024 \\")
        print("                AI_MODEL=gpt-5.6-terra python3 tools/ai_proxy.py")
    print("   endpoints : GET /ai/health  ·  GET /ai/settings  ·  POST /ai/settings")
    print("               POST /ai/ask  ·  POST /ai/test")
    print("=" * 64)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down.")
        srv.shutdown()


if __name__ == "__main__":
    main()
