# Windows crypto is delegated to Authenticode/SignTool, never a custom signature algorithm.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
function Read-CollectorSigningConfig([string]$ConfigPath) {
    $Config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
    $Allowed = @('mode','signtool','subject','thumbprint','timestamp','dlib','metadata')
    foreach ($Property in $Config.PSObject.Properties.Name) {
        if ($Property -notin $Allowed) { throw "Unexpected signing configuration field (secrets forbidden)" }
    }
    foreach ($Field in @('mode','signtool','subject','timestamp')) {
        if (-not $Config.PSObject.Properties[$Field] -or -not $Config.$Field) { throw "Missing signing configuration field: $Field" }
    }
    if ($Config.mode -notin @('certificate-store','azure-artifact')) { throw 'Unsupported signing provider' }
    if ($Config.subject -match 'REPLACE|<|>|[\r\n]') { throw 'Verified publisher subject required' }
    $Timestamp = [Uri]$Config.timestamp
    if ($Timestamp.Scheme -notin @('http','https') -or $Timestamp.Host -notin @('timestamp.digicert.com','timestamp.acs.microsoft.com') -or $Timestamp.UserInfo -or $Timestamp.Query -or $Timestamp.Fragment -or $Timestamp.AbsolutePath -ne '/') { throw 'Reviewed RFC3161 timestamp service required' }
    $Lock = Get-Content (Join-Path $PSScriptRoot 'toolchain.json') -Raw | ConvertFrom-Json
    if ((Get-FileHash -LiteralPath $Config.signtool -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Lock.sdk.file_sha256) { throw 'Unapproved SignTool binary' }
    if ($Config.mode -eq 'certificate-store') {
        if (-not $Config.PSObject.Properties['thumbprint'] -or $Config.thumbprint -notmatch '^[0-9A-Fa-f]{40}$') { throw 'Exact approved certificate thumbprint required' }
    } else {
        if (-not $Config.PSObject.Properties['dlib'] -or -not $Config.PSObject.Properties['metadata']) { throw 'Artifact Signing client and metadata required' }
        if ((Get-FileHash -LiteralPath $Config.dlib -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Lock.artifact_client.file_sha256) { throw 'Unapproved Artifact Signing client' }
        $Metadata = Get-Content -LiteralPath $Config.metadata -Raw | ConvertFrom-Json
        foreach ($Name in $Metadata.PSObject.Properties.Name) {
            if ($Name -notin @('Endpoint','CodeSigningAccountName','CertificateProfileName','CorrelationId','ExcludeCredentials')) { throw 'Secrets/unexpected cloud metadata forbidden' }
        }
        if (-not $Metadata.PSObject.Properties['ExcludeCredentials'] -or 'InteractiveBrowserCredential' -notin $Metadata.ExcludeCredentials -or 'EnvironmentCredential' -notin $Metadata.ExcludeCredentials) { throw 'Noninteractive Azure CLI authentication required' }
        $Endpoint = [Uri]$Metadata.Endpoint
        if ($Endpoint.Scheme -ne 'https' -or $Endpoint.Host -notmatch '^[a-z0-9-]+\.codesigning\.azure\.net$' -or $Endpoint.UserInfo -or $Endpoint.Query -or $Endpoint.Fragment -or $Endpoint.AbsolutePath -ne '/') { throw 'Public Artifact Signing HTTPS endpoint required' }
        foreach ($Field in @('CodeSigningAccountName','CertificateProfileName')) {
            if ($Metadata.$Field -notmatch '^[a-zA-Z0-9-]{1,100}$') { throw 'Invalid Artifact Signing account/profile' }
        }
    }
    return $Config
}
function Assert-CollectorSignature([string]$Path, $Config, [bool]$RequirePublisher = $false) {
    $Signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($Signature.Status.ToString() -ne 'Valid' -or $Signature.SignatureType.ToString() -ne 'Authenticode' -or -not $Signature.SignerCertificate -or -not $Signature.TimeStamperCertificate) { throw 'Valid trusted timestamped Authenticode signature required' }
    if ($Signature.SignerCertificate.PublicKey.Oid.Value -ne '1.2.840.113549.1.1.1') { throw 'RSA signer required for SAC compatibility target' }
    if ($RequirePublisher) {
        if ($Signature.SignerCertificate.Subject -cne $Config.subject) { throw 'Unexpected publisher identity' }
        if ($Config.mode -eq 'certificate-store' -and $Signature.SignerCertificate.Thumbprint -ine $Config.thumbprint) { throw 'Unexpected publisher certificate' }
    }
    & $Config.signtool verify /pa /all /tw $Path | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'SignTool Authenticode verification failed' }
    return [ordered]@{ status='Valid'; embedded=$true; rsa=$true; timestamp=$true;
        subject=$Signature.SignerCertificate.Subject; thumbprint=$Signature.SignerCertificate.Thumbprint;
        timestamp_thumbprint=$Signature.TimeStamperCertificate.Thumbprint;
        sha256=(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
}
function Sign-CollectorFile([string]$Path, $Config) {
    if (-not $IsWindows) { throw 'Native Windows signing required' }
    $Existing = Get-AuthenticodeSignature -LiteralPath $Path
    if ($Existing.Status.ToString() -eq 'Valid') {
        # Never silently replace valid third-party signatures; verify their RSA/time/trust instead.
        return Assert-CollectorSignature $Path $Config $false
    }
    if ($Existing.Status.ToString() -ne 'NotSigned') { throw 'Refusing to re-sign invalid/tampered/untrusted signature' }
    $Arguments = @('sign','/fd','SHA256','/tr',$Config.timestamp,'/td','SHA256')
    if ($Config.mode -eq 'certificate-store') {
        $Certificate = Get-Item -LiteralPath ('Cert:\CurrentUser\My\'+$Config.thumbprint)
        if ($Certificate.Subject -ceq $Certificate.Issuer -or -not $Certificate.HasPrivateKey -or $Certificate.Subject -cne $Config.subject -or $Certificate.NotAfter -le (Get-Date) -or $Certificate.PublicKey.Oid.Value -ne '1.2.840.113549.1.1.1' -or '1.3.6.1.5.5.7.3.3' -notin $Certificate.EnhancedKeyUsageList.ObjectId.Value) { throw 'Usable RSA Code Signing certificate/private-key provider required' }
        $Arguments += @('/s','My','/sha1',$Config.thumbprint)
    } else {
        $Arguments += @('/dlib',$Config.dlib,'/dmdf',$Config.metadata)
    }
    & $Config.signtool @Arguments $Path | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Signing or RFC3161 timestamp failed' }
    return Assert-CollectorSignature $Path $Config $true
}
function Test-CollectorPE([string]$Path) {
    $Stream = [IO.File]::OpenRead($Path)
    try {
        if ($Stream.Length -lt 64) { return $false }
        $Reader = [IO.BinaryReader]::new($Stream)
        if ($Reader.ReadUInt16() -ne 0x5A4D) { return $false }
        $Stream.Position=60; $Offset=$Reader.ReadUInt32()
        if ($Offset -gt $Stream.Length-4) { throw 'Malformed executable header' }
        $Stream.Position=$Offset
        if ($Reader.ReadUInt32() -ne 0x00004550) { throw 'Malformed PE signature' }
        return $true
    } finally { $Stream.Dispose() }
}

function Assert-CollectorEnvironment($Environment, $Policies) {
    $Rule=@($Environment.protection_rules | Where-Object { $_.type -eq 'required_reviewers' })
    if ($Rule.Count -ne 1 -or @($Rule[0].reviewers).Count -lt 1 -or $Rule[0].prevent_self_review -ne $true) { throw 'Required independent signing reviewer missing' }
    if ($Environment.can_admins_bypass -ne $false) { throw 'Signing approval bypass must be disabled' }
    if (-not $Environment.deployment_branch_policy.custom_branch_policies) { throw 'Exact signing branch policy required' }
    if (@($Policies.branch_policies).Count -ne 1 -or $Policies.branch_policies[0].name -cne 'feat/mt5-modernization-phase1') { throw 'Signing environment must restrict this exact branch' }
}
