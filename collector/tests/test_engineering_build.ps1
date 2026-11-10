$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot '../build/preflight.ps1')
$Output = Join-Path ([IO.Path]::GetTempPath()) 'synthetic engineering output'
$Production = @(Get-CollectorCompilerArguments $Output '10.0.22621')
$Engineering = @(Get-CollectorCompilerArguments $Output '10.0.22621' 'engineering')
if ($Production.Count -ne 3 -or $Engineering.Count -ne 4 -or
    $Engineering[3] -cne '/DEngineeringBuild=1') { throw 'Build profile compiler flags incorrect' }
for ($Index = 0; $Index -lt 3; $Index++) {
    if ($Production[$Index] -cne $Engineering[$Index]) { throw 'Production arguments changed' }
}
$Build = Join-Path $PSScriptRoot '../build/build.ps1'
foreach ($Case in @(
    @{ApiOrigin='https://tanrenway.com'},
    @{ApiOrigin='https://collector-offline.invalid/'},
    @{ApiOrigin='https://collector-offline.invalid';SigningConfig='not-opened.signing.json'}
)) {
    $Rejected = $false
    try { & $Build -BuildProfile engineering -ExpectedSourceSha ('0' * 40) @Case }
    catch {
        if ($_.Exception.Message -cne 'Engineering requires exact offline origin and unsigned internal build; never production promotion') { throw }
        $Rejected = $true
    }
    if (-not $Rejected) { throw 'Unsafe engineering build accepted' }
}
'PASS: profile compiler arguments and 3 fail-closed origin/signing gates; no build executed'
