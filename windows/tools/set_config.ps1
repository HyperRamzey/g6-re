# set_config.ps1 - replace the live EqualizerAPO config with a given file.
#
# config.txt in the install directory is `Include: g6ct.txt`, so swapping
# g6ct.txt is enough. EqualizerAPO watches the config directory and reloads on
# change, so no service restart is needed - which also makes this a live A/B
# switch for the null tests.
#
#   Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile',
#     '-ExecutionPolicy','Bypass','-File','set_config.ps1','-File','identity.txt'
param(
    [Parameter(Mandatory = $true)][string]$File,
    [string]$Target = 'C:\Program Files\EqualizerAPO\config\g6ct.txt',
    [string]$ConfigTxt = 'C:\Program Files\EqualizerAPO\config\config.txt'
)
$ErrorActionPreference = 'Stop'
$log = Join-Path $PSScriptRoot 'set_config.log'
function Say($m) { Write-Host $m; Add-Content -Path $log -Value ([string]$m) -Encoding UTF8 }
Set-Content -Path $log -Value ("=== " + (Get-Date -Format 'u') + " ===") -Encoding UTF8

try {
    if (-not (Test-Path $File)) { throw "no such file: $File" }
    Copy-Item -Path $File -Destination $Target -Force
    Say ("copied " + $File + " -> " + $Target + " (" + (Get-Item $Target).Length + " bytes)")
    if (Test-Path $ConfigTxt) {
        Say ("config.txt: " + ((Get-Content $ConfigTxt) -join ' / '))
    }
    Say "DONE"
    exit 0
} catch {
    Say ("FAILED: " + $_.Exception.Message)
    exit 1
}
