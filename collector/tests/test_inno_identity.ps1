$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot '../build/preflight.ps1')
$Directory=[IO.Path]::GetFullPath((Join-Path ([IO.Path]::GetTempPath()) 'Inno Setup 6'))
$Compiler=Join-Path $Directory 'ISCC.exe'
$Banner="Inno Setup 6 Command-Line Compiler`nCompiler engine version: Inno Setup 6.4.3`nCopyright (C)"
$Base=@{DisplayName='Inno Setup version 6.4.3';DisplayVersion='6.4.3';InstallLocation=$Directory}
$Count=0
function Expect-Accept($Entries, $Text=$Banner) {
    $Result=Test-CollectorInnoIdentity $Compiler '6.4.3' $Entries $Text
    if ($Result.version -cne '6.4.3') {throw 'Wrong compiler accepted'}
    $script:Count++
}
function Expect-Reject($Entries, $Text=$Banner) {
    $Rejected=$false
    try {Test-CollectorInnoIdentity $Compiler '6.4.3' $Entries $Text | Out-Null} catch {$Rejected=$true}
    if (-not $Rejected) {throw 'Invalid compiler identity accepted'}
    $script:Count++
}
Expect-Accept @([pscustomobject]$Base)
Expect-Accept @([pscustomobject]$Base,[pscustomobject]$Base) # duplicate machine registry views
Expect-Accept @([pscustomobject]@{DisplayVersion='6.4.3';'Inno Setup: App Path'=$Directory})
Expect-Accept @([pscustomobject]@{DisplayVersion='6.4.3';InstallLocation=('"'+$Directory+[IO.Path]::DirectorySeparatorChar+'"')})
Expect-Accept @([pscustomobject]@{DisplayVersion='6.4.3';UninstallString=('"'+(Join-Path $Directory 'unins000.exe')+'" /SILENT')})
Expect-Accept @([pscustomobject]$Base,[pscustomobject]@{DisplayVersion='9.9.9';InstallLocation=(Join-Path $Directory 'other-user')})
Expect-Reject @()
Expect-Reject @([pscustomobject]@{DisplayVersion='6.4.2';InstallLocation=$Directory})
Expect-Reject @([pscustomobject]$Base,[pscustomobject]@{DisplayVersion='6.4.4';InstallLocation=$Directory})
Expect-Reject @([pscustomobject]@{InstallLocation=$Directory})
Expect-Reject @([pscustomobject]@{DisplayVersion='6.4.3';InstallLocation=(Join-Path $Directory 'other-user')})
Expect-Reject @([pscustomobject]$Base) 'Compiler engine version: Inno Setup 6.4.4'
Expect-Reject @([pscustomobject]$Base) 'FileVersion 6.4.3'
Expect-Reject @([pscustomobject]$Base) ($Banner+"`nCompiler engine version: Inno Setup 6.4.3")
Expect-Reject @([pscustomobject]$Base) ('x'*16385)
Expect-Reject @([pscustomobject]$Base) "Inno Setup 6 Command-Line Compiler`nUsage: iscc [options] scriptfile.iss"
$Probe=$Banner+"`nError on line 1 in <stdin>: #error: TANREN_VERSION_PROBE_ABORT`nCompile aborted."
$Checked=Test-CollectorInnoProbeResult 2 $Probe
Expect-Accept @([pscustomobject]$Base) $Checked
$NativeProbe=$Banner+"`r`nError on line 1 in <stdin>: TANREN_VERSION_PROBE_ABORT.`r`nCompile aborted."
Expect-Accept @([pscustomobject]$Base) (Test-CollectorInnoProbeResult 2 $NativeProbe)
Expect-Reject @([pscustomobject]$Base) ($Checked.Replace('Compiler engine version: Inno Setup 6.4.3','Compiler engine version: Inno Setup 6.4.4'))
foreach($Case in @(
    @{Code=0;Text=$Probe},
    @{Code=1;Text=$Probe},
    @{Code=2;Text=$Banner},
    @{Code=2;Text=($Probe.Replace('TANREN_VERSION_PROBE_ABORT','OTHER_ERROR'))},
    @{Code=2;Text=($Probe.Replace('TANREN_VERSION_PROBE_ABORT','TANREN_VERSION_PROBE_ABORT_EXTRA'))},
    @{Code=2;Text=('x'*16385)}
)) {
    $Rejected=$false
    try { Test-CollectorInnoProbeResult $Case.Code $Case.Text | Out-Null } catch { $Rejected=$true }
    if (-not $Rejected) { throw 'Invalid compiler probe accepted' }
    $Count++
}
"PASS: $Count portable Inno identity cases; real Windows registry/compiler still requires native run"
