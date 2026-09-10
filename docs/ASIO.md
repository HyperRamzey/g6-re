# The G6's ASIO driver — fully decoded, and a sample-based-latency patch

The Sound BlasterX G6 ships with **Creative USB Native ASIO v1.1.3.0**
(`CtUsAs64.dll`, registered as `Creative Sound Blaster ASIO`).
We reversed it completely in IDA and live-probed it with a minimal ASIO host
([`tools/G6AsioProbe/`](../tools/G6AsioProbe/)). This page answers the two
classic complaints — "multichannel doesn't work" and "latency is in
milliseconds, not samples" — with code-level proof, and ships a
**reversible per-user patch** that gives every ASIO host a proper
sample-quantized buffer-size dropdown.

## Architecture (where ASIO sits in the G6 stack)

```
ASIO host (DAW)
  └─ CoCreateInstance({B2D4D5A2-1B17-4AB6-8A6D-667095C480B2})   ← ThreadingModel=Apartment
       └─ CtUsAs64.dll  CAsio (ATL, "IDD_ASIOCP_MALCOLM" control panel)
            └─ CKsFilter/CKsPin (SetupDi → DeviceInterfaceAlias → KsCreatePin)
                 └─ ksusba64.sys  (the same KSUSB driver this project documents)
                      └─ USB Audio streaming interface (MI_00) → VT1728/CS43131
```

So the ASIO layer is a thin KS wrapper — **no USB/HID protocol of its own**.
Everything the device supports is reachable through it, subject only to what
the KS pin exposes for the current speaker configuration.

## Multichannel: it already works — the catch is the speaker config

Live probe results on a G6 in 7.1 mode:

```
getChannels() -> inputChannels=2 outputChannels=8
  OUT ch0..1 "Front L/R"     type=Float32LSB
  OUT ch2..3 "Rear L/R"
  OUT ch4..5 "Center/Sub"
  OUT ch6..7 "Side L/R"
  IN  ch0..1 "Audio-In L/R"
createBuffers(10 channels) -> OK, start/stop of 8-ch silence -> OK
```

The channel count is read from the KS render pin's dataranges, which
`ksusba64.sys` derives from the **speaker configuration**:

```
HKLM\SYSTEM\...\USB\VID_041E&PID_3256&MI_00\...\Device Parameters\KSAud_Device
    SPeakerConfig = 0x63F      (KSAUDIO_SPEAKER_7POINT1_SURROUND)
```

