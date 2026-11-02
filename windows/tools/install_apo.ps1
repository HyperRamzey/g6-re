# install_apo.ps1 - attach EqualizerAPO to a render endpoint, one instance only.
#
# Replicates the registry part of DeviceAPOInfo::install() for INSTALL_LFX_GFX
# mode with installPreMix only and no chained child APO, i.e. exactly one
# EqualizerAPO instance in the chain and no other vendor APO left running.
#
#   .\install_apo.ps1 -EndpointGuid '{82B1DE69-E6C7-4290-9141-A1F14857DA9F}'
#
# Run elevated. Restart the audio services afterwards (or reboot) so audiodg
# rebuilds the endpoint's APO chain.
param(
    [Parameter(Mandatory=$true)][string]$EndpointGuid,
    [switch]$PostMixOnly,
    [switch]$KeepOtherApos,
    [switch]$WhatIf
)

$ErrorActionPreference = 'Stop'

# EqualizerAPO APO class ids. The mapping was confirmed from what the stock
# DeviceSelector wrote into this endpoint: the value it put in the SFX slot
# (",5") is EACD2258 and the one it put in EFX (",7") is EC1CC9CE, and those
# two slots are the pre-mix and post-mix positions of the render chain.
$PRE_MIX_GUID  = '{EACD2258-FCAC-4FF4-B36D-419E924A6D79}'
$POST_MIX_GUID = '{EC1CC9CE-FAED-4822-828A-82A81A6F018F}'

$FX_LFX = '{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},1'
$FX_GFX = '{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},2'
$FX_SFX = '{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},5'
$FX_MFX = '{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},6'
$FX_EFX = '{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},7'
$FX_DISABLE_ENHANCEMENTS = '{1da5d803-d492-4edd-8c23-e0c0ffee7f0e},5'

$fxKey    = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render\$EndpointGuid\FxProperties"
$childKey = "HKLM:\SOFTWARE\EqualizerAPO\Child APOs\$EndpointGuid"

function Set-Value([string]$key, [string]$name, [string]$value) {
    if ($WhatIf) { "  would set '$name' = '$value'"; return }
    New-ItemProperty -Path $key -Name $name -Value $value -PropertyType String -Force | Out-Null
    "  set '$name' = '$value'"
}
function Del-Value([string]$key, [string]$name) {
    if (-not ((Get-Item $key).Property -contains $name)) { "  '$name' already absent"; return }
    $old = (Get-ItemProperty -Path $key -Name $name).$name
    if ($WhatIf) { "  would delete '$name' (was '$old')"; return }
    Remove-ItemProperty -Path $key -Name $name -Force
    "  deleted '$name' (was '$old')"
}

if (-not (Test-Path $fxKey)) { throw "no FxProperties key at $fxKey (is the endpoint connected?)" }

# The MMDevices keys are owned by SYSTEM and not writable by Administrators
# until EqualizerAPO takes ownership. Doing the same here keeps this script
# usable on an endpoint that EqualizerAPO has never touched.
try {
    New-ItemProperty -Path $fxKey -Name 'eapo_probe' -Value 'x' -PropertyType String -Force | Out-Null
    Remove-ItemProperty -Path $fxKey -Name 'eapo_probe' -Force
} catch {
    "FxProperties is not writable yet, taking ownership"
    $owner = (Get-Acl 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render' ).Owner
    "  current owner of Render tree: $owner"
    throw "take ownership first (run EqualizerAPO's DeviceSelector once, or use takeown/icacls on the endpoint key)"
}

"=== endpoint $EndpointGuid ==="
"before:"
(Get-Item $fxKey).Property | ForEach-Object { "  '$_' = '" + (Get-ItemProperty $fxKey -Name $_).$_ + "'" } | Out-String | Write-Host

if (-not $WhatIf) {
    New-Item -Path $childKey -Force | Out-Null
}

"applying:"
if ($PostMixOnly) {
    # post-mix slot only
    Set-Value $childKey 'PreMixChild'  ''
    Set-Value $childKey 'PostMixChild' ''
    Set-Value $fxKey $FX_GFX $POST_MIX_GUID
    Del-Value $fxKey $FX_LFX
    Del-Value $fxKey $FX_SFX
    Del-Value $fxKey $FX_MFX
    Del-Value $fxKey $FX_EFX
} else {
    Set-Value $childKey 'PreMixChild'  ''
    Set-Value $childKey 'PostMixChild' ''
    Set-Value $fxKey $FX_LFX $PRE_MIX_GUID
    Del-Value $fxKey $FX_GFX
    Del-Value $fxKey $FX_SFX
    Del-Value $fxKey $FX_MFX
    Del-Value $fxKey $FX_EFX
}
Set-Value $childKey 'AllowSilentBufferModification' 'false'
Set-Value $childKey 'Version' '2'
# EqualizerAPO force-enables enhancements so the APO chain is not skipped.
Del-Value $fxKey $FX_DISABLE_ENHANCEMENTS

"after:"
(Get-Item $fxKey).Property | ForEach-Object { "  '$_' = '" + (Get-ItemProperty $fxKey -Name $_).$_ + "'" }
