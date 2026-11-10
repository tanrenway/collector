import QtQuick
import QtQuick.Controls
CheckBox {
    id: control
    property string label: ""
    text: label
    Accessible.name: label
    implicitHeight: Math.max(32, contentItem.implicitHeight + 8)
    indicator: Rectangle { x: 0; y: (control.height-height)/2; width: 20; height: 20; radius: 5; color: control.checked ? ui.colors.accent : ui.colors.input; border.width: control.visualFocus ? 2 : 1; border.color: control.visualFocus ? ui.colors.focus : ui.colors.line; Image { anchors.fill: parent; anchors.margins: 3; visible: control.checked; source: ui.icon("check", ui.colors.accentInk) } }
    contentItem: Text { textFormat: Text.PlainText; leftPadding: 30; text: control.label; color: ui.colors.text; font.pixelSize: 14; wrapMode: Text.Wrap; verticalAlignment: Text.AlignVCenter }
}
