# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

project_dir = Path(SPECPATH).resolve()

datas = [
    (project_dir / "images", "images"),
]
binaries = []
hiddenimports = []

qdark_datas, qdark_binaries, qdark_hidden = collect_all("qdarktheme")
datas += qdark_datas
binaries += qdark_binaries
hiddenimports += qdark_hidden

a = Analysis(
    ["main.py"],
    pathex=[str(project_dir), str(project_dir / "lib")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="combat_tracker",
    debug=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon=str(project_dir / "images" / "d20_icon.png"),
)
