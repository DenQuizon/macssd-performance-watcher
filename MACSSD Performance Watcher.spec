# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = []
hiddenimports += collect_submodules('rumps')
hiddenimports += collect_submodules('psutil')
hiddenimports += collect_submodules('objc')
hiddenimports += collect_submodules('AppKit')


a = Analysis(
    ['pyinstaller_macssd_launcher.py'],
    pathex=['/Users/denquizon/MAC-SSD Software Projects/mac-system-intelligence-monitor/.venv/lib/python3.13/site-packages'],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MACSSD Performance Watcher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['MACSSDIcon.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MACSSD Performance Watcher',
)
app = BUNDLE(
    coll,
    name='MACSSD Performance Watcher.app',
    icon='MACSSDIcon.icns',
    bundle_identifier=None,
)
