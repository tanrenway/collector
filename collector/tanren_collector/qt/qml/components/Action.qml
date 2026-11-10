import QtQuick
import QtQuick.Controls
import QtQuick.Window
Button {
    id: control
    property bool primary: false
    property string variant: primary ? "primary" : "secondary"
    property bool loading: false
    property string iconName: ""
    property real iconRotation: 0
    readonly property bool filled: variant==="primary"
    readonly property color ink: !enabled ? ui.colors.disabledText : variant==="destructive" ? ui.colors.negative : filled ? ui.colors.accentInk : ui.colors.text
    implicitHeight: 38
    implicitWidth: variant==="icon" ? 38 : Math.max(80, contentItem.implicitWidth+24)
    padding: 10
    enabled: !loading
    focusPolicy: Qt.StrongFocus
    Accessible.name: text || ui.words.browser
    contentItem: Item {
        implicitWidth: row.implicitWidth
        implicitHeight: row.implicitHeight
        Row {
            id: row
            anchors.centerIn: parent
            spacing: 8
            Image { visible: control.iconName!=="" || control.loading; width: visible ? 17 : 0; height: 17; anchors.verticalCenter: parent.verticalCenter; rotation: control.loading ? 0 : control.iconRotation; source: visible ? ui.icon(control.loading ? "sync" : control.iconName,control.ink) : "" }
            Text { textFormat: Text.PlainText; text: control.loading ? ui.words.loading : control.text; visible: control.variant!=="icon"; font.pixelSize: 13; font.weight: Font.Medium; color: control.ink; anchors.verticalCenter: parent.verticalCenter }
        }
    }
    background: Rectangle {
        radius: ui.tokens["radius-control"]
        color: !control.enabled ? ui.colors.disabled : control.variant==="destructive" ? ui.colors.errorBg : control.filled ? (control.down ? ui.colors.accentActive : control.hovered ? ui.colors.accentHover : ui.colors.accent) : control.down ? ui.colors.accentSoft : control.hovered ? ui.colors.hover : ["tertiary","icon"].includes(control.variant) ? "transparent" : ui.colors.elevated
        border.width: control.visualFocus ? 2 : control.variant==="tertiary" || control.variant==="icon" ? 0 : 1
        border.color: control.visualFocus ? ui.colors.focus : control.filled ? color : ui.colors.line
        Behavior on color { ColorAnimation { duration: ui.reducedMotion || !control.Window.active ? 0 : ui.tokens["motion-fast"] } }
    }
}
