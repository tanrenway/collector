import QtQuick
Text {
    textFormat: Text.PlainText
    property bool secondary: false
    property int size: 14
    color: secondary ? ui.colors.secondary : ui.colors.text
    font.pixelSize: size
    wrapMode: Text.Wrap
    lineHeight: 1.25
    Accessible.role: Accessible.StaticText
    Accessible.name: text
}
