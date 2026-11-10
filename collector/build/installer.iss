#define Version "0.7.0"
#ifdef EngineeringBuild
#define AppIdentity "{{C7E48B92-68D5-4C31-9177-503BA7F62DB8}"
#define DisplayName "Tanren Collector Engineering"
#define GroupName "Tanren Engineering"
#define StartupValue "TanrenCollectorEngineering"
#define MutexName "Local\TanrenCollector.Engineering.Desktop"
#define SetupName "TanrenCollectorEngineeringSetup"
#else
#define AppIdentity "{{A40F8247-D97C-4BB5-A778-452509E35053}"
#define DisplayName "Tanren Collector"
#define GroupName "Tanren"
#define StartupValue "TanrenCollector"
#define MutexName "Local\TanrenCollector.Desktop"
#define SetupName "TanrenCollectorSetup"
#endif
#ifndef MinimumWindowsVersion
#error Supply the reviewed candidate minimum Windows version
#endif
#ifndef DistributionRoot
#define DistributionRoot "..\..\dist\TanrenCollector"
#endif
[Setup]
AppId={#AppIdentity}
AppName={#DisplayName}
AppVersion={#Version}
VersionInfoVersion=0.7.0.0
AppVerName={#DisplayName} {#Version}
DefaultDirName={localappdata}\Programs\{#DisplayName}
DefaultGroupName={#GroupName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion={#MinimumWindowsVersion}
OutputDir=..\..\dist
OutputBaseFilename={#SetupName}
SetupIconFile=collector.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
#ifdef TrustedBuild
SignedUninstaller=yes
SignTool=tanren
#endif
#ifdef EngineeringBuild
CloseApplications=no
DisableDirPage=yes
UsePreviousAppDir=no
UsePreviousTasks=no
#else
CloseApplications=yes
#endif
RestartApplications=no
AppMutex={#MutexName}
UninstallDisplayIcon={app}\TanrenCollector.exe
DisableProgramGroupPage=yes
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "ukrainian"; MessagesFile: "compiler:Languages\Ukrainian.isl"
[CustomMessages]
english.DesktopIcon=Create a desktop shortcut
ukrainian.DesktopIcon=Створити ярлик на робочому столі
english.Startup=Start Collector when I sign in to Windows
ukrainian.Startup=Запускати Collector при вході у Windows
english.OpenCollector=Open {#DisplayName}
ukrainian.OpenCollector=Відкрити {#DisplayName}
[Tasks]
Name: desktopicon; Description: "{cm:DesktopIcon}"; Flags: unchecked
#ifdef EngineeringBuild
Name: startup; Description: "{cm:Startup}"; Flags: unchecked
#else
Name: startup; Description: "{cm:Startup}"; Flags: checkedonce
#endif
[Files]
Source: "{#DistributionRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{autoprograms}\{#DisplayName}"; Filename: "{app}\TanrenCollector.exe"
Name: "{autodesktop}\{#DisplayName}"; Filename: "{app}\TanrenCollector.exe"; Tasks: desktopicon
[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#StartupValue}"; ValueData: """{app}\TanrenCollector.exe"" --background"; Tasks: startup; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "{#StartupValue}"; Tasks: not startup; Flags: deletevalue
#ifndef EngineeringBuild
[Run]
Filename: "{app}\TanrenCollector.exe"; Description: "{cm:OpenCollector}"; Flags: nowait postinstall skipifsilent
#endif
; Deliberately no [UninstallDelete]: protected queues/credentials are retained for reviewed recovery.
#ifdef EngineeringBuild
[Code]
function EngineeringFileAttributes(FileName: String): LongWord;
  external 'GetFileAttributesW@kernel32.dll stdcall';

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Directory: String;
  Attributes: LongWord;
begin
  Result := '';
  if CompareText(RemoveBackslashUnlessRoot(ExpandConstant('{app}')),
    RemoveBackslashUnlessRoot(ExpandConstant('{localappdata}\Programs\Tanren Collector Engineering'))) <> 0 then
    Result := 'Engineering installation requires its dedicated default directory.';
  Directory := ExpandConstant('{app}');
  while Directory <> '' do begin
    Attributes := EngineeringFileAttributes(Directory);
    if (Attributes <> $FFFFFFFF) and ((Attributes and $400) <> 0) then begin
      Result := 'Engineering installation does not permit directory reparse points.';
      Exit;
    end;
    if ExtractFileDir(Directory) = Directory then Break;
    Directory := ExtractFileDir(Directory);
  end;
end;
#endif
