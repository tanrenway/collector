param([Parameter(Mandatory)][string]$SourcePython,
      [Parameter(Mandatory)][string]$FrozenExe,
      [Parameter(Mandatory)][string]$ExpectedSourceSha,
      [Parameter(Mandatory)][string]$OutputDirectory,
      [string]$TerminalPath, [switch]$AcknowledgeTestTerminal)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if ($env:OS -ne 'Windows_NT') { throw 'Native Windows x64 comparison required' }
$Repo=(Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$Head=git -C $Repo rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw 'Source commit unavailable' }
$Status=git -C $Repo status --porcelain
if ($LASTEXITCODE -ne 0 -or $Status -or $ExpectedSourceSha -cnotmatch '^[0-9a-f]{40}$' -or $Head -cne $ExpectedSourceSha) { throw 'Clean reviewed source checkout required' }
if ($TerminalPath -and -not $AcknowledgeTestTerminal) { throw 'Acknowledge the separately authorized read-only test terminal' }
$OutputDirectory=[IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path $OutputDirectory) { throw 'Use a fresh private evidence directory' }
New-Item -ItemType Directory -Path $OutputDirectory | Out-Null
foreach ($Value in @($SourcePython,$FrozenExe,$OutputDirectory,$TerminalPath,$Repo)) {
    if ($Value -match '["\r\n]') { throw 'Use paths without quotes or newline characters' }
}
$Results=@()
Push-Location $Repo
try {
    foreach ($Mode in @('source','frozen')) {
        foreach ($Qt in @($false,$true)) {
            $Name=$Mode+$(if ($Qt) {'-qt'} else {'-plain'})
            $Report=Join-Path $OutputDirectory ($Name+'.json')
            $Arguments=@()
            if ($Mode -eq 'source') { $Arguments+=('"'+(Join-Path $Repo 'collector/desktop_entry.py')+'"') }
            $Arguments+=@('--bridge-probe','--report',('"'+$Report+'"'))
            if ($Qt) { $Arguments+='--qt-parent' }
            if ($TerminalPath) { $Arguments+=@('--terminal',('"'+$TerminalPath+'"'),'--acknowledge-test-terminal') }
            $Executable=if ($Mode -eq 'source') {$SourcePython} else {$FrozenExe}
            $Process=Start-Process -FilePath $Executable -ArgumentList $Arguments -PassThru
            if (-not $Process.WaitForExit(60000)) { $Process.Kill(); throw 'Probe exceeded hard comparison deadline; inspect isolated test process' }
            if (-not (Test-Path $Report)) { throw 'Probe report missing; inspect Code Integrity and bootloader logs privately' }
            $Data=Get-Content $Report -Raw | ConvertFrom-Json
            if ($Mode -eq 'frozen' -and $Data.source_commit -cne $ExpectedSourceSha) { throw 'Frozen binary/source mismatch' }
            $Results+=@{mode=$Name;exit=$Process.ExitCode;status=$Data.status}
        }
    }
    @{source_commit=$ExpectedSourceSha;frozen_sha256=(Get-FileHash $FrozenExe -Algorithm SHA256).Hash.ToLowerInvariant();
      windows_build=[Environment]::OSVersion.VersionString;terminal_test=[bool]$TerminalPath;
      note='Not real trading-history E2E; IPC shutdown/reinitialize does not restart terminal process';results=$Results} |
      ConvertTo-Json -Depth 6 | Set-Content (Join-Path $OutputDirectory 'comparison.json') -Encoding utf8NoBOM
    if (@($Results | Where-Object {$_.status -ne 'PASS' -or $_.exit -ne 0}).Count) { throw 'Bridge comparison contains failures; no automatic compatibility approval' }
} finally { Pop-Location }
