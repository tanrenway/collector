"""Inventory fails closed on missing plugins or unreviewed browser engine."""

import runpy
from pathlib import Path

import pytest

inventory = runpy.run_path(str(Path(__file__).parents[1] / "build/qt_inventory.py"))["inventory"]


def module(root, relative):
    file = root / "_internal/PySide6/Qt" / relative
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(b"synthetic inventory file; not a native library")


def test_missing_qml_modules_rejected(tmp_path):
    with pytest.raises(ValueError, match="Missing required"):
        inventory(tmp_path)


def test_required_modules_and_hashes_are_inventoried(tmp_path):
    for name in [
        "qml/QtQml/qmldir",
        "qml/QtQuick/Controls/Basic/qmldir",
        "qml/QtQuick/Layouts/qmldir",
        "qml/QtQuick/Shapes/qmldir",
    ]:
        module(tmp_path, name)
    result = inventory(tmp_path)
    assert len(result["files"]) == 4
    assert all(len(value["sha256"]) == 64 for value in result["files"].values())
    with pytest.raises(ValueError, match="Windows platform"):
        inventory(tmp_path, windows=True)
    module(tmp_path, "plugins/platforms/qwindows.dll")
    assert inventory(tmp_path, windows=True)["windows_inventory"]


def test_unreviewed_browser_engine_rejected(tmp_path):
    module(tmp_path, "QtWebEngineCore.dll")
    with pytest.raises(ValueError, match="Unreviewed QtWebEngine"):
        inventory(tmp_path)


@pytest.mark.parametrize(
    "relative",
    [
        "Qt6QmlCompiler.dll",
        "Qt6QuickTimeline.dll",
        "Qt6QuickTimelineBlendTrees.dll",
        "Qt6Lottie.dll",
        "Qt6Charts.dll",
        "qml/QtQuick/Timeline/qmldir",
        "qml/QtCharts/qmldir",
    ],
)
def test_gpl_only_qt_modules_fail_the_build(tmp_path, relative):
    for name in [
        "qml/QtQml/qmldir",
        "qml/QtQuick/Controls/Basic/qmldir",
        "qml/QtQuick/Layouts/qmldir",
        "qml/QtQuick/Shapes/qmldir",
    ]:
        module(tmp_path, name)
    assert inventory(tmp_path)
    module(tmp_path, relative)
    with pytest.raises(ValueError, match="GPL-only"):
        inventory(tmp_path)


def test_lgpl_modules_the_app_needs_are_allowed(tmp_path):
    for name in [
        "qml/QtQml/qmldir",
        "qml/QtQuick/Controls/Basic/qmldir",
        "qml/QtQuick/Layouts/qmldir",
        "qml/QtQuick/Shapes/qmldir",
        "Qt6Qml.dll",
        "Qt6Quick.dll",
        "Qt6QuickControls2.dll",
        "Qt6QuickTemplates2.dll",
        "Qt6Svg.dll",
        "Qt6Network.dll",
    ]:
        module(tmp_path, name)
    assert len(inventory(tmp_path)["files"]) == 10
