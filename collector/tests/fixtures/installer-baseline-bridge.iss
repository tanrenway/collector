#define Version "0.6.0"
#ifndef MinimumWindowsVersion
#error Supply the reviewed candidate minimum Windows version
#endif
#ifndef DistributionRoot
#define DistributionRoot "..\..\dist\TanrenCollector"
#endif
[Setup]
AppId={{A40F8247-D97C-4BB5-A778-452509E35053}
AppName=tanrenway Bridge
AppVersion={#Version}
VersionInfoVersion=0.6.0.0
AppVerName=tanrenway Bridge {#Version}
DefaultDirName={localappdata}\Programs\Tanren Collector
DefaultGroupName=tanrenway
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion={#MinimumWindowsVersion}
OutputDir=..\..\dist
OutputBaseFilename=TanrenCollectorSetup
SetupIconFile=collector.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
#ifdef TrustedBuild
SignedUninstaller=yes
SignTool=tanren
#endif
CloseApplications=yes
RestartApplications=no
AppMutex=Local\TanrenCollector.Desktop
UninstallDisplayIcon={app}\TanrenCollector.exe
DisableProgramGroupPage=yes
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "ukrainian"; MessagesFile: "compiler:Languages\Ukrainian.isl"
[CustomMessages]
english.DesktopIcon=Create a desktop shortcut
ukrainian.DesktopIcon=Створити ярлик на робочому столі
english.Startup=Start tanrenway Bridge when I sign in to Windows
ukrainian.Startup=Запускати tanrenway Bridge при вході у Windows
english.OpenCollector=Open tanrenway Bridge
ukrainian.OpenCollector=Відкрити tanrenway Bridge
[Tasks]
Name: desktopicon; Description: "{cm:DesktopIcon}"; Flags: unchecked
Name: startup; Description: "{cm:Startup}"; Flags: checkedonce
[Files]
Source: "{#DistributionRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[InstallDelete]
; Shortcuts from before the rename to tanrenway Bridge, so an update leaves no duplicates.
Type: files; Name: "{autoprograms}\Tanren Collector.lnk"
Type: files; Name: "{autodesktop}\Tanren Collector.lnk"
Type: files; Name: "{autoprograms}\Tanren Collector Engineering.lnk"
Type: files; Name: "{autodesktop}\Tanren Collector Engineering.lnk"

[Icons]
Name: "{autoprograms}\tanrenway Bridge"; Filename: "{app}\TanrenCollector.exe"
Name: "{autodesktop}\tanrenway Bridge"; Filename: "{app}\TanrenCollector.exe"; Tasks: desktopicon
[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "TanrenCollector"; ValueData: """{app}\TanrenCollector.exe"" --background"; Tasks: startup; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "TanrenCollector"; Tasks: not startup; Flags: deletevalue
[Run]
Filename: "{app}\TanrenCollector.exe"; Description: "{cm:OpenCollector}"; Flags: nowait postinstall skipifsilent
; Deliberately no [UninstallDelete]: protected queues/credentials are retained for reviewed recovery.
