# -*- mode: python ; coding: utf-8 -*-
# Windows onefile build. main.spec targets macOS (.icns icon + .app BUNDLE, built
# --onedir to dodge the slow re-extraction that broke the .app launch timeout).
# On Windows onefile works fine (see DEVELOPMENT.md), so this spec mirrors
# main.spec's Analysis (same datas + collect-all) and emits a single portable
# TrimItDown-windows-x64.exe with the .ico icon.
import importlib.util
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
# BPE cache bundled, which 500'd every local conversion.
hiddenimports += ['tiktoken_ext', 'tiktoken_ext.openai_public']

# The PDF engine ships as the trimitdown-pdf package. PyInstaller bundles a
# normally-installed package but cannot follow an editable install -- it would
# emit an exe that looks fine and dies on the first PDF, the same silent failure
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
    a.binaries,
    a.datas,
    [],
    name='TrimItDown-windows-x64',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
)
