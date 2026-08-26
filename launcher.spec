# launcher.spec — the stable entry point, built separately from the app.
#
# One file, standard library only, no Qt. It has to start even when the app it
# launches is broken, and it is the one piece an update cannot replace while it
# is running — so it stays small and changes as rarely as possible.
#
# onefile is right here for the opposite reason to the app: the launcher is
# tiny, so the extract-to-temp cost is negligible, and a single file is far
# easier to keep intact across updates that replace everything around it.
import sys
from pathlib import Path

project_dir = Path(SPECPATH).resolve()

if sys.platform == "win32":
    _icon = project_dir / "images" / "d20_icon.ico"
elif sys.platform == "darwin":
    _icon = project_dir / "images" / "d20_icon.icns"
else:
    _icon = project_dir / "images" / "d20_icon.png"
icon = str(_icon) if _icon.exists() else None

a = Analysis(
    ["launcher.py"],
    pathex=[str(project_dir)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    excludes=["PyQt5", "pandas", "numpy", "requests", "pytest", "tkinter"],
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
    name="combat-tracker",
    debug=False,
    upx=False,
    console=False,
    icon=icon,
)
