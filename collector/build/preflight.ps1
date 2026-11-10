# Portable helpers shared by the native build and regression tests.
function Get-CollectorCompilerArguments {
    param([string]$OutputDirectory, [string]$MinimumWindowsVersion,
          [ValidateSet('production','engineering')][string]$BuildProfile = 'production')
    @(
        ('/O' + $OutputDirectory)
        ('/DDistributionRoot=' + (Join-Path $OutputDirectory 'TanrenCollector'))
        ('/DMinimumWindowsVersion=' + $MinimumWindowsVersion)
    )
    if ($BuildProfile -eq 'engineering') { '/DEngineeringBuild=1' }
}

function Get-CollectorInnoEntries {
    # Both machine views and per-user registrations; no registry values are logged.
    $Keys = @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKCU:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
    )
    @(Get-ItemProperty $Keys -ErrorAction SilentlyContinue | Where-Object {
        $_.PSObject.Properties['DisplayName'] -and [string]$_.DisplayName -like 'Inno Setup*'
    })
}

function Get-CollectorInnoDirectory {
    param($Entry)
    foreach ($Name in @('InstallLocation','Inno Setup: App Path')) {
        $Property = $Entry.PSObject.Properties[$Name]
        if ($Property -and -not [string]::IsNullOrWhiteSpace([string]$Property.Value)) {
            $Value = ([string]$Property.Value).Trim().Trim('"')
            if ($Value -notmatch '["\r\n\x00]') { [IO.Path]::GetFullPath($Value) }
        }
    }
    foreach ($Name in @('UninstallString','QuietUninstallString')) {
        $Property = $Entry.PSObject.Properties[$Name]
        if ($Property -and [string]$Property.Value -match '^\s*(?:"([^"]+\.exe)"|(.+?\.exe))(?:\s|$)') {
            $Exe = if ($Matches[1]) { $Matches[1] } else { $Matches[2] }
            if ([IO.Path]::GetFileName($Exe) -match '^unins[0-9]+\.exe$') {
                [IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($Exe))
            }
        }
    }
}

function Test-CollectorInnoIdentity {
    param([string]$Compiler, [string]$ExpectedVersion, [object[]]$Entries, [string]$Banner)
    if ($ExpectedVersion -cnotmatch '^[0-9]+\.[0-9]+\.[0-9]+$') { throw 'Invalid pinned Inno version' }
    $CompilerPath = [IO.Path]::GetFullPath($Compiler)
    $Matching = @($Entries | Where-Object {
        $Entry = $_
        $Directories = @(Get-CollectorInnoDirectory $Entry)
        @($Directories | Where-Object {
            [IO.Path]::GetFullPath((Join-Path $_ 'ISCC.exe')) -ieq $CompilerPath
        }).Count -gt 0
    })
    if (-not $Matching.Count) { throw 'Inno registry identity does not match selected compiler' }
    # Duplicate entries across views are one identity only if all agree on the exact version.
    foreach ($Entry in $Matching) {
        $Version = $Entry.PSObject.Properties['DisplayVersion']
        if (-not $Version -or ([string]$Version.Value).Trim() -cne $ExpectedVersion) {
            throw 'Conflicting or unapproved Inno registry version for selected compiler'
        }
    }
    if ($Banner.Length -gt 16384) { throw 'Inno compiler version output exceeds bound' }
    $Versions = @([regex]::Matches($Banner, '(?m)^Compiler engine version:\s*Inno Setup ([0-9]+\.[0-9]+\.[0-9]+)\s*\r?$'))
    if ($Versions.Count -ne 1 -or $Versions[0].Groups[1].Value -cne $ExpectedVersion) {
        throw 'Compiler engine does not report the exact pinned Inno version'
    }
    [pscustomobject]@{version=$ExpectedVersion;matching_registry_entries=$Matching.Count}
}

function Test-CollectorInnoProbeResult {
    param([int]$ExitCode, [string]$Output)
    # ISCC 6.4.3 /? exits 1 without loading/reporting the compiler engine.
    # Our stdin #error must abort preprocessing (exit 2), never create an installer.
    if ($Output.Length -gt 16384 -or $ExitCode -ne 2 -or
        $Output -notmatch '(?m)^Error on line 1(?: in <stdin>)?:.*TANREN_VERSION_PROBE_ABORT\.?[ \t]*\r?$') {
        throw 'Inno compiler version probe did not abort as expected'
    }
    $Output
}

function Get-CollectorInnoBanner {
    param([string]$Compiler)
    $Start = New-Object System.Diagnostics.ProcessStartInfo
    $Start.FileName = $Compiler
    $Start.Arguments = '/O- -'
    $Start.UseShellExecute = $false
    $Start.CreateNoWindow = $true
    $Start.RedirectStandardInput = $true
    $Start.RedirectStandardOutput = $true
    $Start.RedirectStandardError = $true
    $Process = New-Object System.Diagnostics.Process
    $Process.StartInfo = $Start
    try {
        if (-not $Process.Start()) { throw 'Inno compiler version probe could not start' }
        $Stdout = $Process.StandardOutput.ReadToEndAsync()
        $Stderr = $Process.StandardError.ReadToEndAsync()
        # No user script/includes/signing commands; output is also explicitly disabled.
        $Process.StandardInput.WriteLine('#error TANREN_VERSION_PROBE_ABORT')
        $Process.StandardInput.Close()
        if (-not $Process.WaitForExit(10000)) {
            $Process.Kill()
            throw 'Inno compiler version probe timed out'
        }
        $Text = $Stdout.GetAwaiter().GetResult() + "`n" + $Stderr.GetAwaiter().GetResult()
        Test-CollectorInnoProbeResult $Process.ExitCode $Text
    } finally {
        $Process.Dispose()
    }
}

function Assert-CollectorInnoCompiler {
    param([string]$Compiler, [string]$ExpectedVersion)
    $File = Get-Item -LiteralPath $Compiler -ErrorAction Stop
    if ($File.PSIsContainer -or $File.Name -ine 'ISCC.exe') { throw 'Explicit installed ISCC.exe required' }
    $Banner = Get-CollectorInnoBanner $File.FullName
    $Entries = @(Get-CollectorInnoEntries)
    $Versions = @($Entries | ForEach-Object {
        $Property = $_.PSObject.Properties['DisplayVersion']
        if ($Property -and ([string]$Property.Value).Trim() -match '^[0-9.]{1,32}$') { ([string]$Property.Value).Trim() }
    } | Sort-Object -Unique)
    # Only numeric version metadata/counts, never registry command strings or user paths.
    Write-Host ([ordered]@{compiler='ISCC.exe';expected=$ExpectedVersion;registry_versions=$Versions;registry_entries=$Entries.Count} | ConvertTo-Json -Compress)
    $Identity = Test-CollectorInnoIdentity $File.FullName $ExpectedVersion $Entries $Banner
    [pscustomobject]@{version=$Identity.version;matching_registry_entries=$Identity.matching_registry_entries;sha256=(Get-FileHash $File.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
}
