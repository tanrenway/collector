import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
ColumnLayout {
    id: choice
    property string label: ""
    property var model: []
    property string selectedValue: ""
    property string query: ""
    readonly property bool searchable: model.length > 6
    function restore() {
        let found = -1
        for (let i=0; i<input.count; i++) if (input.valueAt(i) === selectedValue) found=i
        input.currentIndex=found
    }
    onSelectedValueChanged: Qt.callLater(restore)
    onModelChanged: Qt.callLater(restore)
    Copy { text: choice.label; secondary: true; size: 13; Layout.fillWidth: true }
    ComboBox {
        id: input
        objectName: choice.objectName + "Input"
        Layout.fillWidth: true
        implicitHeight: 40
        textRole: "label"; valueRole: "value"
        model: choice.model.filter(row => String(row.label).toLocaleLowerCase().includes(choice.query.toLocaleLowerCase()))
        currentIndex: -1
        wheelEnabled: false
        displayText: { const selected=choice.model.find(row=>row.value===choice.selectedValue); return selected ? selected.label : ui.words.choose }
        onActivated: choice.selectedValue=String(currentValue)
        onModelChanged: Qt.callLater(choice.restore)
        Accessible.name: choice.label
        indicator: Image { x: input.width-width-12; y: (input.height-height)/2; width: 16; height: 16; source: ui.icon("chevron",input.enabled ? ui.colors.secondary : ui.colors.disabledText); rotation: input.popup.visible ? 180 : 0 }
        contentItem: Text { textFormat: Text.PlainText; leftPadding: 12; rightPadding: 36; text: input.displayText; color: input.enabled ? ui.colors.text : ui.colors.disabledText; font.pixelSize: 14; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
        background: Rectangle { radius: ui.tokens["radius-control"]; color: input.hovered ? ui.colors.hover : ui.colors.input; border.color: input.visualFocus || input.popup.visible ? ui.colors.focus : ui.colors.line; border.width: input.visualFocus ? 2 : 1 }
        delegate: ItemDelegate {
            required property var modelData
            required property int index
            width: input.width-8; height: 40
            highlighted: input.highlightedIndex===index
            Accessible.name: String(modelData.label)
            contentItem: RowLayout { spacing: 12
                Text { Layout.fillWidth: true; textFormat: Text.PlainText; text: String(modelData.label); color: ui.colors.text; font.pixelSize: 14; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter }
                Image { visible: choice.selectedValue===modelData.value; source: ui.icon("check",ui.colors.accent); Layout.preferredWidth: 16; Layout.preferredHeight: 16 }
            }
            background: Rectangle { radius: ui.tokens["radius-control"]-2; color: highlighted || parent.hovered ? ui.colors.hover : choice.selectedValue===modelData.value ? ui.colors.accentSoft : "transparent" }
        }
        popup: Popup {
            objectName: choice.objectName+"Popup"
            y: input.height+5; width: input.width
            padding: 4; focus: true
            implicitHeight: Math.min(300, Math.max(44,list.contentHeight)+8+(choice.searchable ? 44 : 0))
            closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
            onClosed: { choice.query=""; Qt.callLater(choice.restore) }
            contentItem: ColumnLayout { spacing: 4
                TextField { objectName: choice.objectName+"Search"; visible: choice.searchable; Layout.fillWidth: true; Layout.preferredHeight: 40; text: choice.query; onTextEdited: choice.query=text; placeholderText: ui.words.search; Accessible.name: ui.words.search; color: ui.colors.text; placeholderTextColor: ui.colors.muted; font.pixelSize: 14; leftPadding: 10
                    background: Rectangle { color: ui.colors.input; radius: ui.tokens["radius-control"]; border.color: parent.activeFocus ? ui.colors.focus : ui.colors.line }
                    Keys.onDownPressed: input.forceActiveFocus()
                }
                ListView { id: list; clip: true; Layout.fillWidth: true; Layout.fillHeight: true; implicitHeight: contentHeight; model: input.popup.visible ? input.delegateModel : null; currentIndex: input.highlightedIndex
                    ScrollBar.vertical: ScrollBar { contentItem: Rectangle { implicitWidth: 4; radius: 2; color: ui.colors.muted } }
                }
                Copy { visible: input.count===0; text: ui.words.noMatches; secondary: true; Layout.fillWidth: true }
            }
            background: Rectangle { radius: ui.tokens["radius-control"]+2; color: ui.colors.elevated; border.color: ui.colors.line }
        }
    }
}
