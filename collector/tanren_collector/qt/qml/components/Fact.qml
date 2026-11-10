import QtQuick
import QtQuick.Layouts
ColumnLayout {
    property string label: ""
    property string value: ""
    spacing: 3
    Copy { text: label; secondary: true; size: 12; Layout.fillWidth: true }
    Copy { text: value; size: 15; font.weight: Font.Medium; Layout.fillWidth: true }
}
