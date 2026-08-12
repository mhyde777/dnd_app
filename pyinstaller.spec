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

# charset_normalizer is mypyc-compiled: its modules import a hash-named
# top-level extension (e.g. 81d243bd2c585b0f4821__mypyc...so) that sits beside
# the package in site-packages, not inside it. PyInstaller's static analysis
# cannot see that dynamic import, so `from charset_normalizer import
# __version__` raised ModuleNotFoundError and requests silently fell back to no
# encoding detection. The hash is build-specific, so glob for it.
import charset_normalizer as _charset_normalizer

_site_packages = Path(_charset_normalizer.__file__).resolve().parent.parent
binaries += [(str(_so), ".") for _so in _site_packages.glob("*__mypyc*.so")]

# Guard list only. PyInstaller follows the real import graph, so none of these
# were ever being bundled -- measured, excluding them changed the bundle by 0
# bytes. They stay as cheap insurance against a stray future import, not as a
# size optimisation. Excluding unused PyQt5.Qt* modules was also measured as
# ineffective: the PyQt5 hook collects the Qt shared libraries wholesale.
excludes = [
    "pandas",
    "numpy",
    "pytz",
    "tzdata",
    "tkinter",
    "pytest",
    "_pytest",
]

a = Analysis(
    ["main.py"],
    pathex=[str(project_dir), str(project_dir / "lib")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

# onedir build: a onefile binary re-extracts the whole bundle to a temp
# directory on every launch, which dominated startup time. package.sh handles
# either layout.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="combat_tracker",
    debug=False,
    upx=False,
    console=False,
    icon=str(project_dir / "images" / "d20_icon.png"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="combat_tracker",
)
