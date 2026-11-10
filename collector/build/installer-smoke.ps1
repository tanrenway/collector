param([string]$SigningConfig, [string]$OutputDirectory = 'dist')
# Disposable GitHub Windows runner ONLY. Never runs on an existing user's Collector profile.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted' -or $env:OS -ne 'Windows_NT') {
    throw 'Requires disposable GitHub-hosted Windows runner; local install must follow manual E2E'
}
$ProfileRoot = Join-Path $env:LOCALAPPDATA 'TanrenCollector'
$StartupKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
if ((Test-Path $ProfileRoot) -or (Get-ItemProperty -Path $StartupKey -Name TanrenCollector -ErrorAction SilentlyContinue)) {
    throw 'Existing Collector state found; refusing installer smoke'
}
$Target = Join-Path $env:RUNNER_TEMP ('Tanren-install-' + [guid]::NewGuid().ToString('N'))
$Root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory, $Root)
$Setup = (Resolve-Path (Join-Path $OutputDirectory 'TanrenCollectorSetup.exe')).Path
function Run-Checked([string]$Executable, [string[]]$Arguments) {
    $Process = Start-Process -FilePath $Executable -ArgumentList $Arguments -PassThru
    if (-not $Process.WaitForExit(120000)) { throw 'Installer smoke timed out; inspect isolated runner' }
    if ($Process.ExitCode -ne 0) { throw "Installer smoke exit $($Process.ExitCode)" }
}
# No enrollment/network/real profile: --self-test creates its own temporary DPAPI SQLite directory.
$SetupArguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', "/DIR=`"$Target`"", '/TASKS=""')
Run-Checked $Setup $SetupArguments
$Executable = Join-Path $Target 'TanrenCollector.exe'
if (-not (Test-Path $Executable)) { throw 'Installed executable missing' }
if ($SigningConfig) {
    . (Join-Path $PSScriptRoot 'trust.ps1')
    $Config=Read-CollectorSigningConfig $SigningConfig
    foreach ($File in Get-ChildItem $Target -File -Recurse) {
        if (Test-CollectorPE $File.FullName) {
            $Owned=$File.Name -in @('TanrenCollector.exe','unins000.exe')
            Assert-CollectorSignature $File.FullName $Config $Owned | Out-Null
        }
    }
}
Run-Checked $Executable @('--self-test')
$RetentionManifest=Join-Path $env:RUNNER_TEMP ('collector-fixture-'+[guid]::NewGuid().ToString('N')+'.json')
$env:PYTHONPATH='collector'
python collector/build/profile_fixture.py seed $RetentionManifest
if ($LASTEXITCODE -ne 0) { throw 'Synthetic retention seed failed' }
# Same-version reinstall checks file replacement, NOT an upgrade from a distinct historical artifact.
Run-Checked $Setup $SetupArguments
Run-Checked $Executable @('--self-test')
$Uninstall = Join-Path $Target 'unins000.exe'
Run-Checked $Uninstall @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART')
if (Test-Path $Executable) { throw 'Uninstall retained executable' }
if (Get-ItemProperty -Path $StartupKey -Name TanrenCollector -ErrorAction SilentlyContinue) {
    throw 'Uninstall retained startup entry'
}
python collector/build/profile_fixture.py verify $RetentionManifest
if ($LASTEXITCODE -ne 0) { throw 'Installer changed protected fixture' }
@{ install=$true; reinstall=$true; frozen_selftest=$true; uninstall=$true;
   synthetic_profile_retained=$true; historical_upgrade='NOT_TESTED'; real_mt5='NOT_TESTED'; signed=([bool]$SigningConfig) } |
    ConvertTo-Json | Out-File (Join-Path $OutputDirectory 'INSTALLER_SMOKE.json') -Encoding utf8
