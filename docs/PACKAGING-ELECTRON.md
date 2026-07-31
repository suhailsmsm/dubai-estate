# Packaging — Electron (Windows installer)

A pure **Node/Electron** desktop app: the UI plus a Node port of the AI proxy,
all in one window — no Python runtime needed when packaged.

> **Size reality:** an Electron build is ~90–110 MB (Windows NSIS, compressed)
> / ~226 MB (macOS app bundle, uncompressed). That's because Electron bundles
> Chromium + Node.js. If **smallest size** matters more than portability, use
> the pywebview packaging in [PACKAGING.md](PACKAGING.md) instead (~12–18 MB).
> Electron's trade-off: it works on any Windows without depending on the system
> WebView2 runtime, and it's cross-platform (Win/macOS/Linux) from one config.

## What gets bundled

| Component | Source | Bundled |
|---|---|---|
| Electron runtime (Chromium + Node) | `electron` (npm) | yes |
| Main process (window + embedded AI proxy) | `electron/main.js` | yes (asar) |
| Preload (exposes API origin) | `electron/preload.js` | yes (asar) |
| Static UI | `ui/**` | yes (asar) |
| Settings file | `%APPDATA%\Dubai Estate Analytics\settings.json` | written at runtime |

The `files` glob in `package.json` restricts bundling to `electron/` + `ui/` +
`package.json` only — verified: nothing else (api/, elt/, python tools) leaks in.

## The Node AI proxy (no Python needed)

`electron/main.js` reimplements `tools/ai_proxy.py` in Node: it runs a local
HTTP server on `127.0.0.1:8787` that serves **both** the static UI and the
`/ai/*` API from one origin (mirrors the Python `--serve-ui` design). Endpoints:
`GET /ai/health`, `GET /ai/settings`, `POST /ai/settings`, `POST /ai/ask`,
`POST /ai/test`. The DeepSeek key lives in `settings.json` (per-user, writable)
and is masked in responses — same security posture as the Python version.

Verified standalone: health, settings (save+reload), static serving, and
path-traversal blocking all work in plain Node.

## Build (three ways)

### A. GitHub Actions — no Windows machine needed (recommended)
Push to GitHub, then **Actions** tab → **Build Electron Installer** →
**Run workflow**. Download the **DubaiEstate-electron-windows** artifact
(contains `DubaiEstate-Setup-1.0.0.exe`). Tag `v1.0.0` for an auto release.

### B. Build on a Windows machine
```bat
git clone <repo> && cd dubai-estate
npm install
python tools\build_bayut_history.py
python tools\build_market_insights.py
npm run dist:win
:: -> release\DubaiEstate-Setup-1.0.0.exe
```

### C. Run in development (any OS)
```bash
npm install
npm start            # opens the Electron window
```

## Size optimization (already applied)

- **`asar: true`** — packs app code into a single archive.
- **`compression: "maximum"`** — LZMA for the NSIS installer.
- **Restricted `files`** — only `electron/` + `ui/` + `package.json`.
- **`removePackageScripts` / `removePackageKeywords`** — strip dev cruft.
- **x64 only** for Windows (smaller than universal).

To shrink further, you can switch the Windows target from `nsis` to `portable`
(single unpacked exe) or enable `electronLanguages` to drop unused locales.

## Configuration / data locations (Windows)

| What | Where |
|---|---|
| Program | `%LOCALAPPDATA%\Programs\dubai-estate\` (per-user) |
| Settings + DeepSeek key | `%APPDATA%\Dubai Estate Analytics\settings.json` |

The in-app Settings page (⚙) writes the key to the APPDATA location, so it
persists across updates.

## Cross-platform

The same `package.json` config builds macOS (`.dmg`) and Linux (`.AppImage`):
```bash
npm run dist:mac      # .dmg (needs macOS to sign)
npm run dist:linux    # .AppImage
```

## Files

```
electron/main.js                          # main process: window + Node AI proxy
electron/preload.js                       # exposes the API origin to the page
package.json                              # electron + electron-builder config
.github/workflows/build-electron.yml      # free cloud build → downloadable exe
```

## Choosing Electron vs pywebview

| | Electron | pywebview (PACKAGING.md) |
|---|---|---|
| Size | ~90–110 MB (NSIS) | ~12–18 MB |
| Python needed at runtime | no | yes (bundled) |
| System dependency | none | Edge WebView2 (Win10/11 has it) |
| Cross-platform from one config | yes | Windows-focused |
| Maturity/tooling | very mature | lighter |
