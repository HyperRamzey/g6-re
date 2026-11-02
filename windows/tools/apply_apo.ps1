# apply_apo.ps1 - attach EqualizerAPO to the G733 render endpoint and restart
# the audio engine.
#
# The MMDevices keys are owned by SYSTEM and do not grant Administrators the
# full KEY_ALL_ACCESS that PowerShell's HKLM: provider asks for, which is why
# `New-ItemProperty` on them fails with "Requested registry access is not
# allowed" even when elevated. They do grant KEY_SET_VALUE, so the values are
# written through .NET's RegistryKey with exactly that right - no ownership or
# ACL change is required or performed.
#
# -Mode picks which of the endpoint's five APO slots EqualizerAPO occupies.
# Windows instantiates an APO only for the slots the driver/endpoint actually
# exposes, so this is the knob to turn if one mode stays silent:
#
#   lfx      {d04e05a6-...},1            legacy pre-mix slot, single instance
#   sfx      {d04e05a6-...},5            per-stream effect, single instance
#   sfx_efx  ,5 and ,7                   what DeviceSelector installs by default
#                                        (runs the config twice - test only)
#   vendor   (default)                   restore the Logitech HX2E chain
#
# EqualizerAPO's own DeviceAPOInfo::install() uses exactly these keys, and
# {d3993a3f-...},5/7 must hold the "Default" processing-mode GUID for the
# SFX/EFX slots or the engine will not select the APO at all.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File apply_apo.ps1 -Mode sfx
#   powershell -NoProfile -ExecutionPolicy Bypass -File apply_apo.ps1 -Mode lfx
#   powershell -NoProfile -ExecutionPolicy Bypass -File apply_apo.ps1 -Revert
param(
    [string]$EndpointGuid = '{82B1DE69-E6C7-4290-9141-A1F14857DA9F}',
    [ValidateSet('lfx', 'sfx', 'sfx_efx', 'vendor')]
    [string]$Mode = 'lfx',
    [switch]$Revert,
    [switch]$NoServiceRestart
)
$ErrorActionPreference = 'Stop'

$log = Join-Path $PSScriptRoot 'apply_apo.log'
function Say($m) {
    Write-Host $m
    Add-Content -Path $log -Value ([string]$m) -Encoding UTF8
}
Set-Content -Path $log -Value ("=== " + (Get-Date -Format 'u') + " mode=" + $Mode +
    " revert=" + [bool]$Revert + " ===") -Encoding UTF8

Add-Type @"
using System;
using System.Security.AccessControl;
using Microsoft.Win32;

public static class Fx {
    const RegistryRights W = RegistryRights.SetValue | RegistryRights.QueryValues;

    // ReadWriteSubTree is what actually asks for write access; ReadSubTree
    // returns a key object that .NET refuses to write through, which surfaces
    // as "Cannot write to the registry key".
    static RegistryKey Open(string subkey, bool write, RegistryRights rights) {
        var k = Registry.LocalMachine.OpenSubKey(subkey,
            write ? RegistryKeyPermissionCheck.ReadWriteSubTree
                  : RegistryKeyPermissionCheck.ReadSubTree,
            rights);
        if (k == null) throw new Exception("no access or missing key: " + subkey);
        return k;
    }

    public static void Set(string subkey, string name, string value) {
        using (var k = Open(subkey, true, W))
            k.SetValue(name, value, RegistryValueKind.String);
    }

    public static void SetMulti(string subkey, string name, string[] values) {
        using (var k = Open(subkey, true, W))
            k.SetValue(name, values, RegistryValueKind.MultiString);
    }

    public static bool Delete(string subkey, string name) {
        using (var k = Open(subkey, true, W)) {
            try { k.DeleteValue(name, false); return true; } catch { return false; }
        }
    }

    public static string Get(string subkey, string name) {
        using (var k = Open(subkey, false, RegistryRights.QueryValues)) {
            var v = k.GetValue(name, null);
            if (v == null) return null;
            var a = v as string[];
            return a == null ? v.ToString() : string.Join("|", a);
        }
    }

