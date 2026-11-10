import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
Button {
    id: card
    required property var option
    property bool selected: false
    property string schemeLabel: ""
    property string selectedLabel: ""
    implicitWidth: 172; implicitHeight: 124
    padding: 8
    focusPolicy: Qt.StrongFocus
    Accessible.name: option.name + ", " + schemeLabel + (selected ? ", " + selectedLabel : "")
    contentItem: ColumnLayout { spacing: 6
        Rectangle {
            Layout.fillWidth: true; Layout.preferredHeight: 60; radius: 8; color: card.option.canvas; border.color: ui.colors.grid; clip: true
            Rectangle { x: 6; y: 6; width: 26; height: 48; radius: 4; color: card.option.navigation }
            Rectangle { x: 38; y: 8; width: 50; height: 4; radius: 2; color: card.option.muted }
            Rectangle { x: 38; y: 18; width: parent.width-46; height: 36; radius: 4; color: card.option.surface }
            Rectangle { x: 46; y: 40; width: parent.width-90; height: 3; radius: 1.5; color: card.option.accent }
            Rectangle { x: parent.width-36; y: 40; width: 24; height: 8; radius: 3; color: card.option.accent }
        }
        RowLayout { Layout.fillWidth: true; spacing: 6
            ColumnLayout { Layout.fillWidth: true; spacing: 0
                Text { Layout.fillWidth: true; textFormat: Text.PlainText; text: card.option.name; color: ui.colors.text; font.pixelSize: 13; font.weight: Font.DemiBold; elide: Text.ElideRight }
                Text { Layout.fillWidth: true; textFormat: Text.PlainText; text: card.schemeLabel; color: ui.colors.secondary; font.pixelSize: 12; elide: Text.ElideRight }
            }
            Image { visible: card.selected; Layout.preferredWidth: 16; Layout.preferredHeight: 16; source: ui.icon("check", ui.colors.accent); Accessible.ignored: true }
        }
    }
    background: Rectangle {
        radius: ui.tokens["radius-control"] + 2
        color: card.selected ? ui.colors.accentSoft : card.hovered ? ui.colors.hover : "transparent"
        border.width: card.selected || card.visualFocus ? 2 : 1
        border.color: card.selected || card.visualFocus ? ui.colors.focus : ui.colors.line
    }
}
