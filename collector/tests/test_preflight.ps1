$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot '../build/preflight.ps1')
$Root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$Output = [IO.Path]::GetFullPath('output with spaces', $Root)
$Arguments = @(Get-CollectorCompilerArguments $Output '10.0.22621')
if ($Arguments.Count -ne 3) { throw 'Inno arguments collapsed' }
if ($Arguments[0] -cne ('/O' + $Output)) { throw 'Output path changed' }
if ($Arguments[1] -cne ('/DDistributionRoot=' + (Join-Path $Output 'TanrenCollector'))) { throw 'Distribution path changed' }
if ($Arguments[2] -cne '/DMinimumWindowsVersion=10.0.22621') { throw 'Minimum version changed' }
# Exercise native argument transmission, including a single argument containing spaces.
$Json = & python -c 'import json,sys; print(json.dumps(sys.argv[1:]))' @Arguments
if ($LASTEXITCODE -ne 0) { throw 'Argument probe failed' }
$Received = @($Json | ConvertFrom-Json)
if ($Received.Count -ne 3 -or $Received[1] -cne $Arguments[1]) { throw 'Native argument transmission failed' }
'PASS: three distinct compiler arguments and paths with spaces (portable, not ISCC execution)'
