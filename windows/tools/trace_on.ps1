# trace_on.ps1 - turn on EqualizerAPO's trace log, restart the audio engine,
# play one 8-channel stimulus, and dump whatever audiodg wrote.
#
# EqualizerAPO's LogHelper reads HKLM\SOFTWARE\EqualizerAPO\EnableTrace once per
# process (defaults to on unless the value is "false"), and writes
# %TEMP%\EqualizerAPO.log. For audiodg that %TEMP% is LocalService's profile
# temp, not the interactive user's. The HKLM value cannot be written through
# PowerShell's HKLM: provider (it asks for KEY_ALL_ACCESS), so it goes through
# RegistryKey.SetValue with KEY_SET_VALUE only.
#
#   Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile',
#     '-ExecutionPolicy','Bypass','-File','trace_on.ps1'
param(
    [switch]$Off,
    [string]$Wav = (Join-Path $PSScriptRoot '..\work\stim8.wav'),
    [string]$Mpv = $(if ($env:MPV) { $env:MPV } else { 'mpv.exe' })
)
$ErrorActionPreference = 'Stop'
$log = Join-Path $PSScriptRoot 'trace_on.log'
function Say($m) {
    Write-Host $m
    Add-Content -Path $log -Value ([string]$m) -Encoding UTF8
}
Set-Content -Path $log -Value ("=== " + (Get-Date -Format 'u') + " off=" + [bool]$Off + " ===") -Encoding UTF8

Add-Type @"
using System;
using System.Security.AccessControl;
using Microsoft.Win32;

public static class Reg {
    static RegistryKey Open(string subkey, bool write) {
        var k = Registry.LocalMachine.OpenSubKey(subkey,
            write ? RegistryKeyPermissionCheck.ReadWriteSubTree
                  : RegistryKeyPermissionCheck.ReadSubTree,
            write ? (RegistryRights.SetValue | RegistryRights.QueryValues)
                  : RegistryRights.QueryValues);
        if (k == null) throw new Exception("no access: " + subkey);
        return k;
    }
    public static void SetString(string subkey, string name, string value) {
        using (var k = Open(subkey, true))
            k.SetValue(name, value, RegistryValueKind.String);
    }
    public static string GetString(string subkey, string name) {
        using (var k = Open(subkey, false)) {
            var v = k.GetValue(name, null);
            return v == null ? null : v.ToString();
        }
    }
}
"@

try {
    $val = if ($Off) { 'false' } else { 'true' }
    [Reg]::SetString('SOFTWARE\EqualizerAPO', 'EnableTrace', $val)
    Say ("EnableTrace = " + [Reg]::GetString('SOFTWARE\EqualizerAPO', 'EnableTrace'))

    $dirs = @(
        'C:\Windows\ServiceProfiles\LocalService\AppData\Local\Temp',
        'C:\Windows\ServiceProfiles\NetworkService\AppData\Local\Temp',
        'C:\Windows\System32\config\systemprofile\AppData\Local\Temp',
        'C:\Windows\Temp',
        $env:TEMP
    )
    foreach ($d in $dirs) {
        $f = Join-Path $d 'EqualizerAPO.log'
        if (Test-Path $f) {
            Remove-Item $f -Force -ErrorAction SilentlyContinue
            Say ("cleared " + $f)
        }
    }

    Say "=== restarting audio engine ==="
    Stop-Service Audiosrv -Force
    Stop-Service AudioEndpointBuilder -Force
    Start-Sleep -Milliseconds 1500
    Start-Service AudioEndpointBuilder
    Start-Service Audiosrv
    foreach ($s in (Get-Service Audiosrv, AudioEndpointBuilder)) {
        Say ("  " + $s.Name + " = " + $s.Status)
    }

    if (-not $Off) {
        Say "=== playing $Wav ==="
        $p = Start-Process -FilePath $Mpv -PassThru -ArgumentList `
            '--no-video', '--no-config', '--really-quiet', '--audio-channels=8', $Wav
        Start-Sleep -Seconds 3
        if (-not $p.HasExited) { $p | Stop-Process -Force }
        Start-Sleep -Milliseconds 1200
    }

    Say "=== logs ==="
    $found = $false
    foreach ($d in $dirs) {
        $f = Join-Path $d 'EqualizerAPO.log'
        if (Test-Path $f) {
            $found = $true
            $len = (Get-Item $f).Length
            Say ("--- " + $f + " (" + $len + " bytes) ---")
            Get-Content $f -ErrorAction SilentlyContinue | ForEach-Object { Say ("  " + $_) }
        }
    }
    if (-not $found) { Say "  (no EqualizerAPO.log anywhere)" }

    Say "DONE"
    exit 0
} catch {
    Say ("FAILED: " + $_.Exception.GetType().FullName + ": " + $_.Exception.Message)
    Say ($_.ScriptStackTrace)
    exit 1
}
