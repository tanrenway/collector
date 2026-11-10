import QtQuick
import QtQuick.Layouts
RowLayout {
    property string iconName: ""
    property string title: ""
    property string subtitle: ""
    spacing: 12
    Rectangle {
        Layout.preferredWidth: 36; Layout.preferredHeight: 36; Layout.alignment: Qt.AlignTop
        radius: 18; color: ui.colors.elevated; border.color: ui.colors.line
        Image { anchors.centerIn: parent; width: 18; height: 18; source: ui.icon(iconName, ui.colors.secondary); Accessible.ignored: true }
    }
    ColumnLayout { Layout.fillWidth: true; spacing: 2
        Copy { text: title; size: 18; font.weight: Font.DemiBold; Layout.fillWidth: true }
        Copy { visible: subtitle !== ""; text: subtitle; secondary: true; size: 12; Layout.fillWidth: true }
    }
}
