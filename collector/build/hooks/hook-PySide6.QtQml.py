"""Collector QML inventory: core QtQml and Quick/Controls(Basic)/Templates/Layouts/Window."""

from pathlib import Path

from PyInstaller.utils.hooks.qt import add_qt6_dependencies, pyside6_library_info

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
qml_binaries, qml_datas = pyside6_library_info.collect_qtqml_files()


def required(item):
    pieces = Path(item[0]).as_posix().split("/qml/", 1)
    if len(pieces) != 2:
        return False
    parts = pieces[1].split("/")
    if parts[0] == "QtQml":
        return True
    if parts[0] != "QtQuick":
        return False
    if len(parts) <= 2 or parts[1] in {"Templates", "Layouts", "Window", "Shapes"}:
        return True
    return parts[1] == "Controls" and (len(parts) <= 3 or parts[2] in {"Basic", "impl"})


binaries += [item for item in qml_binaries if required(item)]
datas += [item for item in qml_datas if required(item)]
binaries = [item for item in binaries if "qmltooling" not in item[1]]
