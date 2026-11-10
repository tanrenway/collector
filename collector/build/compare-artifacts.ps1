param([Parameter(Mandatory)][string]$LeftDirectory,
      [Parameter(Mandatory)][string]$RightDirectory,
      [Parameter(Mandatory)][string]$OutputFile)
. (Join-Path $PSScriptRoot 'trust.ps1')
if (-not $IsWindows) { throw 'Authenticode comparison requires Windows' }
if (Test-Path $OutputFile) { throw 'Use a new private report file' }
function Read-ArtifactDirectory([string]$Directory) {
    $Root=(Resolve-Path $Directory).Path
    $Items=[ordered]@{}
    foreach ($File in Get-ChildItem $Root -File -Recurse) {
        if ($File.LinkType) { throw 'Do not follow artifact symlinks' }
        if (Test-CollectorPE $File.FullName) {
            $Signature=Get-AuthenticodeSignature -LiteralPath $File.FullName
            $Stream=[IO.File]::OpenRead($File.FullName)
            try {
                $Reader=[IO.BinaryReader]::new($Stream)
                $Stream.Position=60;$Offset=$Reader.ReadUInt32()
                $Stream.Position=$Offset+4;$Machine=$Reader.ReadUInt16();$Sections=$Reader.ReadUInt16()
                $Stream.Position=$Offset+20;$OptionalSize=$Reader.ReadUInt16()
                $Stream.Position=$Offset+24+16;$Entry=$Reader.ReadUInt32()
                $Stream.Position=$Offset+24+56;$ImageSize=$Reader.ReadUInt32()
                $End=0L
                for ($Index=0;$Index -lt $Sections;$Index++) {
                    $Stream.Position=$Offset+24+$OptionalSize+$Index*40+16
                    $Size=$Reader.ReadUInt32();$Pointer=$Reader.ReadUInt32()
                    $End=[Math]::Max($End,[long]$Pointer+$Size)
                }
            } finally { $Stream.Dispose() }
            $Relative=[IO.Path]::GetRelativePath($Root,$File.FullName).Replace('\','/')
            $Items[$Relative]=@{ sha256=(Get-FileHash $File.FullName -Algorithm SHA256).Hash;
                bytes=$File.Length; product_version=$File.VersionInfo.ProductVersion;
                machine=$Machine; sections=$Sections; entry_point=$Entry; image_size=$ImageSize;
                overlay_bytes=($File.Length-$End); signature_status=$Signature.Status.ToString();
                signature_type=$Signature.SignatureType.ToString();
                publisher=$(if ($Signature.SignerCertificate) {$Signature.SignerCertificate.Subject} else {$null});
                signer_key_oid=$(if ($Signature.SignerCertificate) {$Signature.SignerCertificate.PublicKey.Oid.Value} else {$null});
                timestamp_present=([bool]$Signature.TimeStamperCertificate) }
        }
    }
    return $Items
}
@{ schema=1; left=(Read-ArtifactDirectory $LeftDirectory); right=(Read-ArtifactDirectory $RightDirectory);
   note='Read-only original artifact inventory; overlay includes archive/certificates, not proof of malicious content. No binaries executed.' } |
    ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $OutputFile -Encoding utf8NoBOM
