# Portable predicate/negative tests with synthetic signatures; NEVER a Windows crypto test.
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot '../build/trust.ps1')
$Directory=Join-Path ([IO.Path]::GetTempPath()) ('collector-trust-test-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $Directory | Out-Null
$Passed=0
function Check([bool]$Condition) { if (-not $Condition) { throw 'Trust predicate failed' }; $script:Passed++ }
function Reject([scriptblock]$Action,[string]$Pattern) {
    try { & $Action } catch { Check ($_.Exception.Message -match $Pattern); return }
    throw 'Expected rejection did not occur'
}
$Verifier=Join-Path $Directory $(if ($IsWindows) {'verify.cmd'} else {'verify.sh'})
if ($IsWindows) { "@echo off`r`nexit /b 0" | Set-Content $Verifier } else {
    "#!/bin/sh`nexit 0" | Set-Content $Verifier; & chmod +x $Verifier
}
$Config=[pscustomobject]@{mode='certificate-store';subject='CN=Fixture';thumbprint=('A'*40);signtool=$Verifier;timestamp='http://timestamp.digicert.com'}
function New-FixtureSignature {
    return [pscustomobject]@{Status='Valid';SignatureType='Authenticode';SignerCertificate=[pscustomobject]@{
        Subject='CN=Fixture';Thumbprint=('A'*40);PublicKey=[pscustomobject]@{Oid=[pscustomobject]@{Value='1.2.840.113549.1.1.1'}}};
        TimeStamperCertificate=[pscustomobject]@{Thumbprint=('B'*40)}}
}
$script:Signature=New-FixtureSignature
$Lock=Get-Content (Join-Path $PSScriptRoot '../build/toolchain.json') -Raw | ConvertFrom-Json
function Get-AuthenticodeSignature { param($LiteralPath); return $script:Signature }
function Get-FileHash { param($LiteralPath,$Algorithm); return [pscustomobject]@{Hash=$Lock.sdk.file_sha256} }
$Result=Assert-CollectorSignature 'fixture.exe' $Config $true
Check ($Result.status -eq 'Valid' -and $Result.timestamp)
$script:Signature.Status='NotSigned'; Reject { Assert-CollectorSignature 'fixture.exe' $Config $true } 'Valid trusted'
$script:Signature=New-FixtureSignature; $script:Signature.TimeStamperCertificate=$null
Reject { Assert-CollectorSignature 'fixture.exe' $Config $true } 'timestamped'
$script:Signature=New-FixtureSignature; $script:Signature.SignerCertificate.Subject='CN=Other'
Reject { Assert-CollectorSignature 'fixture.exe' $Config $true } 'publisher'
Check ((Assert-CollectorSignature 'vendor.dll' $Config $false).status -eq 'Valid')
$script:Signature=New-FixtureSignature; $script:Signature.SignerCertificate.PublicKey.Oid.Value='1.2.840.10045.2.1'
Reject { Assert-CollectorSignature 'fixture.exe' $Config $true } 'RSA'
$script:Signature=New-FixtureSignature; $script:Signature.SignerCertificate.Thumbprint=('C'*40)
Reject { Assert-CollectorSignature 'fixture.exe' $Config $true } 'certificate'
$script:Signature=New-FixtureSignature; $script:Signature.Status='HashMismatch'
Reject { Assert-CollectorSignature 'fixture.exe' $Config $false } 'Valid trusted'
$ConfigPath=Join-Path $Directory 'fixture.signing.json'
$Config | ConvertTo-Json | Set-Content $ConfigPath
Check ((Read-CollectorSigningConfig $ConfigPath).mode -eq 'certificate-store')
$Config | Add-Member clientSecret 'synthetic-forbidden'
$Config | ConvertTo-Json | Set-Content $ConfigPath
Reject { Read-CollectorSigningConfig $ConfigPath } 'secrets forbidden'
$PE=Join-Path $Directory 'fixture.bin'
$Bytes=[byte[]]::new(128);$Bytes[0]=77;$Bytes[1]=90;$Bytes[60]=64;$Bytes[64]=80;$Bytes[65]=69
[IO.File]::WriteAllBytes($PE,$Bytes)
Check (Test-CollectorPE $PE)
$Bytes[64]=0;[IO.File]::WriteAllBytes($PE,$Bytes)
Reject { Test-CollectorPE $PE } 'Malformed PE'
$script:Signature=New-FixtureSignature; $script:Signature.SignatureType='Catalog'
Reject { Assert-CollectorSignature 'fixture.exe' $Config $false } 'Authenticode'
$Environment=[pscustomobject]@{ protection_rules=@([pscustomobject]@{type='required_reviewers';reviewers=@('fixture-owner');prevent_self_review=$true});can_admins_bypass=$false;deployment_branch_policy=[pscustomobject]@{custom_branch_policies=$true} }
$Policies=[pscustomobject]@{branch_policies=@([pscustomobject]@{name='feat/mt5-modernization-phase1'})}
Assert-CollectorEnvironment $Environment $Policies; Check $true
$Environment.can_admins_bypass=$true
Reject { Assert-CollectorEnvironment $Environment $Policies } 'bypass'
$Environment.can_admins_bypass=$false; $Environment.protection_rules[0].prevent_self_review=$false
Reject { Assert-CollectorEnvironment $Environment $Policies } 'reviewer'
Get-ChildItem (Join-Path $PSScriptRoot '../build/*.ps1') | ForEach-Object {
    $Tokens=$null;$Errors=$null
    [Management.Automation.Language.Parser]::ParseFile($_.FullName,[ref]$Tokens,[ref]$Errors) | Out-Null
    Check ($Errors.Count -eq 0)
}
"Portable PowerShell trust predicates/parser: $Passed passed; real Authenticode NOT tested"
# Only files created in a fresh temporary test directory. No profiles/containers/volumes touched.
Remove-Item -Recurse -LiteralPath $Directory
