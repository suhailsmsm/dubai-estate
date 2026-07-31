# Packaging — Windows installer

Package the Dubai Estate app as a Windows desktop app: a native window
powered by the system **Edge WebView2** (no bundled Chromium → small exe),
with the AI proxy + UI served from one local origin.

```
DubaiEstate.exe             # intermediate build output (PyInstaller --onefile) — NOT distributed
DubaiEstate-Setup-1.0.0.exe # the only distributed artifact: installer w/ Start Menu + Desktop shortcuts, uninstaller
```

## What gets bundled

| Component | Source | In the exe |
|---|---|---|
| Python runtime + our code | `packaging/app.py`, `tools/ai_proxy.py` | yes (PyInstaller) |
| `pywebview` window host | pip | yes (uses system WebView2) |
| Static UI | `ui/**` | yes (data) |
| Settings file | `%APPDATA%\DubaiEstate\.ai.env` | written at runtime (per-user, writable) |

The Bayut/listings data (`ui/data/*.js`) is pre-generated and bundled, so the
Pricing History and AI Assistant pages work fully offline.

## Three ways to build (pick one)

### A. GitHub Actions — no Windows machine needed (recommended)
Push the repo to GitHub, then:
1. **Actions** tab → **Build Windows Installer** → **Run workflow**.
2. When it finishes, download the **DubaiEstate-installer** artifact (contains
   `DubaiEstate-Setup-*.exe`).
3. For a public release: push a tag like `v1.0.0` → the workflow auto-creates a
   draft GitHub Release with the installer attached.

This runs entirely on free GitHub-hosted Windows runners.

### B. Build on a Windows machine
```bat
git clone <repo> && cd dubai-estate
pip install -r packaging/requirements-build.txt
python tools\build_bayut_history.py
python tools\build_market_insights.py
pyinstaller packaging\dxb_app.spec --noconfirm
:: -> dist\DubaiEstate.exe
```

### C. Make the installer (after B)
Install [Inno Setup 6](https://jrsoftware.org/isdl.php), then:
```bat
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\installer.iss
:: -> dist\installer\DubaiEstate-Setup-1.0.0.exe
```

## Keeping the exe small

The spec (`packaging/dxb_app.spec`) is tuned for size:

- **`--onefile`** — single exe, no loose files.
- **`console=False`** — GUI app, no console window.
- **Aggressive stdlib `excludes`** — drops tkinter, unittest, email, ftp/imap/smtp
  clients, audio modules, etc. (saves ~6–10 MB).
- **UPX compression** of every binary (`upx=True`) — auto-disabled if UPX isn't
  installed. Install UPX to shave another ~30%: `winget install upx.upx`.
- **System WebView2** instead of bundling Chromium (Electron ships ~150 MB;
  this approach is ~12–18 MB).

Expected size: **≈ 12–18 MB** for the exe (Python + pywebview + UI). The
installer (`lzma2/ultra64`, solid) compresses that further.

## Runtime requirements (end-user machine)

- **Windows 10/11** — Edge WebView2 is preinstalled.
- For Windows 10 LTSC / older builds without WebView2, uncomment the WebView2
  bootstrapper block in `installer.iss` (the file shows where to drop the
  Microsoft installer).

## Configuration / data locations

| What | Where |
|---|---|
| Program | `%LOCALAPPDATA%\Programs\Dubai Estate Analytics\` (per-user, no admin) |
| Settings (`.ai.env`, DeepSeek key) | `%APPDATA%\DubaiEstate\.ai.env` |

The Settings page (⚙ Settings inside the app) writes the DeepSeek key to the
APPDATA location, so it persists and survives reinstalls/updates.

## Customizing

- **App name / version / publisher** — top of `packaging/installer.iss`.
- **Window size** — `packaging/app.py` (`webview.create_window(...)`).
- **App icon** — add `packaging/app.ico`; the spec references it automatically.
- **Default model** — `tools/ai_proxy.py` (`DEFAULT_MODEL`) or ship a `.ai.env`
  next to the spec with the desired defaults.

## Files

```
packaging/app.py            # launcher: server + pywebview window
packaging/dxb_app.spec      # PyInstaller spec (size-optimized)
packaging/installer.iss     # Inno Setup installer script
packaging/requirements-build.txt
.github/workflows/build-windows.yml   # free cloud build → downloadable exe
```
