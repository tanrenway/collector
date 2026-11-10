# PyInstaller spec; run only on Windows x64 through build.ps1, no cross-compilation claim.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, copy_metadata

root = Path(SPECPATH).parent
mt5_data, mt5_binaries, mt5_hidden = collect_all("MetaTrader5")
# MetaTrader5 loads NumPy at runtime; static analysis alone may omit its native .pyd files.
np_data, np_binaries, np_hidden = collect_all("numpy")
for package in ["MetaTrader5", "numpy", "PySide6-Essentials", "PyInstaller"]:
    mt5_data += copy_metadata(package)
a = Analysis([str(root / "desktop_entry.py")], pathex=[str(root)],
             binaries=mt5_binaries + np_binaries, datas=mt5_data + np_data + [(str(root / "tanren_collector/qt/qml"), "tanren_collector/qt/qml"), (str(root / "tanren_collector/qt/assets"), "tanren_collector/qt/assets"), (str(root / "tanren_collector/qt/design.json"), "tanren_collector/qt"), (str(root / "build" / "THIRD_PARTY.md"), "."), (str(root / "build" / "collector.ico"), ".")],
             hiddenimports=mt5_hidden + np_hidden + ["MetaTrader5._core", "PySide6.QtQuickControls2", "PySide6.QtSvg"], hookspath=[str(root / "build" / "hooks")], excludes=["pytest", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="TanrenCollector",
          console=False, icon=str(root / "build" / "collector.ico"),
          version=str(root / "build" / "version-info.txt"), uac_admin=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="TanrenCollector", upx=False)
