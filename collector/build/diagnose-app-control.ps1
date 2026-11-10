param([Parameter(Mandatory)][string]$BinaryPath,
      [Parameter(Mandatory)][string]$OutputDirectory,
      [datetime]$Since = (Get-Date).AddHours(-2))
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if (-not $IsWindows) { throw 'Read-only Windows diagnostic requires Windows' }
$Binary=(Resolve-Path $BinaryPath).Path
$Output=[IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path $Output) { throw 'Choose a new private diagnostic directory' }
New-Item -ItemType Directory $Output | Out-Null
$Signature=Get-AuthenticodeSignature -LiteralPath $Binary
$State=Get-ItemPropertyValue 'HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy' -Name VerifiedAndReputablePolicyState -ErrorAction Stop
$Events=@(Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-CodeIntegrity/Operational';Id=3077,3033;StartTime=$Since} -MaxEvents 500 -ErrorAction SilentlyContinue)
$Relevant=@()
foreach ($Event in $Events) {
    $Xml=[xml]$Event.ToXml()
    $Names=@($Xml.Event.EventData.Data | Where-Object { $_.Name -in @('FileName','FilePath') } | ForEach-Object { $_.'#text' })
    if ($Names | Where-Object { $_ -and ([IO.Path]::GetFileName($_) -ieq [IO.Path]::GetFileName($Binary) -or $_.IndexOf('TanrenCollector',[StringComparison]::OrdinalIgnoreCase) -ge 0) }) {
        $Relevant += @{ id=$Event.Id; time_utc=$Event.TimeCreated.ToUniversalTime().ToString('o');
            files=@($Names | ForEach-Object { [IO.Path]::GetFileName($_) }) }
    }
}
@{ windows=[Environment]::OSVersion.VersionString; reported_policy_state=$State;
   file=[IO.Path]::GetFileName($Binary); sha256=(Get-FileHash $Binary -Algorithm SHA256).Hash;
   signature_status=$Signature.Status.ToString(); events=$Relevant;
   truncated=($Events.Count -eq 500); attests_sac_success=$false;
   note='Diagnostic only. Missing/inaccessible events do not prove no block. No policies modified.' } |
    ConvertTo-Json -Depth 8 | Set-Content (Join-Path $Output 'app-control.json') -Encoding utf8NoBOM
# No raw events/XML/messages/profile paths, credentials, policy edits or execution bypass.
