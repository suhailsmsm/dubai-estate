# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Dubai Estate desktop app (Windows).

Optimized for SMALLEST size:
  - --onefile: single DubaiEstate.exe
  - windowed (no console window) on Windows
  - aggressive excludes of stdlib modules the app never imports
  - UPX compression of every binary (if UPX is on PATH)
  - only pywebview + our code + the ui/ folder are bundled

Build on Windows:
    pip install pyinstaller pywebview
    pyinstaller packaging/dxb_app.spec --noconfirm

The exe is written to dist/DubaiEstate.exe.
"""

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# Stdlib modules the app provably never uses. Excluding them shrinks the
# bundle substantially (tkinter alone is ~3MB).
EXCLUDES = [
    "tkinter", "unittest", "pydoc_data", "test", "tests",
    "distutils", "lib2to3", "ensurepip", "venv",
    "turtle", "turtledemo", "curses",
    "xmlrpc", "ftplib", "telnetlib", "nntplib", "imaplib", "smtplib", "poplib",
    "audioop", "sndhdr", "aifc", "sunau", "wave", "chunk",
    "crypt", "nis", "ossaudiodev",
]

datas = [
    ("ui", "ui"),
    ("tools/ai_proxy.py", "tools"),
]
# pywebview ships platform backends we don't need on non-Windows — but since we
# build on Windows for Windows, keep it simple and let collect_data_files pull
# pywebview's JS bridge assets.
datas += collect_data_files("webview", include_py_files=False)

a = Analysis(
    ["packaging/app.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "webview.platforms.edgechrom",
        "webview",
        "clr_loader",
        "pythonnet",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# UPX-compress everything for size. Disabled automatically if UPX isn't found.
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DubaiEstate",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,                 # compress binaries
    upx_exclude=["vcruntime140.dll", "python3.dll", "WebView2Loader.dll"],
    runtime_tmpdir=None,
    console=False,            # GUI app — no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="packaging/app.ico",  # optional; build still works if absent
)
