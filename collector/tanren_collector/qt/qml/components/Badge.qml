import QtQuick
Rectangle {
    property string label: ""
    property string kind: "neutral"
    implicitWidth: text.implicitWidth+24
    implicitHeight: 28
    radius: ui.tokens["radius-pill"]
    color: kind === "positive" ? ui.colors.successBg : kind === "error" ? ui.colors.errorBg : kind === "warning" ? ui.colors.warningBg : ui.colors.accentSoft
    Text { textFormat: Text.PlainText; id: text; width: parent.width-24; elide: Text.ElideRight; horizontalAlignment: Text.AlignHCenter; anchors.centerIn: parent; text: parent.label; font.pixelSize: 12; font.weight: Font.Medium; color: parent.kind === "positive" ? ui.colors.positive : parent.kind === "error" ? ui.colors.negative : parent.kind === "warning" ? ui.colors.warning : ui.colors.secondary }
}
