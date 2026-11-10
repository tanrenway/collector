param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$ConfigPath)
. (Join-Path $PSScriptRoot 'trust.ps1')
$Config = Read-CollectorSigningConfig $ConfigPath
Sign-CollectorFile $Path $Config | Out-Null
# The Inno hook signs BOTH its generated uninstaller and final Setup.
Assert-CollectorSignature $Path $Config $true | Out-Null
