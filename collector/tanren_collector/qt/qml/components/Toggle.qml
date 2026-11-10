import QtQuick
import QtQuick.Controls
Switch {
    id: control
    property string label: ""
    text: label
    Accessible.name: label
    implicitHeight: Math.max(36, contentItem.implicitHeight + 8)
    indicator: Rectangle {
        x: 0; y: (control.height-height)/2; width: 36; height: 20; radius: 10
        color: control.checked ? ui.colors.accent : ui.colors.input
        border.width: control.visualFocus ? 2 : 1
        border.color: control.visualFocus ? ui.colors.focus : control.checked ? ui.colors.accent : ui.colors.muted
        Rectangle { x: control.checked ? 18 : 2; y: 2; width: 16; height: 16; radius: 8; color: control.checked ? ui.colors.accentInk : ui.colors.secondary }
    }
    contentItem: Text { textFormat: Text.PlainText; leftPadding: 46; text: control.label; color: control.enabled ? ui.colors.text : ui.colors.disabledText; font.pixelSize: 14; wrapMode: Text.Wrap; verticalAlignment: Text.AlignVCenter }
}
