param([Parameter(Mandatory)][string]$OutputDirectory,
      [Parameter(Mandatory)][string]$ConfigPath, [string]$EvidencePath)
. (Join-Path $PSScriptRoot 'trust.ps1')
if (-not $IsWindows) { throw 'Native Windows Authenticode verification required' }
$Root = (Resolve-Path $OutputDirectory).Path
$Config = Read-CollectorSigningConfig $ConfigPath
$Repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$Info = Get-Content (Join-Path $Root 'BUILD_INFO.json') -Raw | ConvertFrom-Json
$Commit = git -C $Repo rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $Commit -cne $Info.source_commit) { throw 'Verify against exact source checkout' }
$Status = git -C $Repo status --porcelain
if ($LASTEXITCODE -ne 0 -or $Status) { throw 'Source checkout changed/dirty' }
$Expected = @('collector/build/build.ps1','collector/build/preflight.ps1','collector/build/check_qt_smoke.py','collector/build/toolchain.json','collector/build/windows_inventory.py','collector/build/profile_fixture.py','collector/build/installer-smoke.ps1','collector/build/compare-bridge.ps1','collector/build/version-info.txt','collector/tanren_collector/__init__.py','collector/tanren_collector/bridge_probe.py','collector/build/windows-requirements.lock',
 'collector/build/collector.spec','collector/build/hooks/hook-PySide6.QtQml.py','collector/build/qt_inventory.py','collector/build/collect_notices.py','collector/build/qt-licenses/LGPL-3.txt','collector/build/qt-licenses/GPL-2.txt','collector/build/qt-licenses/GPL-3.txt','collector/build/qt-licenses/README.md','collector/tanren_collector/qt/design.json',
        'collector/build/installer.iss','collector/build/trust.ps1',
 'collector/build/sign-file.ps1','collector/build/complete-release.ps1','collector/build/release_manifest.py')
if (@($Info.inputs.PSObject.Properties).Count -ne $Expected.Count) { throw 'Missing provenance inputs' }
foreach ($Name in $Expected) {
    if (-not $Info.inputs.PSObject.Properties[$Name] -or (Get-FileHash (Join-Path $Repo $Name) -Algorithm SHA256).Hash.ToLowerInvariant() -cne $Info.inputs.$Name) { throw 'Source/build input mismatch' }
}
$Report = [ordered]@{}
foreach ($File in Get-ChildItem -LiteralPath $Root -File -Recurse | Sort-Object FullName) {
    if ($File.LinkType) { throw 'Release symlinks forbidden' }
    if (Test-CollectorPE $File.FullName) {
        $Relative = [IO.Path]::GetRelativePath($Root,$File.FullName).Replace('\','/')
        $Owned = $Relative -in @('TanrenCollectorSetup.exe','TanrenCollector/TanrenCollector.exe')
        $Report[$Relative] = Assert-CollectorSignature $File.FullName $Config $Owned
    }
}
$Report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $Root 'SIGNATURE_REPORT.json') -Encoding utf8NoBOM
$Arguments = @((Join-Path $PSScriptRoot 'release_manifest.py'),$Root,'--create')
if ($EvidencePath) { $Arguments += @('--evidence',$EvidencePath) }
python @Arguments
if ($LASTEXITCODE -ne 0) { throw 'Release integrity/promotion gate failed' }
