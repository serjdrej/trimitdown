# -*- mode: python ; coding: utf-8 -*-
# Windows onefile build. main.spec targets macOS (.icns icon + .app BUNDLE, built
# --onedir to dodge the slow re-extraction that broke the .app launch timeout).
# On Windows onefile works fine (see DEVELOPMENT.md), so this spec mirrors
# main.spec's Analysis (same datas + collect-all) and emits a single portable
# TrimItDown-windows-x64.exe with the .ico icon.
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
