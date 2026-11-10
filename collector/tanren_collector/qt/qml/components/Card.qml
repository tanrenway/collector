import QtQuick
import QtQuick.Layouts
import QtQuick.Shapes
import QtQuick.Window
Rectangle {
    id: card
    default property alias content: body.data
    property int padding: 20
    property bool spotlight: false
    readonly property color lightColor: ui.colors.accent
    HoverHandler { id: cursor; enabled: card.spotlight && !ui.reducedMotion && card.Window.active }
    Shape {
        anchors.fill: parent
        visible: cursor.hovered && cursor.enabled
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeWidth: 0
            fillGradient: RadialGradient {
                centerX: cursor.point.position.x; centerY: cursor.point.position.y
                focalX: centerX; focalY: centerY; centerRadius: 360
                GradientStop { position: 0; color: Qt.rgba(card.lightColor.r,card.lightColor.g,card.lightColor.b,0.13) }
                GradientStop { position: 1; color: "transparent" }
            }
            PathRectangle { width: card.width; height: card.height; radius: card.radius }
        }
    }
    implicitHeight: body.implicitHeight + padding * 2
    radius: ui.tokens["radius-card"]
    color: ui.colors.surface
    border.color: ui.colors.grid
    border.width: 1
    ColumnLayout { id: body; anchors.fill: parent; anchors.margins: card.padding; spacing: 14 }
}
