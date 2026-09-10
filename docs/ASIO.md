# The G6's ASIO driver — fully decoded, and a raw-sample latency patch

The Sound BlasterX G6 ships with **Creative USB Native ASIO v1.1.3.0**
(`CtUsAs64.dll`, registered as `Creative Sound Blaster ASIO`).
We reversed it completely in IDA and live-probed it with a minimal ASIO host
([`tools/G6AsioProbe/`](../tools/G6AsioProbe/)). This page answers the two
classic complaints — "multichannel doesn't work" and "latency is in
milliseconds, not samples" — with code-level proof, and ships a
**reversible per-user patch** that turns the driver's whole latency model
into raw samples, with a **one-click installer**.

## One-click installer (recommended)

Grab `g6-asio-install.exe` from the
[releases](https://github.com/HyperRamzey/g6-re/releases) page and run it:

- locates your stock `CtUsAs64.dll` v1.1.3.0 and verifies every patch site
- writes the patched copy to `%LOCALAPPDATA%\Creative\G6AsioPatch\`
- seeds `LatencyS = 256` samples
- registers the per-user COM class + `HKCU\Software\ASIO` entry (no admin)
- asks **one** UAC prompt to add the `HKLM\SOFTWARE\ASIO` entry — this is
  what makes Nuendo/Cubase see the driver (they enumerate HKLM only)
- offers to add a **logon self-heal** (silent, no UAC) that re-asserts the
  patch if a registry cleaner or Creative update wipes it
- `--uninstall` removes everything; the stock driver is never touched

The installer is a single self-contained C file
([`tools/G6AsioProbe/g6asio-install.c`](../tools/G6AsioProbe/g6asio-install.c)),
built with clang ThinLTO + `-O3 -march=x86-64-v2`. It embeds only the patch
*data* (offsets + byte diffs), never Creative's binary — it reads the stock
driver from your own machine, so nothing of Creative's ships in this repo.

## What the v4 patch changes (the raw-sample model)

The stock driver stores latency as integer **milliseconds**, which made
power-of-two buffer sizes (128/256/512 samples) physically unreachable
(256 samples = 5.33 ms). v4 switches the model to raw samples:

- **New 16-entry sample table** (in the `.rsrc` padding, VirtualSize extended
  so the loader maps it):
  `48, 96, 128, 192, 256, 320, 384, 512, 640, 768, 1024, 1536, 2048, 3072, 3840, 4800`
- **Registry**: the driver now reads/writes `LatencyS` (REG_DWORD = raw
  samples) instead of `Latency` — the stock key is left untouched, so
  uninstalling restores stock behavior with its own setting intact.
- **`getBufferSize`**: `min = max = preferred = LatencyS` (raw), granularity
  `16`. DAWs get a sample-quantized dropdown; any 16..4800 multiple works
  via `createBuffers` (verified at 128/256/512).
- **Panel**: the combobox lists the sample table directly ("`%d samples`",
  16 entries); the save path stores raw samples; the ms→samples conversion
  cave from v3 is gone — the table *is* samples now.
- **Advisory gate neutered**: the stock `createBuffers` ms-check
  (sub_40BAB8) fired `kAsioResetRequest` spam whenever a host picked a
  non-preferred size (the result was always discarded, but the side effects
  weren't). v4 makes the gate never fire.
- **CLSID rebinding** `{B2D4D5A2-…}` → `{8F5E2A31-…}` as before, so the
  patched copy registers per-user alongside the stock driver.

Live-verified on a real G6 (Nuendo 15.0.30 x64):

```text
getChannels    : 2 in / 8 out (7.1 speaker-config dependent)
getBufferSize  : min=256 max=256 preferred=256 granularity=16
getLatencies   : 256 / 256 samples
createBuffers  : OK at 128, 256, 512 samples (10 channels)
registry       : LatencyS = 256 (REG_DWORD, raw samples)
```

The equivalent Python implementation is
[`tools/G6AsioProbe/patch_asio.py`](../tools/G6AsioProbe/patch_asio.py) — it
asserts all 17 stock byte patterns before patching and produces a
byte-identical DLL (the C installer's output is SHA-256-matched to it).

### Multichannel: works, and always did — the catch is device config

The ASIO layer exposes whatever the KSUSB render pin advertises, which
follows the **speaker config**: `KSAud_Device\SPeakerConfig = 0x63F` (7.1)
→ 8 output channels (`Front/Rear/Center-Sub/Side L/R` names auto-assigned in
sub_40B2B0) + 2 inputs. If your DAW shows stereo, switch the G6 to 7.1 in
Sound Blaster Command first. In Direct Mode the device downmixes internally
— leave Direct off for true 8-channel ASIO. Channel names, the WFX masks
(0x3/0x3F/0x63F in sub_40E11C), and 10-channel `createBuffers` verified live.

### The stock latency model (what the patch replaces)

`getBufferSize` reported `min = max = preferred` derived from a 13-entry
**ms** table (`1,2,4,5,6,8,10,20,40,50,60,80,100` @0x427A08) with
`granularity=0` — hosts got one fixed buffer size, displayed in ms, and a
stale `SampleRate=384000.0` in the registry made reported latencies
nonsense. `createBuffers` itself never rejected sizes (the ms-check's
return is discarded at the disassembly level — proven at `0x40A480`), which
is what made both the v3 and v4 patches safe.

## Why Nuendo/Cubase need the HKLM entry (disassembly-proven)

Nuendo's ASIO host component is `baios.dll`. Full discovery map from IDA:

| baios.dll function | What it does |
| --- | --- |
| `sub_180006FC0` | top-level discovery: ① scan `C:\Program Files\Common Files\ASIO3\*.dll`, ② `sub_1800079A0` |
| `sub_1800079A0` | `RegOpenKeyW(HKEY_LOCAL_MACHINE, "SOFTWARE\\ASIO")` — **HKLM only, no HKCU enumeration anywhere** |
| `sub_180008030` | per entry: required `CLSID` value, optional `Description` (falls back to key name) |
| `sub_180007CC0` | validates the CLSID via `HKCR\CLSID\<clsid>\InprocServer32` (merged view — per-user classes visible), then `sub_180007C30` checks the DLL file exists |

So an ASIO entry registered only under `HKCU\Software\ASIO` is invisible to
Nuendo/Cubase by design. The **COM class stays per-user** (HKCR merges it);
only the enumeration entry must live in HKLM — that's the single UAC prompt
in the installer. `tools/G6AsioEnum/` reproduces this discovery path
programmatically if you want to check what Nuendo sees.

## Manual install (equivalent to the installer)

```powershell
# build the patched copy from the stock driver (byte-identical to the installer's)
python tools/G6AsioProbe/patch_asio.py `
  "C:\Program Files (x86)\Creative\Creative USB Native ASIO\CtUsAsio\amd64\CtUsAs64.dll" `
  "$env:LOCALAPPDATA\Creative\G6AsioPatch\CtUsAs64_patched.dll"

$clsid = "{8F5E2A31-6C74-4B9E-9D3A-2E7F5A6B8C90}"
reg add "HKCU\Software\Classes\CLSID\$clsid\InprocServer32" /ve /d "$env:LOCALAPPDATA\Creative\G6AsioPatch\CtUsAs64_patched.dll" /f
reg add "HKCU\Software\Classes\CLSID\$clsid\InprocServer32" /v ThreadingModel /d "Apartment" /f
reg add "HKCU\Software\Creative Tech\CtUsAsio" /v LatencyS /t REG_DWORD /d 256 /f

# REAPER-style hosts (HKCU enumeration)
reg add "HKCU\Software\ASIO\G6 ASIO (sample-based patch)" /ve /d "G6 sample-based ASIO" /f
reg add "HKCU\Software\ASIO\G6 ASIO (sample-based patch)" /v CLSID /d "$clsid" /f
reg add "HKCU\Software\ASIO\G6 ASIO (sample-based patch)" /v Description /d "Creative Sound Blaster ASIO (sample latency patch)" /f

# Nuendo/Cubase (HKLM enumeration; admin console)
reg add "HKLM\SOFTWARE\ASIO\G6 ASIO (sample-based patch)" /ve /d "G6 sample-based ASIO" /f
reg add "HKLM\SOFTWARE\ASIO\G6 ASIO (sample-based patch)" /v CLSID /d "$clsid" /f
reg add "HKLM\SOFTWARE\ASIO\G6 ASIO (sample-based patch)" /v Description /d "Creative Sound Blaster ASIO (sample latency patch)" /f

# optional logon self-heal (silent, no UAC):
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v G6AsioPatch /t REG_SZ /d "\"C:\path\to\g6-asio-install.exe\" --silent" /f

# uninstall:
#   reg delete "HKLM\SOFTWARE\ASIO\G6 ASIO (sample-based patch)" /f
#   reg delete "HKCU\Software\ASIO\G6 ASIO (sample-based patch)" /f
#   reg delete "HKCU\Software\Classes\CLSID\$clsid" /f
#   reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v G6AsioPatch /f
#   del "$env:LOCALAPPDATA\Creative\G6AsioPatch\CtUsAs64_patched.dll"
```

## Notes and caveats

- The patch is built for `CtUsAs64.dll` v1.1.3.0; the installer and script
  assert the original byte pattern at every site and refuse anything else.
- **getLatencies** reports the current preferred size both directions (the
  stock single-buffer model); at other sizes your DAW computes ms from the
  actual buffer/rate.
- Bit depth: the panel's 16/24 choice sets the **KS pin** format (16-bit
  int, or 24-in-32); hosts always see Float32LSB — the driver converts.
- `SampleRate` (HKCU, a raw double) is written by `setSampleRate` through
  any host; if a host leaves a bogus value (we found 384000.0 once), one
  `setSampleRate(48000)` through any host fixes it permanently.
- The v3→v4 development history (including two crashes we caught by
  re-verifying the built DLL in IDA before/after deploy — the rel32
  position-dependence lesson and the `#UD` leftover-byte lesson) is in
  `docs/fw_notes.md`.
