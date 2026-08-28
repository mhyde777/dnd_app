# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

project_dir = Path(SPECPATH).resolve()

datas = [
    (project_dir / "images", "images"),
]

# The bundled SRD library, when this tree has one. Absent in a plain source
# checkout, so the spec has to stay valid without it.
# Shipped so Help -> Release Notes and Help -> Documentation work offline and
# describe the running build, not whatever is on the web. README.md is the
# "Overview" page in the docs window, so it travels with the rest.
for _doc in ("CHANGELOG.md", "LICENSE-SRD.md", "README.md"):
    if (project_dir / _doc).is_file():
        datas.append((project_dir / _doc, "."))

# The docs/ tree, kept at the same relative path it has in the source checkout
# so app/docs_content.py needs one search order for both. Without this the
# Help -> Documentation window opens empty in a packaged build, which is
# exactly the build where a user cannot fall back to reading the repository.
if (project_dir / "docs").is_dir():
    datas.append((project_dir / "docs", "docs"))

_srd_content = project_dir / "srd_content"
if _srd_content.is_dir():
    # Ship the library and its manifest, not extraction_report.txt -- that is
    # a dev artefact from scripts/extract_srd.py and means nothing to a user.
    datas.append((_srd_content / "MANIFEST.json", "srd_content"))
    for _sub in ("statblocks", "spells", "items"):
        if (_srd_content / _sub).is_dir():
            datas.append((_srd_content / _sub, f"srd_content/{_sub}"))
binaries = []
# The in-process Foundry bridge. It is imported inside LocalBridgeServer.start()
# rather than at module level, so that a user who never enables Foundry sync
# does not pay for Flask at startup -- but that puts it out of easy reach of
# PyInstaller's static analysis, and a packaged build with no bridge_service is
# a build where "run the bridge on this computer" fails at the moment it is
# ticked. Naming it here does not depend on that analysis working.
hiddenimports = [
    "bridge_service",
    "bridge_service.app",
    "bridge_service.command_queue",
    "werkzeug.serving",
]

# Python-Markdown, for Help -> Documentation. ui/docs_window.py imports the
# extension classes directly rather than by name, so static analysis does find
# them -- these are belt and braces, because the failure mode is a window that
# raises "Failed loading extension" only in a packaged build.
hiddenimports += [
    "markdown.extensions.fenced_code",
    "markdown.extensions.sane_lists",
    "markdown.extensions.tables",
    "markdown.extensions.toc",
]

qdark_datas, qdark_binaries, qdark_hidden = collect_all("qdarktheme")
datas += qdark_datas
binaries += qdark_binaries
hiddenimports += qdark_hidden

# charset_normalizer is mypyc-compiled: its modules import a hash-named
# top-level extension (e.g. 81d243bd2c585b0f4821__mypyc...so) that sits beside
# the package in site-packages, not inside it. PyInstaller's static analysis
# cannot see that dynamic import, so `from charset_normalizer import
# __version__` raised ModuleNotFoundError and requests silently fell back to no
# encoding detection. The hash is build-specific, so glob for it -- and glob
# both suffixes: the extension is .so on Linux/macOS but .pyd on Windows, and
# matching only .so meant the fix silently did nothing in the Windows build.
import charset_normalizer as _charset_normalizer

_site_packages = Path(_charset_normalizer.__file__).resolve().parent.parent
binaries += [
    (str(_ext), ".")
    for _pattern in ("*__mypyc*.so", "*__mypyc*.pyd")
    for _ext in _site_packages.glob(_pattern)
]

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

# Each platform accepts exactly one icon format: .ico on Windows, .icns on
# macOS, and PyInstaller ignores the icon entirely on Linux (the .desktop file
# carries it there). Passing the .png on Windows made the build fail outright.
# See docs/packaging-macos.md for generating the .icns.
if sys.platform == "win32":
    _icon = project_dir / "images" / "d20_icon.ico"
elif sys.platform == "darwin":
    _icon = project_dir / "images" / "d20_icon.icns"
else:
    _icon = project_dir / "images" / "d20_icon.png"
icon = str(_icon) if _icon.exists() else None

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
    icon=icon,
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
