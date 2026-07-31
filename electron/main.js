/**
 * Dubai Estate — Electron main process.
 *
 * What this does:
 *   1. Runs a tiny local HTTP server that serves BOTH the static UI and the
 *      /ai/* API from one origin (127.0.0.1:<port>). Mirrors the proven
 *      Python `--serve-ui` design, so the existing HTML pages work unchanged.
 *   2. Opens a BrowserWindow pointed at that origin.
 *
 * The /ai/* API is a faithful Node port of tools/ai_proxy.py: it forwards to
 * any OpenAI-compatible chat endpoint (DeepSeek by default), keeps the API key
 * only in memory + a per-user settings file, and masks the key in responses.
 *
 * No separate Python runtime is needed when packaged with Electron.
 */

const { app, BrowserWindow } = require("electron");
const http = require("http");
const fs = require("fs");
const path = require("path");

const DEFAULTS = {
  base_url: "https://api.deepseek.com",
  model: "deepseek-chat",
  key: "",
};

// ------------------------------------------------------------ settings store
function settingsFile() {
  return path.join(app.getPath("userData"), "settings.json");
}

function loadSettings() {
  try {
    const raw = fs.readFileSync(settingsFile(), "utf8");
    return { ...DEFAULTS, ...JSON.parse(raw) };
  } catch {
    return { ...DEFAULTS };
  }
}

let settings = loadSettings();

function maskKey(k) {
  if (!k) return "";
  if (k.length <= 10) return "•".repeat(k.length);
  return k.slice(0, 4) + "•".repeat(k.length - 8) + k.slice(-4);
}

function saveSettings({ base_url, model, key }) {
  const next = { ...settings };
  if (base_url) next.base_url = String(base_url).trim().replace(/\/+$/, "");
  if (model) next.model = String(model).trim();
  // Preserve the existing key unless a real (non-masked) one is supplied.
  if (key && !String(key).includes("•")) {
    next.key = String(key).trim();
  }
  try {
    fs.writeFileSync(settingsFile(), JSON.stringify(next, null, 2));
  } catch (e) {
    console.error("settings save failed:", e.message);
  }
  settings = next;
  return next;
}

// ------------------------------------------------------------ model forwarding
async function forwardChat({ messages, model, temperature }) {
  if (!settings.key) {
    return {
      error: "no_api_key",
      message:
        "No API key configured. Open Settings (⚙) and enter your DeepSeek key.",
    };
  }
  const body = {
    model: model || settings.model,
    messages,
    stream: false,
  };
  if (temperature != null) body.temperature = temperature;
  const t0 = Date.now();
  try {
    const r = await fetch(settings.base_url + "/v1/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${settings.key}`,
      },
      body: JSON.stringify(body),
    });
    const obj = await r.json();
    if (!r.ok) {
      return {
        error: "upstream_http_error",
        status: r.status,
        message: upstreamErr(r.status, obj),
        detail: obj,
      };
    }
    const choice = (obj.choices || [{}])[0];
    return {
      content: choice?.message?.content || "",
      model: obj.model || body.model,
      usage: obj.usage || {},
      ms: Date.now() - t0,
    };
  } catch (e) {
    return {
      error: "upstream_unreachable",
      message: `Could not reach ${settings.base_url}: ${e.message}`,
      hint: "Is AI_BASE_URL correct and reachable from this machine?",
    };
  }
}

async function testConnection({ base_url, model, key }) {
  const useKey =
    (key && !String(key).includes("•") && String(key).trim()) || settings.key;
  const useBase = (base_url && String(base_url).trim()) || settings.base_url;
  const useModel = (model && String(model).trim()) || settings.model;
  if (!useKey) return { ok: false, message: "No API key set — enter one first." };
  const t0 = Date.now();
  try {
    const r = await fetch(useBase.replace(/\/+$/, "") + "/v1/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${useKey}`,
      },
      body: JSON.stringify({
        model: useModel,
        messages: [{ role: "user", content: "ping" }],
        max_tokens: 1,
        stream: false,
      }),
    });
    const obj = await r.json().catch(() => ({}));
    if (!r.ok) return { ok: false, message: upstreamErr(r.status, obj) };
    return { ok: true, model: obj.model || useModel, ms: Date.now() - t0 };
  } catch (e) {
    return { ok: false, message: `Could not reach endpoint: ${e.message}` };
  }
}

function upstreamErr(status, obj) {
  if (status === 401 || status === 403)
    return `Auth failed (${status}) — the API key is invalid or unauthorized for this model.`;
  if (status === 404)
    return "Model not found (404) — the model name isn't served at this base_url.";
  const msg =
    obj?.error?.message || (typeof obj?.error === "string" ? obj.error : null);
  return `HTTP ${status}: ${msg || JSON.stringify(obj).slice(0, 160)}`;
}