    public static bool Has(string subkey, string name) {
        using (var k = Open(subkey, false, RegistryRights.QueryValues))
            return k.GetValue(name, null) != null;
    }

    public static string[] Names(string subkey) {
        using (var k = Open(subkey, false, RegistryRights.QueryValues))
            return k.GetValueNames();
    }

    public static bool Exists(string subkey) {
        try {
            using (var k = Registry.LocalMachine.OpenSubKey(subkey,
                RegistryKeyPermissionCheck.ReadSubTree, RegistryRights.QueryValues))
                return k != null;
        } catch { return false; }
    }

    public static void CreateKey(string subkey) {
        using (var k = Registry.LocalMachine.CreateSubKey(subkey,
            RegistryKeyPermissionCheck.ReadWriteSubTree)) { }
    }

    public static void DeleteTree(string subkey) {
        Registry.LocalMachine.DeleteSubKeyTree(subkey, false);
    }
}
"@

# Confirmed from what the stock DeviceSelector wrote into this endpoint: the
# value it placed in the SFX slot (",5") is EACD2258 and the one in EFX (",7")
# is EC1CC9CE. DeviceAPOInfo uses the same two constants for pre-mix/post-mix.
$PRE_MIX_GUID  = '{EACD2258-FCAC-4FF4-B36D-419E924A6D79}'
$POST_MIX_GUID = '{EC1CC9CE-FAED-4822-828A-82A81A6F018F}'
# PKEY_AudioEndpoint_... "Default" processing mode; the only mode these
# endpoints advertise, and what install() writes when the list is missing.
$DEFAULT_MODE  = '{C18E2F7E-933D-4965-B7D1-1EEF228D2AF3}'

$FX_LFX = '{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},1'
$FX_GFX = '{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},2'
$FX_SFX = '{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},5'
$FX_MFX = '{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},6'
$FX_EFX = '{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},7'
$FX_DISABLE_ENHANCEMENTS = '{1da5d803-d492-4edd-8c23-e0c0ffee7f0e},5'
$MODES_SFX = '{d3993a3f-99c2-4402-b5ec-a92a0367664b},5'
$MODES_MFX = '{d3993a3f-99c2-4402-b5ec-a92a0367664b},6'
$MODES_EFX = '{d3993a3f-99c2-4402-b5ec-a92a0367664b},7'

$fxPath    = "SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render\$EndpointGuid\FxProperties"
$fxKey     = "HKLM:\$fxPath"
$childPath = "SOFTWARE\EqualizerAPO\Child APOs\$EndpointGuid"
$childKey  = "HKLM:\$childPath"

function Dump($label) {
    Say $label
    foreach ($n in [Fx]::Names($fxPath)) {
        Say ("  '" + $n + "' = '" + [Fx]::Get($fxPath, $n) + "'")
    }
    if ([Fx]::Exists($childPath)) {
        Say ("  child key " + $childPath)
        foreach ($n in [Fx]::Names($childPath)) {
            Say ("    '" + $n + "' = '" + [Fx]::Get($childPath, $n) + "'")
        }
    } else {
        Say "  child key (absent)"
    }
}

function DropFx($name) {
    $old = [Fx]::Get($fxPath, $name)
    if ($null -ne $old) {
        [Fx]::Delete($fxPath, $name) | Out-Null
        Say ("  deleted '" + $name + "' (was '" + $old + "')")
    }
}

