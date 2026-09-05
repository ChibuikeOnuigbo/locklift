# PyInstaller build for LockLift Windows File Unlocker.
from pathlib import Path

root = Path(SPECPATH)
assets = root / "assets"

analysis = Analysis(
    [str(root / "unlocker_app.py")],
    pathex=[str(root)],
    binaries=[(str(root / "handle.exe"), "assets")],
    datas=[(str(assets), "assets"), (str(root / "unlocker.ico"), ".")],
    hiddenimports=["win32timezone"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="LockLift",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(root / "unlocker.ico"),
)
