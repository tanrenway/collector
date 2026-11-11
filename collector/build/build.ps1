param([string]$ApiOrigin = 'https://collector-offline.invalid',
      [string]$OutputDirectory = 'dist', [string]$SigningConfig,
      [Parameter(Mandatory)][string]$ExpectedSourceSha,
      [string]$MinimumWindowsVersion = '10.0.22621',
      [ValidateSet('production','engineering')][string]$BuildProfile = 'production')
$ErrorActionPreference = 'Stop'
$BuildProfile = $BuildProfile.ToLowerInvariant()
. (Join-Path $PSScriptRoot 'preflight.ps1')
Set-StrictMode -Version Latest
if (-not [Environment]::Is64BitProcess -or $env:OS -ne 'Windows_NT') { throw 'Windows x64 build required' }
$Root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
if ($BuildProfile -eq 'engineering' -and ($ApiOrigin -cne 'https://collector-offline.invalid' -or $SigningConfig)) {
    throw 'Engineering requires exact offline origin and unsigned internal build; never production promotion'
}
$SetupName = if ($BuildProfile -eq 'engineering') { 'TanrenCollectorEngineeringSetup.exe' } else { 'TanrenCollectorSetup.exe' }
$Lock = Get-Content (Join-Path $PSScriptRoot 'toolchain.json') -Raw | ConvertFrom-Json
$PythonVersion = python -c 'import platform; print(platform.python_version())'
if ($LASTEXITCODE -ne 0 -or $PythonVersion -ne $Lock.python) { throw "Pinned Python $($Lock.python) required" }
$Uri = [Uri]$ApiOrigin
if ($Uri.Scheme -ne 'https' -or -not $Uri.Host -or $Uri.UserInfo -or $Uri.Query -or $Uri.Fragment -or $Uri.AbsolutePath -ne '/') { throw 'Reviewed HTTPS origin required, no path/credentials/query/fragment' }
$Target = Join-Path $Root 'collector/tanren_collector/build_target.py'
$OriginalTarget = [IO.File]::ReadAllText($Target)
$PreviousEpoch = $env:SOURCE_DATE_EPOCH
$PreviousSeed = $env:PYTHONHASHSEED
Push-Location $Root
try {
    $Commit = git rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or $Commit -notmatch '^[0-9a-f]{40}$') { throw 'Immutable Git source required' }
    $Status = git status --porcelain
    if ($LASTEXITCODE -ne 0) { throw 'Git source status unavailable' }
    $Dirty = [bool]$Status
    if ($Dirty -or $ExpectedSourceSha -cnotmatch '^[0-9a-f]{40}$' -or $Commit -cne $ExpectedSourceSha) { throw 'Clean exact reviewed source SHA required for every RC build' }
    if ($MinimumWindowsVersion -notmatch '^10\.0\.[0-9]{5}$') { throw 'Explicit reviewed candidate Windows version required' }
    $Epoch = git log -1 --format=%ct
    if ($LASTEXITCODE -ne 0 -or $Epoch -notmatch '^[0-9]+$') { throw 'Source timestamp unavailable' }
    $env:SOURCE_DATE_EPOCH=$Epoch
    $env:PYTHONHASHSEED='0'
    $Trusted = -not [string]::IsNullOrEmpty($SigningConfig)
    if ($Trusted -and $Dirty) { throw 'Trusted signing requires a clean reviewed checkout' }
    $OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory, $Root)
    if ((Test-Path (Join-Path $OutputDirectory 'TanrenCollector')) -or (Test-Path (Join-Path $OutputDirectory $SetupName))) { throw 'Use a fresh output directory; never mix old and new binaries' }
    if ((Test-Path $OutputDirectory) -and ((Get-Item $OutputDirectory).LinkType -or (Get-ChildItem -Force $OutputDirectory | Select-Object -First 1))) { throw 'Empty, non-symlink output directory required' }
    $Virtual = python -c 'import sys; print(int(sys.prefix != sys.base_prefix))'
    if ($LASTEXITCODE -ne 0 -or $Virtual -ne '1') { throw 'Fresh isolated build virtualenv required' }
    New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
    $InputNames = @('collector/build/build.ps1','collector/build/preflight.ps1','collector/build/check_qt_smoke.py','collector/build/toolchain.json','collector/build/windows_inventory.py','collector/build/profile_fixture.py','collector/build/installer-smoke.ps1','collector/build/compare-bridge.ps1','collector/build/version-info.txt','collector/tanren_collector/__init__.py','collector/tanren_collector/bridge_probe.py',
        'collector/build/windows-requirements.lock','collector/build/collector.spec',
        'collector/build/hooks/hook-PySide6.QtQml.py','collector/build/qt_inventory.py','collector/build/collect_notices.py','collector/build/qt-licenses/LGPL-3.txt','collector/build/qt-licenses/GPL-2.txt','collector/build/qt-licenses/GPL-3.txt','collector/build/qt-licenses/README.md','collector/tanren_collector/qt/design.json',
        'collector/build/installer.iss','collector/build/trust.ps1','collector/build/sign-file.ps1',
        'collector/build/complete-release.ps1','collector/build/release_manifest.py')
    $InputHashes = [ordered]@{}
    if ($BuildProfile -eq 'engineering') { $InputNames += 'collector/tanren_collector/build_profile.py' }
    foreach ($Name in $InputNames) { $InputHashes[$Name] = (Get-FileHash $Name -Algorithm SHA256).Hash.ToLowerInvariant() }
    if ($Trusted) {
        . (Join-Path $PSScriptRoot 'trust.ps1')
        $SigningConfig = (Resolve-Path $SigningConfig).Path
        $Config = Read-CollectorSigningConfig $SigningConfig
    }
    [IO.File]::WriteAllText($Target, ('ORIGIN = ' + (ConvertTo-Json -InputObject ($ApiOrigin.TrimEnd('/')) -Compress) + [Environment]::NewLine + 'SOURCE_COMMIT = '+(ConvertTo-Json -InputObject $Commit -Compress) + [Environment]::NewLine + 'BUILD_PROFILE = ' + (ConvertTo-Json -InputObject $BuildProfile -Compress)))
    python -m pip install --require-hashes --only-binary=:all: -r collector/build/windows-requirements.lock
    if ($LASTEXITCODE -ne 0) { throw 'Locked dependency installation failed' }
    python -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency integrity check failed' }
    python -c "from PIL import Image; Image.open('collector/build/icon-256.png').save('collector/build/collector.ico', sizes=[(16,16),(20,20),(24,24),(32,32),(40,40),(48,48),(64,64),(256,256)])"
    if ($LASTEXITCODE -ne 0) { throw 'Icon preparation failed' }
    $WorkPath = if ($BuildProfile -eq 'engineering') { Join-Path $OutputDirectory 'build-work' } else { 'build/collector' }
    python -m PyInstaller --clean --noconfirm --distpath $OutputDirectory --workpath $WorkPath collector/build/collector.spec
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }
    python collector/build/collect_notices.py --output (Join-Path $OutputDirectory 'TanrenCollector/THIRD_PARTY_LICENSES')
    if ($LASTEXITCODE -ne 0) { throw 'License collection failed' }
    python collector/build/qt_inventory.py (Join-Path $OutputDirectory 'TanrenCollector') --windows --output (Join-Path $OutputDirectory 'QT_INVENTORY.json')
    if ($LASTEXITCODE -ne 0) { throw 'Qt inventory validation failed' }
    Copy-Item (Join-Path $PSScriptRoot 'APP_CONTROL_SUPPORT.txt') (Join-Path $OutputDirectory 'TanrenCollector/APP_CONTROL_SUPPORT.txt')
    if ($Trusted) {
        $Before = [ordered]@{}
        foreach ($File in Get-ChildItem (Join-Path $OutputDirectory 'TanrenCollector') -File -Recurse | Sort-Object FullName) {
            if (Test-CollectorPE $File.FullName) {
                $Before[[IO.Path]::GetRelativePath($OutputDirectory,$File.FullName).Replace('\','/')] = (Get-FileHash $File.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
                Sign-CollectorFile $File.FullName $Config | Out-Null
            }
        }
        $Before | ConvertTo-Json | Set-Content (Join-Path $OutputDirectory 'PRE_SIGN_PE_HASHES.json') -Encoding utf8NoBOM
        Assert-CollectorSignature (Join-Path $OutputDirectory 'TanrenCollector/TanrenCollector.exe') $Config $true | Out-Null
        # Signing changes PE hashes: retain a final Qt inventory, not stale pre-sign digests.
        python collector/build/qt_inventory.py (Join-Path $OutputDirectory 'TanrenCollector') --windows --output (Join-Path $OutputDirectory 'QT_INVENTORY.json')
        if ($LASTEXITCODE -ne 0) { throw 'Post-sign Qt inventory validation failed' }
    }
    python collector/build/windows_inventory.py (Join-Path $OutputDirectory 'TanrenCollector') --output (Join-Path $OutputDirectory 'WINDOWS_INVENTORY.json')
    if ($LASTEXITCODE -ne 0) { throw 'Windows native inventory validation failed' }
    $Compiler = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6/ISCC.exe'
    if (-not (Test-Path $Compiler)) { throw 'Install pinned Inno Setup first' }
    $CompilerIdentity = Assert-CollectorInnoCompiler $Compiler ([string]$Lock.inno_setup)
    $Version = $CompilerIdentity.version
    $CompilerIdentity | ConvertTo-Json | Set-Content (Join-Path $OutputDirectory 'INNO_IDENTITY.json') -Encoding utf8NoBOM
    $Arguments = @(Get-CollectorCompilerArguments $OutputDirectory $MinimumWindowsVersion $BuildProfile)
    if ($Trusted) {
        foreach ($Value in @($Root,$SigningConfig,$PSHOME)) {
            if ($Value -match '[$"\r\n]') { throw 'Use a simple signing workspace path for the Inno hook' }
        }
        $Command = '$q'+(Join-Path $PSHOME 'pwsh.exe')+'$q -NoLogo -NoProfile -NonInteractive -File $q'+(Join-Path $PSScriptRoot 'sign-file.ps1')+'$q -ConfigPath $q'+$SigningConfig+'$q -Path $f'
        $Arguments += @('/DTrustedBuild=1', ('/Stanren='+$Command))
    }
    & $Compiler @Arguments collector/build/installer.iss
    if ($LASTEXITCODE -ne 0) { throw 'Installer compilation/signing failed' }
    if ($Trusted) { Assert-CollectorSignature (Join-Path $OutputDirectory $SetupName) $Config $true | Out-Null }
    $Digest = (Get-FileHash (Join-Path $OutputDirectory $SetupName) -Algorithm SHA256).Hash.ToLowerInvariant()
    "$Digest  $SetupName" | Set-Content (Join-Path $OutputDirectory 'SHA256SUMS.txt') -Encoding ascii
    $ApiOrigin | Set-Content (Join-Path $OutputDirectory 'BUILD_ORIGIN.txt') -Encoding ascii
    $Commit | Set-Content (Join-Path $OutputDirectory 'SOURCE_COMMIT.txt') -Encoding ascii
    python -m pip list --format=freeze | Set-Content (Join-Path $OutputDirectory 'BUILD_DEPENDENCIES.txt') -Encoding ascii
    if ($LASTEXITCODE -ne 0) { throw 'Dependency provenance collection failed' }
    $Info = [ordered]@{ source_commit=$Commit; source_clean=(-not $Dirty); api_origin=$ApiOrigin.TrimEnd('/');
        python=$PythonVersion; inno=$Version; inputs=$InputHashes; signed_uninstaller=$Trusted;
        candidate_version='0.7.1'; minimum_windows_candidate=$MinimumWindowsVersion; os_support_verified=$false;
        source_date_epoch=$Epoch; python_hash_seed='0';
        publisher=$(if ($Trusted) {$Config.subject} else {''});
        provider=$(if ($Trusted) {$Config.mode} else {'unsigned-review'});
        os=[Environment]::OSVersion.VersionString; powershell=$PSVersionTable.PSVersion.ToString() }
    if ($BuildProfile -eq 'engineering') {
        $Info.build_profile = 'engineering'
        $Info.display_name = 'Tanren Collector Engineering'
        $Info.profile_directory = 'TanrenCollectorEngineering'
        $Info.installer_app_id = 'C7E48B92-68D5-4C31-9177-503BA7F62DB8'
        $Info.setup_filename = $SetupName
        $Info.network_enabled = $false
        $Info.native_mt5_enabled = $false
    }
    $Info | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $OutputDirectory 'BUILD_INFO.json') -Encoding utf8NoBOM
    Copy-Item (Join-Path $PSScriptRoot 'toolchain.json') (Join-Path $OutputDirectory 'TOOLCHAIN_INPUTS.json')
} finally { [IO.File]::WriteAllText($Target, $OriginalTarget); Pop-Location; $env:SOURCE_DATE_EPOCH=$PreviousEpoch; $env:PYTHONHASHSEED=$PreviousSeed }
if ($Trusted) { & (Join-Path $PSScriptRoot 'complete-release.ps1') -OutputDirectory $OutputDirectory -ConfigPath $SigningConfig }
