import QtQuick
import QtQuick.Controls
Menu {
    id: menu
    property string bindingId: ""
    signal detailsRequested()
    width: 240
    padding: 5
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
    background: Rectangle { color: ui.colors.elevated; radius: ui.tokens["radius-control"]+2; border.color: ui.colors.line }
    component Entry: MenuItem {
        implicitHeight: 38
        contentItem: Text { textFormat: Text.PlainText; text: parent.text; font.pixelSize: 13; color: ui.colors.text; verticalAlignment: Text.AlignVCenter; leftPadding: 10 }
        background: Rectangle { radius: ui.tokens["radius-control"]-2; color: parent.highlighted || parent.hovered ? ui.colors.hover : "transparent" }
    }
    Entry { text: ui.words.details; onTriggered: menu.detailsRequested() }
    Entry { text: ui.words.pause; onTriggered: ui.accountAction(menu.bindingId,"pause") }
    Entry { text: ui.words.resume; onTriggered: ui.accountAction(menu.bindingId,"resume") }
    Entry { text: ui.words.reviewAccess; onTriggered: ui.openBrowser() }
}
