import QtQuick
import QtQuick.Controls
import QtQuick.Window
import QtQuick.Layouts
import "components" as C

ApplicationWindow {
    id: root
    objectName: "mainWindow"
    width: 1180; height: 840
    minimumWidth: 640; minimumHeight: 540
    visible: true
    title: Qt.application.name
    color: ui.colors.canvas
    property int screenIndex: 1
    property var pageKeys: ["welcome","dashboard","accounts","add","details","migration","settings","support","activity"]
    property var pageIcons: ["link","grid","accounts","plus","details","migration","settings","support","activity"]
    property var mainSections: [1,2,8,6]
    property bool firstSnapshot: true
    property bool onboarding: false
    property bool geometryReady: false
    onWidthChanged: if(geometryReady && !ui.synthetic) geometrySave.restart()
    onHeightChanged: if(geometryReady && !ui.synthetic) geometrySave.restart()
    Timer { id: geometrySave; interval: 700; onTriggered: ui.saveWindow(Math.min(2560,root.width),Math.min(1600,root.height),root.visibility===Window.Maximized) }
    property string confirmKind: ""
    property bool repairing: false
    property string deviceError: (ui.state.device || {}).error || ""
    property bool compact: width < 900
    function t(key) { return ui.words[key] || key }
    function value(data) { return data === undefined || data === null || data === "" ? t("notAvailable") : String(data) }
    function accountOptions() { return (ui.state.accounts || []).map((a,i) => ({value:a.binding_id,label:(a.name || t("accounts") + " · " + (i+1))})) }
    function select(binding) { ui.selectAccount(binding); detailChoice.selectedValue=binding; detailChoice.restore(); migrationChoice.selectedValue=binding; migrationChoice.restore(); screenIndex=4 }
    function confirm(kind) { confirmKind=kind; confirmation.open() }
    function accountLine(a) { return root.value(a.broker)+(a.login_suffix ? " · •••• "+a.login_suffix : "") }
    function accountStatus(a) {
        if (!a || !a.binding_id) return {label:t("statusChecking"),kind:"neutral"}
        if (a.stage==="paused") return {label:t("statusPaused"),kind:"neutral"}
        if (["authorization_required","awaiting_handover","continuity_review","access_denied"].includes(a.stage)) return {label:t("statusAction"),kind:"warning"}
        if (a.stage==="waiting" || a.error) return {label:t("statusRetrying"),kind:"warning"}
        if (a.role==="standby") return {label:t("statusStandby"),kind:"neutral"}
        if (a.stage==="unknown" && a.role==="unknown") return {label:t("statusChecking"),kind:"neutral"}
        return {label:t("statusSyncing"),kind:"positive"}
    }
    function overview() {
        const rows=ui.state.accounts || []
        if ((ui.state.device || {}).state!=="paired") return {title:t("overviewNoDevice"),hint:t("overviewNoDeviceHint"),kind:"warning"}
        if (rows.length===0) return {title:t("overviewEmpty"),hint:t("overviewEmptyHint"),kind:"neutral"}
        if (rows.some(a => accountStatus(a).kind==="warning" || a.review>0)) return {title:t("overviewAttention"),hint:t("overviewAttentionHint"),kind:"warning"}
        if (rows.every(a => a.stage==="paused")) return {title:t("overviewPaused"),hint:t("overviewPausedHint"),kind:"neutral"}
        return {title:t("overviewOk"),hint:t("overviewOkHint"),kind:"positive"}
    }
    function activityLabel(row) { return ui.words["activity_"+row.subject+"_"+row.state] || t(row.state) }
    property string prefilledFor: ""
    property bool accountAdvanced: false
    property bool supportDetails: false
    readonly property var previewedTerminal: (ui.state.terminals || []).find(t => t.key===terminalChoice.selectedValue && t.broker) || null
    function prefillAccount() {
        const t=previewedTerminal
        if (!t) return
        const key=t.key+"|"+t.server+"|"+t.login_suffix
        if (key===prefilledFor) return
        prefilledFor=key
        const suggested=ui.suggestFirm(t.broker,t.server)
        firm.text=suggested || t.broker
        accountName.text=(suggested || t.broker)+" "+t.login_suffix
        // Never guess "personal": without a firm match or a demo server the user picks the category.
        category.selectedValue=/demo/i.test(t.server) ? "demo" : suggested ? "prop_firm" : ""
        timezone.text=ui.systemTimezone
        baseline.text=t.starting_balance || ""
        ui.trace("ui_prefilled","ok")
    }
    onPreviewedTerminalChanged: { ui.trace("ui_previewed",previewedTerminal ? "row" : "none"); prefillAccount() }
    onScreenIndexChanged: { if (screenIndex===3 && !ui.synthetic && (ui.state.terminals || []).length===0) ui.discover(); pairCode.text=""; drainConfirmation.checked=false; ui.dismissNotice(); Qt.callLater(function() { scroll.contentItem.contentY=0 }) }
    onClosing: function(close) {
        close.accepted=false
        if(!ui.synthetic) ui.saveWindow(Math.min(2560,root.width),Math.min(1600,root.height),root.visibility===Window.Maximized)
        if (ui.preferences.close_to_tray && ui.trayAvailable) root.hide()
        else root.confirm("quit")
    }
    Shortcut { sequence: "Alt+1"; onActivated: root.screenIndex=1 }
    Shortcut { sequence: "Alt+2"; onActivated: root.screenIndex=2 }
    Shortcut { sequence: "Alt+3"; onActivated: root.screenIndex=8 }
    Shortcut { sequence: "Ctrl+,"; onActivated: root.screenIndex=6 }
    Connections {
        target: ui
        function onSettingsChanged() {
            if(!root.geometryReady && !ui.synthetic) {
                root.width=ui.preferences.window_width
                root.height=ui.preferences.window_height
                if(ui.preferences.window_maximized) root.showMaximized()
                root.geometryReady=true
            }
        }
        function onQuitRequested() { root.confirm("quit") }
        function onChanged() {
            if(root.firstSnapshot) {
                root.firstSnapshot=false
                root.onboarding=(ui.state.accounts || []).length===0
                if(root.onboarding) root.screenIndex=(ui.state.device || {}).state==="paired" ? 3 : 0
            }
            if(root.onboarding && (ui.state.device || {}).state==="paired" && root.screenIndex===0) root.screenIndex=3
            if(root.onboarding && (ui.state.accounts || []).length>0) { root.onboarding=false; root.select(ui.state.accounts[0].binding_id) }
        }
    }

    RowLayout {
        anchors.fill: parent; spacing: 0
        Rectangle {
            Layout.preferredWidth: root.compact ? 72 : 212
            Layout.fillHeight: true
            color: ui.colors.navigation
            ColumnLayout {
                anchors.fill: parent; anchors.margins: root.compact ? 12 : 20; spacing: 10
                RowLayout {
                    Layout.topMargin: 14; Layout.bottomMargin: 26; spacing: 10
                    Image { source: ui.mark(ui.colors.muted,ui.colors.accent,ui.colors.sessionLondon); sourceSize.width: 72; sourceSize.height: 42; Layout.preferredWidth: 36; Layout.preferredHeight: 21; Accessible.ignored: true }
                    C.Copy { visible: !root.compact; text: "Tanren"; size: 19; font.weight: Font.DemiBold }
                }
                Repeater {
                    model: root.mainSections
                    delegate: Button {
                        required property int modelData
                        required property int index
                        objectName: "nav"+index
                        Layout.minimumWidth: 0
                        Layout.fillWidth: true
                        implicitHeight: root.compact ? 46 : Math.max(44,label.implicitHeight+20)
                        focusPolicy: Qt.StrongFocus
                        Accessible.name: root.t(root.pageKeys[modelData])
                        onClicked: root.screenIndex=modelData
                        ToolTip.visible: hovered && root.compact
                        ToolTip.text: root.t(root.pageKeys[modelData])
                        background: Rectangle { radius: ui.tokens["radius-control"]; color: (root.screenIndex===modelData || (modelData===2 && [3,4,5].includes(root.screenIndex))) ? ui.colors.accentSoft : parent.hovered ? ui.colors.hover : "transparent"; border.width: parent.visualFocus ? 2 : 0; border.color: ui.colors.focus }
                        contentItem: RowLayout { spacing: 12; Image { Layout.preferredWidth: 20; Layout.preferredHeight: 20; source: ui.icon(root.pageIcons[modelData], (root.screenIndex===modelData || (modelData===2 && [3,4,5].includes(root.screenIndex))) ? ui.colors.accent : ui.colors.muted) } C.Copy { id: label; visible: !root.compact; Layout.fillWidth: true; text: root.t(root.pageKeys[modelData]); color: (root.screenIndex===modelData || (modelData===2 && [3,4,5].includes(root.screenIndex))) ? ui.colors.text : ui.colors.secondary; size: 13; font.weight: (root.screenIndex===modelData || (modelData===2 && [3,4,5].includes(root.screenIndex))) ? Font.DemiBold : Font.Normal } }
                    }
                }
                Item { Layout.fillHeight: true }
                C.Copy { visible: !root.compact; Layout.fillWidth: true; text: "COLLECTOR · " + ui.build.version; secondary: true; size: 11 }
                C.Action { objectName: "sidebarUpdate"; visible: !root.compact && ["available","ready"].includes(ui.updateInfo.state); primary: true; text: root.t("updateAvailableShort"); Layout.fillWidth: true; onClicked: root.screenIndex=6 }
                C.Badge { visible: !root.compact; Layout.minimumWidth: 0; Layout.maximumWidth: 172; Layout.fillWidth: true; label: root.t((ui.state.device || {}).state || "disconnected"); kind: (ui.state.device || {}).state === "paired" ? "positive" : "warning" }
            }
        }
        ColumnLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; spacing: 0
            Rectangle {
                Layout.fillWidth: true; Layout.preferredHeight: 70; color: ui.colors.canvas
                RowLayout { anchors.fill: parent; anchors.leftMargin: 28; anchors.rightMargin: 28
                    ColumnLayout { spacing: 3; C.Copy { text: "Tanren Collector"; size: 15; font.weight: Font.DemiBold } C.Copy { text: root.t("workspaceHint"); secondary: true; size: 11 } }
                    Item { Layout.fillWidth: true }
                    C.Badge { visible: ui.synthetic; Layout.minimumWidth: 0; Layout.maximumWidth: root.compact ? 150 : implicitWidth; label: root.t("syntheticPreview"); kind: "warning" }
                    C.Action { objectName: "browserButton"; text: root.compact ? "" : root.t("browser"); iconName: "external"; onClicked: ui.openBrowser() }
                }
            }
            Rectangle {
                objectName: "notificationBanner"
                visible: ui.noticeVisible || !!ui.state.error || !!root.deviceError || !!ui.state.suspended
                Layout.fillWidth: true; Layout.preferredHeight: notice.implicitHeight+22
                color: ui.command.phase === "failed" || ui.state.error || root.deviceError ? ui.colors.errorBg : ui.colors.accentSoft
                C.Copy { id: notice; anchors.left: parent.left; anchors.right: parent.right; anchors.margins: 28; anchors.verticalCenter: parent.verticalCenter; size: 13; text: ui.state.suspended ? root.t("suspended") : (ui.state.error || root.deviceError ? ui.explain(ui.state.error || root.deviceError) : root.t(ui.command.phase==="pending" ? "loading" : ui.command.phase || "idle") + (ui.command.error ? " · " + ui.explain(ui.command.error) : "")); Accessible.role: Accessible.AlertMessage }
            }
            ScrollView {
                id: scroll
                objectName: "pageScroll"
                Layout.fillWidth: true; Layout.fillHeight: true
                clip: true
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                contentWidth: availableWidth
                contentHeight: pageBody.implicitHeight
                ColumnLayout {
                    id: pageBody
                    height: implicitHeight
                    width: scroll.availableWidth
                    spacing: 0
                    Item { Layout.preferredHeight: 24 }
                    StackLayout {
                        id: pages
                        currentIndex: root.screenIndex
                        Layout.minimumHeight: 0
                        Layout.preferredHeight: children[currentIndex] ? children[currentIndex].implicitHeight : 0
                        Layout.maximumHeight: Layout.preferredHeight
                        Layout.fillWidth: true; Layout.leftMargin: root.compact ? 16 : 28; Layout.rightMargin: root.compact ? 16 : 28
                        // Welcome
                        ColumnLayout {
                            spacing: 20
                            C.Copy { text: root.t("stepLabel")+" · 1 / 3"; color: ui.colors.accent; Layout.fillWidth: true }
                            C.Copy { text: root.t("pairTitle"); size: 28; font.weight: Font.DemiBold; Layout.fillWidth: true }
                            C.Copy { text: root.t("subtitle"); secondary: true; size: 17; Layout.fillWidth: true }
                            C.Card {
                                Layout.fillWidth: true
                                C.Copy { visible: root.repairing; text: root.t("repairWarning"); color: ui.colors.warning; Layout.fillWidth: true }
                                C.Copy { text: root.t("pairHint"); secondary: true; Layout.fillWidth: true }
                                C.Field { id: deviceName; objectName: "deviceName"; label: root.t("deviceName"); Layout.fillWidth: true }
                                C.Field { id: pairCode; objectName: "pairCode"; label: root.t("pairCode"); secret: true; Layout.fillWidth: true }
                                Flow { Layout.fillWidth: true; spacing: 10
                                    C.Action { objectName: "pairButton"; enabled: pairCode.text.trim().length>0 && deviceName.text.trim().length>0; text: root.t("pair"); primary: true; loading: ui.command.action==="pair" && ["submitted","pending"].includes(ui.command.phase); onClicked: { if(root.repairing) root.confirm("repair"); else if (ui.pair(pairCode.text,deviceName.text,false,false)) pairCode.text="" } }
                                    C.Action { text: root.t("browser"); onClicked: ui.openBrowser() }
                                }
                                C.Badge { label: root.t((ui.state.device || {}).state || "disconnected"); kind: (ui.state.device || {}).state === "paired" ? "positive" : "warning" }
                                C.Copy { visible: !!(ui.state.device || {}).verification_phrase; text: root.t("phrase")+": "+((ui.state.device || {}).verification_phrase || ""); size: 21; font.weight: Font.DemiBold; Layout.fillWidth: true }
                                C.Copy { text: root.t("expiresHint"); secondary: true; Layout.fillWidth: true }
                                C.Copy { visible: !!(ui.state.device || {}).error; text: ui.explain((ui.state.device || {}).error || ""); color: ui.colors.negative; Layout.fillWidth: true }
                            }
                            Item { Layout.preferredHeight: 12 }
                        }
                        // Dashboard
                        ColumnLayout {
                            spacing: 20
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 16
                                ColumnLayout { Layout.fillWidth: true; spacing: 4; C.Copy { text: root.t("dashboard"); size: 25; font.weight: Font.DemiBold; Layout.fillWidth: true } C.Copy { text: root.t("readyHint"); secondary: true; Layout.fillWidth: true } }
                                C.Action { objectName: "addFromDashboard"; iconName: "plus"; text: root.t("add"); primary: true; onClicked: root.screenIndex=3 }
                            }
                            C.Card { objectName: "statusCard"; Layout.fillWidth: true; padding: 24
                                GridLayout { Layout.fillWidth: true; columns: root.compact ? 1 : 2; columnSpacing: 32; rowSpacing: 16
                                    RowLayout { Layout.fillWidth: true; spacing: 14
                                        Rectangle { Layout.preferredWidth: 12; Layout.preferredHeight: 12; Layout.alignment: Qt.AlignTop; Layout.topMargin: 9; radius: 6; color: root.overview().kind==="positive" ? ui.colors.positive : root.overview().kind==="warning" ? ui.colors.warning : ui.colors.muted; Accessible.ignored: true }
                                        ColumnLayout { Layout.fillWidth: true; spacing: 4
                                            C.Copy { objectName: "statusTitle"; text: root.overview().title; size: 21; font.weight: Font.DemiBold; Layout.fillWidth: true }
                                            C.Copy { text: root.overview().hint; secondary: true; Layout.fillWidth: true }
                                        }
                                    }
                                    ColumnLayout { visible: ui.summary.accounts>0; Layout.alignment: Qt.AlignVCenter; spacing: 2
                                        C.Copy { text: root.t("lastSync"); secondary: true; size: 12 }
                                        C.Copy { objectName: "lastSyncValue"; text: ui.time(ui.summary.last_synced); size: 16; font.weight: Font.DemiBold }
                                    }
                                }
                                Flow { Layout.fillWidth: true; spacing: 10
                                    C.Action { visible: (ui.state.device || {}).state!=="paired"; text: root.t("connectApp"); primary: true; onClicked: root.screenIndex=0 }
                                    C.Action { objectName: "refreshButton"; visible: ui.summary.accounts>0; iconName: "sync"; text: root.t("refresh"); onClicked: ui.refresh() }
                                }
                            }
                            C.Card { Layout.fillWidth: true; visible: ui.summary.accounts===0
                                C.Copy { text: root.t("noAccounts"); size: 18; font.weight: Font.DemiBold; Layout.fillWidth: true }
                                C.Copy { text: root.t("noAccountsHint"); secondary: true; Layout.fillWidth: true }
                            }
                            C.Copy { visible: ui.summary.accounts>0; text: root.t("accounts"); size: 17; font.weight: Font.DemiBold }
                            Repeater { model: (ui.state.accounts || []).slice(0,5)
                                C.Card { required property var modelData; Layout.fillWidth: true
                                    RowLayout { Layout.fillWidth: true; spacing: 10; C.Copy { text: modelData.name || root.t("accounts"); size: 16; font.weight: Font.DemiBold; Layout.fillWidth: true } C.Badge { label: root.accountStatus(modelData).label; kind: root.accountStatus(modelData).kind }
                                        C.Action { id: moreButton; objectName: "accountMenu"+modelData.binding_id; variant: "icon"; iconName: "more"; text: root.t("details"); onClicked: actionsMenu.open() }
                                        C.AccountMenu { id: actionsMenu; objectName: "actionsMenu"+modelData.binding_id; parent: moreButton; y: moreButton.height+4; x: moreButton.width-width; bindingId: modelData.binding_id; onDetailsRequested: root.select(modelData.binding_id) }
                                    }
                                    C.Copy { text: root.accountLine(modelData); secondary: true; Layout.fillWidth: true }
                                    C.Copy { text: root.t("lastSync")+": "+ui.time(modelData.last_observed_at); secondary: true; Layout.fillWidth: true }
                                    C.Copy { visible: !!modelData.error; text: ui.explain(modelData.error || ""); color: ui.colors.warning; Layout.fillWidth: true }
                                    C.Copy { visible: modelData.review>0; text: root.t("needs_review"); color: ui.colors.warning; Layout.fillWidth: true }
                                    C.Action { text: root.t("details"); onClicked: root.select(modelData.binding_id) }
                                }
                            }
                        }
                        // Accounts
                        ColumnLayout {
                            spacing: 16
                            RowLayout { Layout.fillWidth: true; spacing: 16; C.Copy { text: root.t("accounts"); size: 25; font.weight: Font.DemiBold; Layout.fillWidth: true } C.Action { iconName: "plus"; text: root.t("add"); primary: true; onClicked: root.screenIndex=3 } }
                            C.Card { visible: ui.summary.accounts===0; Layout.fillWidth: true; C.Copy { text: root.t("noAccounts"); size: 18; font.weight: Font.DemiBold; Layout.fillWidth: true } C.Copy { text: root.t("noAccountsHint"); secondary: true; Layout.fillWidth: true } }
                            Repeater { model: ui.state.accounts || []
                                C.Card { required property var modelData; Layout.fillWidth: true
                                    RowLayout { Layout.fillWidth: true; spacing: 10; C.Copy { text: modelData.name || root.t("accounts"); font.weight: Font.DemiBold; size: 18; Layout.fillWidth: true } C.Badge { label: root.accountStatus(modelData).label; kind: root.accountStatus(modelData).kind }
                                        C.Action { id: listMoreButton; objectName: "listAccountMenu"+modelData.binding_id; variant: "icon"; iconName: "more"; text: root.t("details"); onClicked: listActionsMenu.open() }
                                        C.AccountMenu { id: listActionsMenu; objectName: "listActionsMenu"+modelData.binding_id; parent: listMoreButton; y: listMoreButton.height+4; x: listMoreButton.width-width; bindingId: modelData.binding_id; onDetailsRequested: root.select(modelData.binding_id) }
                                    }
                                    C.Copy { text: root.accountLine(modelData); secondary: true; Layout.fillWidth: true }
                                    C.Copy { text: root.t("lastSync")+": "+ui.time(modelData.last_observed_at); secondary: true; Layout.fillWidth: true }
                                    C.Copy { visible: modelData.role==="standby"; text: root.t("standbyHelp"); secondary: true; Layout.fillWidth: true }
                                    C.Copy { visible: !!modelData.error; text: ui.explain(modelData.error || ""); color: ui.colors.warning; Layout.fillWidth: true }
                                    C.Copy { visible: modelData.review>0; text: root.t("needs_review"); color: ui.colors.warning; Layout.fillWidth: true }
                                    Flow { spacing: 8; Layout.fillWidth: true
                                        C.Action { text: root.t("details"); onClicked: root.select(modelData.binding_id) }
                                        C.Action { visible: modelData.stage!=="paused"; text: root.t("pause"); onClicked: ui.accountAction(modelData.binding_id,"pause") }
                                        C.Action { visible: modelData.stage==="paused"; text: root.t("resume"); primary: true; onClicked: ui.accountAction(modelData.binding_id,"resume") }
                                    }
                                }
                            }
                        }
                        // Add account
                        ColumnLayout {
                            spacing: 18
                            C.Copy { text: root.t("stepLabel")+" · 2 / 3"; color: ui.colors.accent; Layout.fillWidth: true }
                            C.Copy { text: root.t("add"); size: 25; font.weight: Font.DemiBold; Layout.fillWidth: true }
                            C.Copy { text: root.t("identityHint"); secondary: true; Layout.fillWidth: true }
                            C.Card { Layout.fillWidth: true
                                Flow { Layout.fillWidth: true; spacing: 10
                                    C.Action { objectName: "discoverButton"; loading: ui.command.action==="discover" && ["submitted","pending"].includes(ui.command.phase); iconName: "sync"; text: root.t("discover"); primary: true; onClicked: ui.discover() }
                                    C.Action { objectName: "pickTerminalButton"; text: root.t("pickTerminal"); onClicked: ui.pickTerminal() }
                                }
                                C.Copy { objectName: "noTerminalsHint"; visible: (ui.state.terminals || []).length===0; text: root.t("noTerminalsHint"); secondary: true; Layout.fillWidth: true }
                                C.Choice { id: terminalChoice; objectName: "terminalChoice"; label: root.t("chooseTerminal"); Layout.fillWidth: true; model: (ui.state.terminals || []).map(t => ({value:t.key,label:t.label+" · "+root.t(t.running ? "running" : "stopped")})) }
                                Repeater { model: (ui.state.terminals || []).length>1 ? (ui.state.terminals || []).filter(t => t.key===terminalChoice.selectedValue) : []
                                    C.Copy { required property var modelData; text: modelData.path || root.t("pathUnavailable"); secondary: true; size: 12; Layout.fillWidth: true }
                                }
                                C.Action { objectName: "previewButton"; enabled: terminalChoice.selectedValue!==""; text: root.t("preview"); onClicked: ui.preview(terminalChoice.selectedValue) }
                                Repeater { model: (ui.state.terminals || []).filter(t => t.key===terminalChoice.selectedValue && t.broker)
                                    C.Copy { required property var modelData; text: root.value(modelData.broker)+" · "+root.value(modelData.server)+" · •••• "+root.value(modelData.login_suffix); color: ui.colors.accent; Layout.fillWidth: true }
                                }
                            }
                            C.Card { Layout.fillWidth: true
                                C.Copy { objectName: "howAdd"; text: root.t("howAdd"); secondary: true; Layout.fillWidth: true }
                                C.Copy { objectName: "registrationError"; visible: !!(ui.state.registration || {}).error; text: String((ui.state.registration || {}).error || "").includes("403") ? root.t("registrationDenied") : ui.explain((ui.state.registration || {}).error || ""); color: ui.colors.warning; Layout.fillWidth: true }
                                C.Copy { visible: ((ui.state.registration || {}).state || "idle")!=="idle"; text: root.t((ui.state.registration || {}).state || "idle"); color: ui.colors.accent; font.weight: Font.DemiBold; Layout.fillWidth: true }
                                GridLayout { Layout.fillWidth: true; columns: root.compact ? 1 : 2; columnSpacing: 16; rowSpacing: 16
                                    C.Field { id: accountName; objectName: "accountName"; label: root.t("name"); Layout.fillWidth: true; Layout.preferredWidth: 1 }
                                    C.FirmField { id: firm; objectName: "firm"; label: root.t("firm"); options: ui.propFirms; Layout.fillWidth: true; Layout.preferredWidth: 1 }
                                    C.Choice { id: category; objectName: "category"; label: root.t("category"); Layout.fillWidth: true; Layout.preferredWidth: 1; model: ["personal","prop_firm","demo"].map(v => ({value:v,label:root.t(v)})) }
                                    C.Field { id: baseline; objectName: "baseline"; label: root.t("baseline")+(root.previewedTerminal && root.previewedTerminal.currency ? " ("+root.previewedTerminal.currency+")" : ""); Layout.fillWidth: true; Layout.preferredWidth: 1 }
                                }
                                C.Copy { text: root.t(root.previewedTerminal && root.previewedTerminal.starting_balance ? "baselineFound" : "baselineHint"); secondary: true; Layout.fillWidth: true }
                                C.Copy { objectName: "categoryHint"; visible: !!root.previewedTerminal && category.selectedValue===""; text: root.t("categoryHint"); color: ui.colors.warning; Layout.fillWidth: true }
                                C.Copy { visible: (ui.state.device || {}).state!=="paired"; text: root.t("pairBeforeRegister"); color: ui.colors.warning; Layout.fillWidth: true }
                                C.Action { objectName: "accountAdvancedToggle"; text: root.t(root.accountAdvanced ? "hideAdvanced" : "showAdvanced"); onClicked: root.accountAdvanced=!root.accountAdvanced }
                                GridLayout { visible: root.accountAdvanced; Layout.fillWidth: true; columns: root.compact ? 1 : 2; columnSpacing: 16; rowSpacing: 16
                                    C.Field { id: timezone; objectName: "timezone"; label: root.t("timezone"); placeholderText: "Europe/Kyiv"; Layout.fillWidth: true; Layout.preferredWidth: 1 }
                                }
                                C.Copy { visible: root.accountAdvanced; text: root.t("chartsHint"); secondary: true; Layout.fillWidth: true }
                                C.Action { objectName: "registerButton"; text: root.t("register"); primary: true; enabled: (ui.state.device || {}).state==="paired" && category.selectedValue!=="" && (ui.state.terminals || []).some(t => t.key===terminalChoice.selectedValue && t.broker); onClicked: {
                                    let metadata={name:accountName.text,firm:firm.text,category:category.selectedValue,journal_mode:"automatic",timezone:timezone.text}
                                    if (baseline.text!=="") metadata.initial_balance=baseline.text
                                    if (!metadata.name || !metadata.firm || !metadata.category || !metadata.timezone) metadata={}
                                    ui.registerAccount(terminalChoice.selectedValue,metadata)
                                } }
                            }
                        }
                        // Details
                        ColumnLayout {
                            spacing: 18
                            Flow { Layout.fillWidth: true; spacing: 8
                                C.Action { objectName: "backToOverview"; variant: "tertiary"; iconName: "chevron"; iconRotation: 90; text: root.t("dashboard"); onClicked: root.screenIndex=1 }
                                C.Action { visible: ui.selected.stage==="awaiting_handover"; text: root.t("continue"); primary: true; onClicked: { migrationChoice.selectedValue=ui.selected.binding_id; migrationChoice.restore(); root.screenIndex=5 } }
                            }
                            C.Copy { visible: root.onboarding || ui.selected.stage==="awaiting_handover"; text: root.t("stepLabel")+" · 3 / 3 · "+root.t("readiness"); color: ui.colors.accent; Layout.fillWidth: true }
                            C.Copy { text: root.t("details"); size: 25; font.weight: Font.DemiBold; Layout.fillWidth: true }
                            C.Choice { id: detailChoice; objectName: "detailChoice"; visible: ui.summary.accounts>1; label: root.t("chooseAccount"); Layout.fillWidth: true; model: root.accountOptions(); onSelectedValueChanged: if (selectedValue) ui.selectAccount(selectedValue) }
                            C.Card { Layout.fillWidth: true; visible: !!ui.selected.binding_id; padding: 24
                                RowLayout { Layout.fillWidth: true; spacing: 10; C.Copy { text: ui.selected.name || root.t("accounts"); size: 20; font.weight: Font.DemiBold; Layout.fillWidth: true } C.Badge { label: root.accountStatus(ui.selected).label; kind: root.accountStatus(ui.selected).kind } }
                                C.Copy { visible: !!ui.selected.error; text: ui.explain(ui.selected.error || ""); color: ui.colors.warning; Layout.fillWidth: true }
                                C.Copy { visible: ui.selected.review>0; text: root.t("needs_review"); color: ui.colors.warning; Layout.fillWidth: true }
                                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: ui.colors.grid; Accessible.ignored: true }
                                GridLayout { Layout.fillWidth: true; columns: root.compact ? 1 : 2; columnSpacing: 32; rowSpacing: 18
                                    C.Fact { objectName: "factSync"; label: root.t("lastSync"); value: ui.time(ui.selected.last_observed_at); Layout.fillWidth: true; Layout.preferredWidth: 1 }
                                    C.Fact { label: root.t("mt5Account"); value: ui.selected.login_suffix ? "•••• "+ui.selected.login_suffix : root.t("notAvailable"); Layout.fillWidth: true; Layout.preferredWidth: 1 }
                                    C.Fact { label: root.t("broker"); value: root.value(ui.selected.broker); Layout.fillWidth: true; Layout.preferredWidth: 1 }
                                    C.Fact { label: root.t("server"); value: root.value(ui.selected.server); Layout.fillWidth: true; Layout.preferredWidth: 1 }
                                }
                                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: ui.colors.grid; Accessible.ignored: true }
                                Flow { Layout.fillWidth: true; spacing: 10
                                    C.Action { objectName: "pauseButton"; visible: ui.selected.stage!=="paused"; text: root.t("pause"); onClicked: ui.accountAction(ui.selected.binding_id,"pause") }
                                    C.Action { objectName: "resumeButton"; visible: ui.selected.stage==="paused"; primary: true; text: root.t("resume"); onClicked: ui.accountAction(ui.selected.binding_id,"resume") }
                                    C.Action { iconName: "sync"; text: root.t("refresh"); onClicked: ui.accountAction(ui.selected.binding_id,"sync") }
                                    C.Action { objectName: "deleteOnSite"; variant: "destructive"; iconName: "external"; text: root.t("deleteOnSite"); onClicked: ui.openAccountPage(ui.selected.account_id) }
                                }
                            }
                            C.Card { Layout.fillWidth: true; visible: (ui.selected.force || []).length>0
                                C.Copy { text: root.t("force"); size: 16; font.weight: Font.DemiBold; Layout.fillWidth: true }
                                C.Copy { text: root.t("forceHint"); secondary: true; Layout.fillWidth: true }
                                Repeater { model: ui.selected.force || []; C.Copy { required property var modelData; text: root.t(modelData.state); Layout.fillWidth: true } }
                            }
                        }
                        // Migration
                        ColumnLayout {
                            spacing: 18
                            C.Copy { text: root.t("migration"); size: 25; font.weight: Font.DemiBold; Layout.fillWidth: true }
                            C.Copy { text: root.t("migrationHint"); secondary: true; Layout.fillWidth: true }
                            C.Choice { id: migrationChoice; objectName: "migrationChoice"; onSelectedValueChanged: drainConfirmation.checked=false; label: root.t("chooseAccount"); Layout.fillWidth: true; model: root.accountOptions() }
                            C.Card { Layout.fillWidth: true
                                C.Copy { text: "01  /  "+root.t("inspect"); size: 18; font.weight: Font.DemiBold; Layout.fillWidth: true }
                                C.Action { objectName: "inspectButton"; text: root.t("inspect"); enabled: migrationChoice.selectedValue!==""; onClicked: ui.migrate(migrationChoice.selectedValue,false,false) }
                                C.Copy { text: root.t((ui.state.migration || {}).stage || "idle"); color: ui.colors.warning; Layout.fillWidth: true }
                                Repeater { model: (ui.state.migration || {}).queues || []; C.Copy { required property var modelData; text: modelData.protocol+" · "+root.t("pending")+": "+modelData.pending+" · "+root.t("processing")+": "+modelData.processing; Layout.fillWidth: true } }
                            }
                            C.Card { Layout.fillWidth: true
                                C.Copy { text: "02  /  "+root.t("drain"); size: 18; font.weight: Font.DemiBold; Layout.fillWidth: true }
                                C.Check { id: drainConfirmation; objectName: "drainConfirmation"; label: root.t("confirmDrain"); Layout.fillWidth: true }
                                C.Action { objectName: "drainButton"; text: root.t("drain"); enabled: drainConfirmation.checked && migrationChoice.selectedValue!==""; onClicked: ui.migrate(migrationChoice.selectedValue,true,true) }
                            }
                            C.Card { Layout.fillWidth: true
                                C.Copy { text: "03  /  "+root.t("awaiting_browser_confirmation"); size: 18; font.weight: Font.DemiBold; Layout.fillWidth: true }
                                C.Copy { text: root.t("migrationHint"); secondary: true; Layout.fillWidth: true }
                                Flow { Layout.fillWidth: true; spacing: 10; C.Action { text: root.t("browser"); onClicked: ui.openBrowser() } C.Action { objectName: "enableButton"; text: root.t("enable"); enabled: migrationChoice.selectedValue!==""; onClicked: ui.accountAction(migrationChoice.selectedValue,"activate") } }
                            }
                        }
                        // Settings
                        ColumnLayout {
                            spacing: 18
                            C.Copy { text: root.t("settings"); size: 25; font.weight: Font.DemiBold; Layout.fillWidth: true }
                            C.Card { Layout.fillWidth: true
                                C.SectionHead { iconName: "settings"; title: root.t("appearance"); subtitle: root.t("appearanceHint"); Layout.fillWidth: true }
                                C.Copy { text: root.t("language"); secondary: true; size: 13; Layout.fillWidth: true }
                                RowLayout { Layout.fillWidth: true; spacing: 10; C.Action { objectName: "languageEn"; text: "English"; Layout.preferredWidth: 132; primary: ui.preferences.locale==="en"; onClicked: ui.preference("locale","en") } C.Action { objectName: "languageUk"; text: "Українська"; Layout.preferredWidth: 132; primary: ui.preferences.locale==="uk"; onClicked: ui.preference("locale","uk") } Item { Layout.fillWidth: true } }
                                C.Copy { text: root.t("palette"); secondary: true; size: 13; Layout.fillWidth: true }
                                GridLayout { objectName: "paletteGrid"; Layout.fillWidth: true; columns: root.width>=1400 ? 6 : 3; columnSpacing: 10; rowSpacing: 10
                                    Repeater { model: ui.paletteCatalog; C.PaletteCard { required property var modelData; option: modelData; objectName: "palette"+modelData.id; Layout.fillWidth: true; Layout.preferredWidth: 1; selected: ui.preferences.palette===modelData.id; schemeLabel: root.t(modelData.scheme); selectedLabel: root.t("selected"); onClicked: ui.preference("palette",modelData.id) } }
                                }
                                C.Copy { text: root.t("behaviour"); secondary: true; size: 13; Layout.fillWidth: true }
                                C.Toggle { objectName: "reducedMotion"; label: root.t("motion"); checked: ui.reducedMotion; onClicked: { let desired=checked; checked=Qt.binding(() => ui.reducedMotion); ui.preference("reduced_motion",desired) } Layout.fillWidth: true }
                                C.Toggle { objectName: "closeToTray"; label: root.t("closeTray"); checked: ui.preferences.close_to_tray; onClicked: { let desired=checked; checked=Qt.binding(() => ui.preferences.close_to_tray); ui.preference("close_to_tray",desired) } Layout.fillWidth: true }
                                C.Toggle { label: root.t("notifications"); checked: ui.preferences.notifications; onClicked: { let desired=checked; checked=Qt.binding(() => ui.preferences.notifications); ui.preference("notifications",desired) } Layout.fillWidth: true }
                                C.Toggle { objectName: "autostart"; label: root.t("autostart"); checked: ui.preferences.autostart; enabled: ui.installedWindows; onClicked: { let desired=checked; checked=Qt.binding(() => ui.preferences.autostart); ui.preference("autostart",desired) } Layout.fillWidth: true }
                                C.Copy { visible: !ui.installedWindows; text: root.t("installedOnly"); secondary: true; Layout.fillWidth: true }
                            }
                            C.Card { objectName: "updatesCard"; Layout.fillWidth: true
                                C.SectionHead { iconName: "sync"; title: root.t("updates"); subtitle: root.t("installedVersion")+": "+ui.build.version; Layout.fillWidth: true }
                                C.Copy { objectName: "updateStatus"; text: root.t("update_"+ui.updateInfo.state)+(ui.updateInfo.state==="available" ? " "+ui.updateInfo.version : ""); color: ui.updateInfo.state==="error" ? ui.colors.warning : ui.colors.text; Layout.fillWidth: true }
                                C.Copy { visible: ["available","ready"].includes(ui.updateInfo.state); text: root.t("updateUnsigned"); secondary: true; Layout.fillWidth: true }
                                Flow { Layout.fillWidth: true; spacing: 10
                                    C.Action { objectName: "checkUpdates"; visible: ui.updateInfo.state!=="ready"; loading: ui.updateInfo.state==="checking"; enabled: ui.updateInfo.state!=="downloading"; text: root.t("checkUpdates"); onClicked: ui.checkUpdate() }
                                    C.Action { objectName: "downloadUpdate"; visible: ["available","downloading"].includes(ui.updateInfo.state) && ui.installedWindows; loading: ui.updateInfo.state==="downloading"; primary: true; text: root.t("downloadUpdate"); onClicked: ui.downloadUpdate() }
                                    C.Action { objectName: "installUpdate"; visible: ui.updateInfo.state==="ready"; primary: true; text: root.t("installUpdate"); onClicked: ui.installUpdate() }
                                }
                            }
                            C.Card { objectName: "deviceCard"; Layout.fillWidth: true
                                C.SectionHead { iconName: "link"; title: root.t("device"); subtitle: root.t((ui.state.device || {}).state || "disconnected"); Layout.fillWidth: true }
                                C.Copy { text: root.t("deviceHint"); secondary: true; Layout.fillWidth: true }
                                Flow { Layout.fillWidth: true; spacing: 10
                                    C.Action { text: root.t("reviewAccess"); iconName: "external"; onClicked: ui.openBrowser() }
                                    C.Action { objectName: "repairButton"; text: root.t("repair"); onClicked: { root.screenIndex=0; root.repairing=true } }
                                    C.Action { visible: (ui.state.accounts || []).some(a => a.stage==="awaiting_handover" || a.stage==="continuity_review"); text: root.t("migration"); iconName: "migration"; onClicked: root.screenIndex=5 }
                                    C.Action { text: root.t("disconnect"); variant: "destructive"; onClicked: root.confirm("disconnect") }
                                }
                            }
                            C.Card { Layout.fillWidth: true
                                C.SectionHead { iconName: "support"; title: root.t("support"); subtitle: root.t("supportHint"); Layout.fillWidth: true }
                                C.Action { objectName: "openSupport"; text: root.t("advanced"); onClicked: root.screenIndex=7 }
                            }
                        }
                        // Diagnostics
                        ColumnLayout {
                            spacing: 18
                            C.Copy { text: root.t("support"); size: 25; font.weight: Font.DemiBold; Layout.fillWidth: true }
                            C.Card { Layout.fillWidth: true; padding: 24
                                RowLayout { Layout.fillWidth: true; spacing: 14
                                    Rectangle { Layout.preferredWidth: 12; Layout.preferredHeight: 12; Layout.alignment: Qt.AlignVCenter; radius: 6; color: ui.command.error || ui.state.error ? ui.colors.warning : ui.colors.positive; Accessible.ignored: true }
                                    C.Copy { objectName: "supportStatus"; text: ui.command.error || ui.state.error ? ui.explain(ui.command.error || ui.state.error) : root.t("noErrors"); size: 16; font.weight: Font.DemiBold; Layout.fillWidth: true }
                                }
                                C.Copy { text: root.t("installedVersion")+": "+ui.build.version; secondary: true; Layout.fillWidth: true }
                            }
                            C.Card { Layout.fillWidth: true
                                C.Copy { text: root.t("helpTitle"); size: 16; font.weight: Font.DemiBold; Layout.fillWidth: true }
                                Repeater { model: ["helpStepTerminal","helpStepNetwork","helpStepAccess"]
                                    RowLayout { required property string modelData; required property int index; Layout.fillWidth: true; spacing: 12
                                        Rectangle { Layout.preferredWidth: 24; Layout.preferredHeight: 24; Layout.alignment: Qt.AlignTop; radius: 12; color: ui.colors.accentSoft; Accessible.ignored: true; Text { anchors.centerIn: parent; textFormat: Text.PlainText; text: String(parent.parent.index+1); font.pixelSize: 12; font.weight: Font.DemiBold; color: ui.colors.text } }
                                        C.Copy { text: root.t(modelData); Layout.fillWidth: true; Layout.topMargin: 2 }
                                    }
                                }
                                C.Copy { text: root.t("help"); secondary: true; Layout.fillWidth: true }
                            }
                            C.Card { Layout.fillWidth: true
                                C.Copy { text: root.t("exportTitle"); size: 16; font.weight: Font.DemiBold; Layout.fillWidth: true }
                                C.Copy { text: root.t("exportHint"); secondary: true; Layout.fillWidth: true }
                                Flow { Layout.fillWidth: true; spacing: 10
                                    C.Action { objectName: "exportButton"; iconName: "support"; text: root.t("export"); primary: true; onClicked: ui.exportDiagnostics() }
                                    C.Action { objectName: "supportDetailsToggle"; variant: "tertiary"; iconName: "chevron"; iconRotation: root.supportDetails ? 180 : 0; text: root.t("technicalDetails"); onClicked: root.supportDetails=!root.supportDetails }
                                }
                                C.Copy { visible: root.supportDetails; text: ui.build.version+" · Qt "+ui.build.qt+" · "+String(ui.build.commit); secondary: true; size: 12; Layout.fillWidth: true }
                                C.Copy { visible: root.supportDetails; text: root.t("stage")+": "+root.value((ui.state.diagnostic || {}).stage)+" · "+root.t("correlation")+": "+root.value((ui.state.diagnostic || {}).id || ui.command.id); secondary: true; size: 12; Layout.fillWidth: true }
                            }
                        }
                        // Operational activity, observed locally; never an invented financial timeline.
                        ColumnLayout {
                            spacing: 16
                            C.Copy { text: root.t("activity"); size: 25; font.weight: Font.DemiBold; Layout.fillWidth: true }
                            C.Copy { text: root.t("activityHint"); secondary: true; Layout.fillWidth: true }
                            C.Card { Layout.fillWidth: true; visible: ui.activity.length===0; padding: 24
                                C.Copy { text: root.t("noActivity"); size: 16; font.weight: Font.DemiBold; Layout.fillWidth: true }
                                C.Copy { text: root.t("noActivityHint"); secondary: true; Layout.fillWidth: true }
                            }
                            C.Card { objectName: "activityCard"; Layout.fillWidth: true; visible: ui.activity.length>0
                                Repeater { model: ui.activity
                                    ColumnLayout { required property var modelData; required property int index; Layout.fillWidth: true; spacing: 12
                                        Rectangle { visible: index>0; Layout.fillWidth: true; Layout.preferredHeight: 1; color: ui.colors.grid; Accessible.ignored: true }
                                        RowLayout { Layout.fillWidth: true; spacing: 12
                                            C.Copy { text: root.activityLabel(modelData); Layout.fillWidth: true }
                                            C.Copy { text: ui.time(modelData.observed_at); secondary: true; size: 13 }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    Item { Layout.preferredHeight: 28 }
                }
            }
        }
    }
    Dialog {
        id: confirmation
        objectName: "confirmationDialog"
        anchors.centerIn: parent
        modal: true
        focus: true
        onOpened: confirmCancelButton.forceActiveFocus()
        width: Math.min(480,root.width-40)
        padding: 24
        closePolicy: Popup.CloseOnEscape
        background: Rectangle { radius: ui.tokens["radius-dialog"]; color: ui.colors.elevated; border.color: ui.colors.line }
        contentItem: ColumnLayout { spacing: 18
            C.Copy { text: root.t(root.confirmKind==="repair" ? "repair" : root.confirmKind==="disconnect" ? "disconnect" : "quit"); size: 21; font.weight: Font.DemiBold; Layout.fillWidth: true }
            C.Copy { text: root.t(root.confirmKind==="repair" ? "repairWarning" : root.confirmKind==="disconnect" ? "disconnectWarning" : "quitHint"); secondary: true; Layout.fillWidth: true }
            Flow { Layout.fillWidth: true; spacing: 10
                C.Action { id: confirmCancelButton; objectName: "confirmCancel"; text: root.t("cancel"); onClicked: confirmation.close() }
                C.Action { objectName: "confirmAccept"; text: root.t("confirm"); primary: true; onClicked: { confirmation.close(); if(root.confirmKind==="quit") { if(!ui.synthetic) ui.saveWindow(Math.min(2560,root.width),Math.min(1600,root.height),root.visibility===Window.Maximized); ui.stopRequested() } else if(root.confirmKind==="disconnect") ui.disconnect(); else { if(ui.pair(pairCode.text,deviceName.text,true,true)) { pairCode.text=""; root.repairing=false } } } }
            }
        }
        Overlay.modal: Rectangle { color: ui.colors.scrim }
    }
}