// ------------------------------------------------------------ HTTP helpers
function sendJson(res, status, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Content-Length": Buffer.byteLength(body),
  });
  res.end(body);
}

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
};

function serveStatic(req, res, uiRoot) {
  const pathname = decodeURIComponent(new URL(req.url, "http://x").pathname);
  let rel = pathname.replace(/^\/+/, "");
  if (rel === "" || rel === "app" || rel === "index")
    rel = "index.html";
  const target = path.resolve(uiRoot, rel);
  // Path-traversal guard.
  if (!target.startsWith(path.resolve(uiRoot) + path.sep) && target !== path.resolve(uiRoot)) {
    sendJson(res, 403, { error: "forbidden" });
    return;
  }
  fs.stat(target, (err, st) => {
    if (err || !st.isFile()) {
      sendJson(res, 404, { error: "not_found", path: req.url });
      return;
    }
    const mime = MIME[path.extname(target).toLowerCase()] || "application/octet-stream";
    const data = fs.readFileSync(target);
    res.writeHead(200, {
      "Content-Type": mime,
      "Content-Length": data.length,
      "Cache-Control": "no-cache",
    });
    res.end(data);
  });
}

// ------------------------------------------------------------ server + window
let chosenPort = 8787;

function startServer(uiRoot) {
  return new Promise((resolve) => {
    const server = http.createServer(async (req, res) => {
      if (req.method === "OPTIONS") return sendJson(res, 204, {});

      // /ai/* API
      if (req.url.startsWith("/ai/")) {
        if (req.method === "GET" && req.url.startsWith("/ai/health")) {
          return sendJson(res, 200, {
            ok: true,
            configured: Boolean(settings.key),
            base_url: settings.base_url,
            model: settings.model,
            port: chosenPort,
          });
        }
        if (req.method === "GET" && req.url.startsWith("/ai/settings")) {
          return sendJson(res, 200, {
            configured: Boolean(settings.key),
            base_url: settings.base_url,
            model: settings.model,
            key_masked: maskKey(settings.key),
            env_file: settingsFile(),
            env_file_exists: fs.existsSync(settingsFile()),
          });
        }
        if (req.method === "POST") {
          const body = await readBody(req);
          const j = body ? JSON.parse(body) : {};
          if (req.url === "/ai/ask") return sendJson(res, 200, await forwardChat(j));
          if (req.url === "/ai/settings") {
            const next = saveSettings(j);
            return sendJson(res, 200, {
              ok: true,
              configured: Boolean(next.key),
              base_url: next.base_url,
              model: next.model,
              key_masked: maskKey(next.key),
            });
          }
          if (req.url === "/ai/test")
            return sendJson(res, 200, await testConnection(j));
        }
        return sendJson(res, 404, { error: "not_found", path: req.url });
      }

      // Everything else: serve the static UI from the same origin.
      if (req.method === "GET") return serveStatic(req, res, uiRoot);
      sendJson(res, 404, { error: "not_found", path: req.url });
    });

    // Bind 8787; if busy, walk up to find a free port.
    server.on("error", (e) => {
      if (e.code === "EADDRINUSE" && chosenPort < 8800) {
        chosenPort++;
        server.listen(chosenPort, "127.0.0.1");
      } else {
        console.error("server error:", e);
      }
    });
    server.listen(chosenPort, "127.0.0.1", () => resolve(server));
  });
}

function readBody(req) {
  return new Promise((resolve) => {
    let data = "";
    req.on("data", (c) => (data += c));
    req.on("end", () => resolve(data));
  });
}

function uiRoot() {
  // In production the ui/ folder is packaged next to main.js (asar unpacked
  // for the html, or inside asar — fs reads both). In dev it's ../ui.
  const here = __dirname;
  for (const c of [path.join(here, "ui"), path.join(here, "..", "ui")]) {
    if (fs.existsSync(c)) return c;
  }
  return path.join(here, "..", "ui");
}

let mainWindow = null;
function createWindow(port) {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 960,
    minHeight: 600,
    backgroundColor: "#0d1117",
    autoHideMenuBar: true,
    title: "Dubai Estate Analytics",
    webPreferences: {
      contextIsolation: true,
      // Tell the UI pages which origin to call the API on (they default to
      // 8787, so this only matters if the port had to change).
      preload: path.join(__dirname, "preload.js"),
      additionalArguments: [`--ai-base=http://127.0.0.1:${port}`],
    },
  });
  mainWindow.loadURL(`http://127.0.0.1:${port}/`);
  // mainWindow.webContents.openDevTools(); // uncomment to debug
}

app.whenReady().then(async () => {
  const server = await startServer(uiRoot());
  console.log(`Dubai Estate server on http://127.0.0.1:${chosenPort}`);
  createWindow(chosenPort);
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow(chosenPort);
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
