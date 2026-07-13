# -*- mode: python ; coding: utf-8 -*-
import os

from PyInstaller.utils.hooks import collect_all

datas = [('static', 'static'), ('core/tiktoken_cache', 'core/tiktoken_cache')]
binaries = []
hiddenimports = []

for pkg in (
    'markitdown', 'magika', 'mammoth', 'pdfminer', 'pptx',
    'openpyxl', 'xlrd', 'olefile', 'bs4', 'lxml', 'tiktoken',
):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

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
    name='MarkItDown',
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
    name='MarkItDown',
)

app = BUNDLE(
    coll,
    name='MarkItDown.app',
    icon='mac-build/AppIcon.icns',
    bundle_identifier='dev.serjdrej.markitdown',
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
