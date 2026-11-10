import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
ColumnLayout {
    id: field
    property string label: ""
    property alias text: input.text
    property alias placeholderText: input.placeholderText
    property bool secret: false
    spacing: 7
    Copy { text: field.label; secondary: true; size: 13; Layout.fillWidth: true }
    TextField {
        id: input
        objectName: field.objectName + "Input"
        Layout.fillWidth: true
        implicitHeight: 42
        color: ui.colors.text
        selectionColor: ui.colors.accent
        selectedTextColor: ui.colors.accentInk
        placeholderTextColor: ui.colors.muted
        font.pixelSize: 14
        leftPadding: 12
        maximumLength: field.secret ? 32 : 200
        echoMode: field.secret ? TextInput.Password : TextInput.Normal
        Accessible.name: field.label
        background: Rectangle { radius: ui.tokens["radius-control"]; color: ui.colors.input; border.color: input.activeFocus ? ui.colors.focus : ui.colors.line; border.width: input.activeFocus ? 2 : 1 }
    }
}