**If your DAW only shows stereo:** the G6 was last set to 2.0 in Sound
Blaster Command. Switch it to 7.1 there (or with any Linux HID tool) and the
ASIO driver immediately exposes 8 channels. There is no firmware lock — the
8-channel path is the same virtual-7.1 stream described in
[`REPORT.md` §C](REPORT.md#c--direct-mode--virtual-71-the-full-mechanism).

One nuance for Direct Mode users: with Direct/StereoDirect active the device
itself downmixes to 2.0 — the ASIO layer will still show 8 channels (the KS
pin format is unchanged), but 6 of them are folded by the DSP. For *true*
8-channel ASIO use, leave Direct off.

## Latency: why your DAW shows milliseconds

The driver's entire buffer model is **millisecond-quantized**:

- `HKCU\Software\Creative Tech\CtUsAsio\Latency` — a DWORD holding one of 13
  hardcoded values (`{1,2,4,5,6,8,10,20,40,50,60,80,100}` ms — table at
  `0x427A08`), written by the ASIO control panel (`IDD_ASIOCP_MALCOLM`).
- `ASIOgetBufferSize` (`sub_409F28`) computes `preferred = rate × ms / 1000`
  and then reports **min = max = preferred, granularity = 0** — the tail at
  `0x40A037` copies the preferred size over min and max and zeroes the
  granularity. Hosts therefore hide the block-size dropdown and display
  latency in ms (their only remaining unit).
- `ASIOgetLatencies` just returns the buffer size for both directions
  (single-buffer model).

We also found the reason reported latencies looked *absurd* on this machine:
the same registry key `SampleRate` (a raw **double**) had been left at
**384000.0 Hz** by some earlier run, so `getBufferSize` reported
`min=max=pref=19200, granularity=0` — a perfect 50 ms… at a rate the G6
doesn't stream. Clearing it via the driver's own `setSampleRate(48000)`
immediately restored sane numbers (2400 samples = 50 ms @ 48 kHz).

### The interesting part: `createBuffers` accepts ANY size

The ms-check in `sub_40BAB8` (called at the top of `createBuffers`) looks
like a gate — but its return value is **discarded** (verified at the
disassembly level: `call sub_40BAB8` at `0x40A480` flows straight into the
next call with no `test`/branch). It only fires advisory callbacks
(`sampleRateDidChange`, `kAsioOverload`, `kAsioBufferSizeChange`,
`kAsioResetRequest`) and proceeds with the host's requested size.

So the sample-quantization exists **only in what getBufferSize reports**.
That's all a patch needs to change.

## The patch: sample-based latency (per-user, reversible)

[`tools/G6AsioProbe/patch_asio.py`](../tools/G6AsioProbe/patch_asio.py)
builds `CtUsAs64_patched.dll` from the stock driver:

1. **Rebinds the COM CLSID** `{B2D4D5A2-…}` → `{8F5E2A31-…}` (6 occurrences,
   including the ATL object map) so the copy can be registered **per-user**
   alongside the stock driver — zero system files touched, no admin needed.
2. **Patches 12 bytes** in the `getBufferSize` tail (file offset `0x9437`):

   | | bytes | effect |
   | --- | --- | --- |
   | stock | `41 8B 09 41 89 08 89 0B 41 83 23 00` | min=max=preferred, granularity=0 |
   | patched | `41 C7 03 08 00 00 00 90 90 90 90 90` | `mov dword [r11],8` + nops — skips the overwrite, sets granularity=8 |

Live-verified result at 48 kHz / 50 ms setting:

```
stock   : min=2400  max=2400  preferred=2400  granularity=0
patched : min=48    max=4800  preferred=2400  granularity=8
```

Hosts now get the full 1–100 ms range as a sample dropdown (48 → 4800 in
steps of 8: 64, 128, 256, 512, 1024…). We verified `createBuffers` at 128
samples (2.67 ms), at 33 samples (odd — works, but 8-aligned sizes are
saner for the KS allocator), and at 4800 — all created and disposed cleanly
on the real device, 10 channels (2 in + 8 out) at Float32LSB.

### Install / uninstall

```powershell
# build the patched copy from the stock driver
python tools/G6AsioProbe/patch_asio.py `
  "C:\Program Files (x86)\Creative\Creative USB Native ASIO\CtUsAsio\amd64\CtUsAs64.dll" `
  "$env:LOCALAPPDATA\CtUsAs64_patched.dll"

# register per-user (no admin)
$clsid = "{8F5E2A31-6C74-4B9E-9D3A-2E7F5A6B8C90}"
reg add "HKCU\Software\Classes\CLSID\$clsid\InprocServer32" /ve /d "$env:LOCALAPPDATA\CtUsAs64_patched.dll" /f
reg add "HKCU\Software\Classes\CLSID\$clsid\InprocServer32" /v ThreadingModel /d "Apartment" /f
reg add "HKCU\Software\ASIO\G6 ASIO (sample-based patch)" /ve /d "G6 sample-based ASIO" /f
reg add "HKCU\Software\ASIO\G6 ASIO (sample-based patch)" /v CLSID /d "$clsid" /f
reg add "HKCU\Software\ASIO\G6 ASIO (sample-based patch)" /v Description /d "Creative Sound Blaster ASIO (sample latency patch)" /f

# pick "G6 ASIO (sample-based patch)" in your DAW's ASIO driver list

# uninstall: delete the two HKCU keys (or run reg delete as below)
reg delete "HKCU\Software\ASIO\G6 ASIO (sample-based patch)" /f
reg delete "HKCU\Software\Classes\CLSID\$clsid" /f
```

### Notes and caveats

- **getLatencies** still reports the preferred-size for both directions
  (the patch only touches the reported *range*; the driver's internal
  single-buffer model is untouched). At non-preferred sizes your DAW's
  displayed ms is computed from the actual buffer/rate, which is now
  consistent since we cleared the stale 384 kHz registry value.
- The patch is built for `CtUsAs64.dll` v1.1.3.0 (the file your driver
  package installs); the script asserts the original byte pattern before
  patching and refuses anything else.
- Bit depth: the control panel's 16/24 choice sets the **KS pin** format
  (16-bit int, or 24-in-32). The host always sees Float32LSB either way —
  the driver converts. 32-bit hosts are unaffected by that registry value.
- `SampleRate` (HKCU, a raw double) is written by `setSampleRate` through
  any host; if a host ever leaves a bogus value (as we found 384000.0),
  one `setSampleRate(48000)` fixes it permanently.
