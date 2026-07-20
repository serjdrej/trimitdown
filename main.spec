# -*- mode: python ; coding: utf-8 -*-
import importlib.util
import os
import sysconfig
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

datas = [('static', 'static'), ('core/tiktoken_cache', 'core/tiktoken_cache')]
binaries = []
hiddenimports = []

for pkg in (
    'markitdown', 'magika', 'mammoth', 'pdfminer', 'pptx',
    'openpyxl', 'xlrd', 'olefile', 'bs4', 'lxml', 'tiktoken',
    'pdfplumber',
):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

# tiktoken's encoding constructors live in the separate top-level tiktoken_ext
# namespace package; collect_all('tiktoken') does not pull it. Without it,
# get_encoding("cl100k_base") raises "Unknown encoding" at runtime even with the
# BPE cache bundled — which broke token counting in the packaged app.
hiddenimports += ['tiktoken_ext', 'tiktoken_ext.openai_public']

# The PDF engine ships as the trimitdown-pdf package. PyInstaller bundles a
# normally-installed package but cannot follow an editable install -- it would
# emit an app that looks fine and dies on the first PDF, the same silent failure
# mode as a missing tiktoken_ext. Fail the build instead.
#
# find_spec, not import: importing the module here would drag pdfplumber into
# spec evaluation. DEVELOPMENT.md documents the editable install for day-to-day
# work, so this guard is what stands between that and a broken release build.
_engine = importlib.util.find_spec('trimitdown_pdf')
if _engine is None or _engine.origin is None:
    raise SystemExit(
        'trimitdown_pdf is not installed.\n'
        'Run: pip install ./packages/trimitdown-pdf')
if Path(sysconfig.get_paths()['purelib']).resolve() not in Path(_engine.origin).resolve().parents:
    raise SystemExit(
        f'trimitdown_pdf is installed editable ({_engine.origin}).\n'
        'PyInstaller will not bundle it and the build would ship without the PDF engine.\n'
        'Run: pip install --force-reinstall ./packages/trimitdown-pdf')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TrimItDown',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=os.environ.get('PYI_TARGET_ARCH') or None,
    codesign_identity=None,
    entitlements_file=None,
    icon='mac-build/AppIcon.icns',
)

# onedir, not onefile: a macOS .app built --onefile re-extracts the entire
# bundled payload (markitdown/magika/lxml/...) into a fresh temp dir on every
# launch, which was slow enough to blow past main.py's 15s local-server
# startup timeout and crash before any window opened. onedir lays the files
# out once at build time so launches start immediately. PyInstaller also
# deprecates onefile+windowed .app bundles on macOS for this reason.
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='TrimItDown',
)

app = BUNDLE(
    coll,
    name='TrimItDown.app',
    icon='mac-build/AppIcon.icns',
    bundle_identifier='dev.serjdrej.trimitdown',
    info_plist={
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '11.0',
        # WKWebView blocks plain-HTTP to 127.0.0.1 by default (ATS); the local
        # offline fallback server needs this exception or the window loads blank.
        'NSAppTransportSecurity': {
            'NSAllowsLocalNetworking': True,
        },
    },
)
