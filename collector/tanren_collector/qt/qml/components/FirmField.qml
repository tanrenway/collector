import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
ColumnLayout {
    id: field
    property string label: ""
    property var options: []
    property alias text: input.editText
    spacing: 7
    Copy { text: field.label; secondary: true; size: 13; Layout.fillWidth: true }
    ComboBox {
        id: input
        objectName: field.objectName + "Input"
        Layout.fillWidth: true
        implicitHeight: 42
        editable: true
        selectTextByMouse: true
        model: field.options
        currentIndex: -1
        wheelEnabled: false
        Accessible.name: field.label
        indicator: Image { x: input.width-width-12; y: (input.height-height)/2; width: 16; height: 16; source: ui.icon("chevron",ui.colors.secondary); rotation: input.popup.visible ? 180 : 0 }
        contentItem: TextField {
            leftPadding: 12; rightPadding: 36
            text: input.editText
            color: ui.colors.text
            selectionColor: ui.colors.accent
            selectedTextColor: ui.colors.accentInk
            font.pixelSize: 14
            verticalAlignment: Text.AlignVCenter
            maximumLength: 200
            background: Item {}
        }
        background: Rectangle { radius: ui.tokens["radius-control"]; color: ui.colors.input; border.color: input.activeFocus || input.popup.visible ? ui.colors.focus : ui.colors.line; border.width: input.activeFocus ? 2 : 1 }
        delegate: ItemDelegate {
            required property var modelData
            required property int index
            width: input.width-8; height: 40
            highlighted: input.highlightedIndex===index
            Accessible.name: String(modelData)
            contentItem: Text { textFormat: Text.PlainText; text: String(modelData); color: ui.colors.text; font.pixelSize: 14; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter }
            background: Rectangle { radius: ui.tokens["radius-control"]-2; color: highlighted || parent.hovered ? ui.colors.hover : "transparent" }
        }
        popup: Popup {
            objectName: field.objectName + "Popup"
            y: input.height+5; width: input.width
            padding: 4
            implicitHeight: Math.min(300, list.contentHeight+8)
            closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
            contentItem: ListView { id: list; clip: true; implicitHeight: contentHeight; model: input.popup.visible ? input.delegateModel : null; currentIndex: input.highlightedIndex
                ScrollBar.vertical: ScrollBar { contentItem: Rectangle { implicitWidth: 4; radius: 2; color: ui.colors.muted } }
            }
            background: Rectangle { radius: ui.tokens["radius-control"]+2; color: ui.colors.elevated; border.color: ui.colors.line }
        }
    }
}
