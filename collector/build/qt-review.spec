# Review-only Linux/source-equivalent bundle; excludes native MT5/Tk. Never a Windows release.
from pathlib import Path
root = Path(SPECPATH).parent
analysis = Analysis([str(root / 'desktop_entry.py')], pathex=[str(root)],
    datas=[(str(root / 'tanren_collector/qt/qml'), 'tanren_collector/qt/qml'), (str(root / 'tanren_collector/qt/assets'), 'tanren_collector/qt/assets'), (str(root / 'tanren_collector/qt/design.json'), 'tanren_collector/qt')],
    hookspath=[str(root / 'build/hooks')], hiddenimports=['PySide6.QtQuickControls2','PySide6.QtSvg'],
    excludes=['MetaTrader5','tkinter','pytest','PySide6.QtWebEngineCore',
              'PySide6.QtWebEngineWidgets','PySide6.QtWebEngineQuick'], noarchive=False)
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True,
          name='TanrenCollectorQtReview', console=True, upx=False)
collection = COLLECT(exe, analysis.binaries, analysis.datas,
                     name='TanrenCollectorQtReview', upx=False)
