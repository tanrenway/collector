# Tanren Collector — third-party software

Tanren Collector's own code is licensed under the Apache License 2.0 (see `LICENSE` and `NOTICE`).
The Windows installer also contains the components below. Their full license texts are installed
in the `THIRD_PARTY_LICENSES` folder next to `TanrenCollector.exe`. This file is a summary, not
legal advice and not a replacement for those texts.

| Component | Version | License |
| --- | --- | --- |
| CPython runtime (with OpenSSL, libffi, bzip2, xz, zlib, expat, mpdecimal, SQLite) | 3.12.10 | Python Software Foundation License and the licenses of its components (`Python-LICENSE.txt`) |
| Tcl/Tk (fallback window only) | bundled with CPython | Tcl/Tk license (`TclTk-*-license.terms`) |
| Qt for Python: PySide6-Essentials, shiboken6 | 6.11.2 | GNU LGPL version 3 (chosen from LGPL-3.0 / GPL-2.0 / GPL-3.0) |
| Qt libraries and plugins used by the app (Core, Gui, Widgets, Network, Qml, Quick, Quick Controls Basic, Layouts, Shapes, Svg and their plugins) | 6.11.2 | GNU LGPL version 3, plus the licenses of third-party code inside Qt |
| NumPy (with OpenBLAS, LAPACK and the GCC runtime library) | 2.5.4 | BSD-3-Clause and the licenses of its bundled components; the GCC runtime is GPL-3.0 with the GCC Runtime Library Exception |
| MetaTrader5 Python package | 5.0.6231 | MIT, Copyright MetaQuotes Ltd. |
| Microsoft Visual C++ runtime DLLs (shipped inside the Python wheels) | — | Microsoft redistributable code |
| PyInstaller bootloader | 6.22.3 | GPL-2.0-or-later with the PyInstaller bootloader exception |
| Inno Setup (installer and uninstaller) | 6.7.1 | Inno Setup License |

## Qt under the GNU LGPL version 3

Qt and Qt for Python are used under the GNU Lesser General Public License version 3. See
`THIRD_PARTY_LICENSES/Qt/README.md` for where to get the corresponding source code and how to
replace the Qt libraries with your own build. The installed application keeps every Qt library
as a separate file, so it can be replaced. The application includes no Qt module that is
available only under the GPL; the build fails if one is found.

## What is not included

Collector does not include the MetaTrader 5 terminal, broker software, trading passwords, broker
profiles or market data. It talks to a MetaTrader 5 terminal that you installed yourself, under
that terminal's own license.

## Build tools that are not shipped

pip, setuptools, Pillow, altgraph, pefile, pywin32-ctypes, packaging, PyInstaller (except its
bootloader) and pyinstaller-hooks-contrib are used only while building.