try {
    if (-not [Fx]::Exists($fxPath)) { throw "no FxProperties at $fxPath" }
    if ($Revert) { $Mode = 'vendor' }

    Dump "=== before ==="

    if ($Mode -eq 'vendor') {
        Say "=== restore the vendor APO chain ==="
        [Fx]::Set($fxPath, $FX_LFX, '{A8CF6A24-68AE-499B-896A-0C631102AEB8}')
        Say ("  " + $FX_LFX + " = Logitech HX2E")
        DropFx $FX_GFX
        [Fx]::Set($fxPath, $FX_SFX, '{670173e3-78cf-11e5-a837-0800200c9a66}')
        [Fx]::Set($fxPath, $FX_MFX, '{670173e4-78cf-11e5-a837-0800200c9a66}')
        [Fx]::Set($fxPath, $FX_EFX, '{670173e5-78cf-11e5-a837-0800200c9a66}')
        Say "  SFX/MFX/EFX = Logitech 670173e3/e4/e5"
        DropFx $FX_DISABLE_ENHANCEMENTS
        if ([Fx]::Exists($childPath)) { [Fx]::DeleteTree($childPath); Say "  removed EqualizerAPO child key" }
    } else {
        Say ("=== install: mode " + $Mode + " ===")
        [Fx]::CreateKey($childPath)
        [Fx]::Set($childPath, 'PreMixChild', '')
        [Fx]::Set($childPath, 'PostMixChild', '')
        [Fx]::Set($childPath, 'AllowSilentBufferModification', 'false')
        [Fx]::Set($childPath, 'Version', '2')
        Say "  child key: PreMixChild='' PostMixChild='' Version=2"

        switch ($Mode) {
            'lfx' {
                [Fx]::Set($fxPath, $FX_LFX, $PRE_MIX_GUID)
                Say ("  " + $FX_LFX + " = " + $PRE_MIX_GUID)
                DropFx $FX_GFX; DropFx $FX_SFX; DropFx $FX_MFX; DropFx $FX_EFX
            }
            'sfx' {
                [Fx]::Set($fxPath, $FX_SFX, $PRE_MIX_GUID)
                Say ("  " + $FX_SFX + " = " + $PRE_MIX_GUID)
                if (-not [Fx]::Has($fxPath, $MODES_SFX)) {
                    [Fx]::SetMulti($fxPath, $MODES_SFX, @($DEFAULT_MODE))
                    Say ("  " + $MODES_SFX + " = " + $DEFAULT_MODE)
                } else {
                    Say ("  " + $MODES_SFX + " already '" + [Fx]::Get($fxPath, $MODES_SFX) + "'")
                }
                DropFx $FX_LFX; DropFx $FX_GFX; DropFx $FX_MFX; DropFx $FX_EFX
            }
            'sfx_efx' {
                [Fx]::Set($fxPath, $FX_SFX, $PRE_MIX_GUID)
                [Fx]::Set($fxPath, $FX_EFX, $POST_MIX_GUID)
                Say ("  " + $FX_SFX + " = " + $PRE_MIX_GUID)
                Say ("  " + $FX_EFX + " = " + $POST_MIX_GUID)
                foreach ($pair in @(@($MODES_SFX, 'sfx'), @($MODES_EFX, 'efx'))) {
                    if (-not [Fx]::Has($fxPath, $pair[0])) {
                        [Fx]::SetMulti($fxPath, $pair[0], @($DEFAULT_MODE))
                        Say ("  " + $pair[0] + " = " + $DEFAULT_MODE)
                    }
                }
                DropFx $FX_LFX; DropFx $FX_GFX; DropFx $FX_MFX
            }
        }
        DropFx $FX_DISABLE_ENHANCEMENTS
    }

    Dump "=== after ==="

    if (-not $NoServiceRestart) {
        Say "=== restarting audio engine ==="
        Stop-Service Audiosrv -Force -ErrorAction SilentlyContinue
        Stop-Service AudioEndpointBuilder -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 1500
        Start-Service AudioEndpointBuilder
        Start-Service Audiosrv
        foreach ($s in (Get-Service Audiosrv, AudioEndpointBuilder)) {
            Say ("  " + $s.Name + " = " + $s.Status)
        }
    }

    Say "DONE"
    exit 0
} catch {
    Say ("FAILED: " + $_.Exception.GetType().FullName + ": " + $_.Exception.Message)
    Say ($_.ScriptStackTrace)
    exit 1
}


