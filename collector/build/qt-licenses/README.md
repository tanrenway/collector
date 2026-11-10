# Qt in Tanren Collector

Tanren Collector uses Qt 6.11.2 and Qt for Python (PySide6-Essentials and shiboken6) 6.11.2 under
the **GNU Lesser General Public License version 3** (`LGPL-3.txt`, which builds on `GPL-3.txt`).
`GPL-2.txt` is included because PySide6 is also offered under that license. The Qt sources have
not been modified.

## Corresponding source code

- Qt 6.11.2: https://download.qt.io/archive/qt/6.11/6.11.2/single/
- Qt for Python 6.11.2: https://download.qt.io/official_releases/QtForPython/pyside6/
- The exact PySide6-Essentials and shiboken6 wheels are pinned by SHA-256 in
  `collector/build/windows-requirements.lock` in the Tanren Collector source repository.

A copy of the corresponding source for these exact versions is kept in the `qt-source-6.11.2`
release of the public Tanren Collector repository. If you cannot get it from these places, write to
support@tanrenway.com and we will send it to you, for at least three years after the release.

## Replacing Qt

The application is built as a folder, not a single file. Every Qt library (`Qt6*.dll`), plugin
and the PySide6/shiboken6 extension modules are separate files inside the installation folder
(`%LOCALAPPDATA%\Programs\Tanren Collector\_internal\PySide6`). To use a modified Qt, build the
same Qt and PySide6 versions with the same compiler and replace those files. You can also rebuild
the whole application from the public source with `collector/build/build.ps1`.

Nothing in the Tanren terms forbids modifying the Qt parts for your own use or reverse
engineering needed to debug such modifications.

## Third-party code inside Qt

Qt itself includes third-party code under other licenses, listed for this version at
https://doc.qt.io/qt-6/licenses-used-in-qt.html .
