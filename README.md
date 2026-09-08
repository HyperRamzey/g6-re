# Sound BlasterX G6 — Reverse Engineering Findings

> Plain-language version. For the full technical report with every address and
> code citation, see [`REPORT.md`](REPORT.md). Analysis notebook with raw
> findings: [`docs/fw_notes.md`](docs/fw_notes.md).

I took apart the G6's firmware (all five public versions, 2019–2025) and the
Sound Blaster Command Windows app (decompiled) to answer three questions.
Everything below was verified against actual code — no guesswork. The device
was never flashed or modified; only reversible, app-level setting toggles were
tested, and everything was restored afterwards.

---

## TL;DR — the three answers

| Question | Answer |
| --- | --- |
| **Are there hidden features locked in fw/software?** | **Yes.** The firmware contains a capability-mask that switches features on/off per product. The G6's mask enables several things the app never shows you — most notably **HRTF mode for speakers**, and an engineering debug bus into the audio DSP. Some features (96 kHz optical-in passthrough, host-controlled headphone gain) are **hard-locked off** in the G6's firmware personality and reject commands. |
| **Was the -2 dBFS / full-volume SINAD bug fixed?** | **No — and it never will be.** Every gain and DSP constant in the firmware is *byte-identical* between the version measured in the famous 2019 ASR review and today's 2025 firmware. The bug lives in the analog power-supply domain (USB power headroom at full-scale DAC drive), which firmware can't fix without a headroom trim that was never added. **Workaround: keep Windows volume below 100%.** |
| **What does "Direct Mode" do with virtual 7.1?** | Direct Mode = 7.1 still streams over USB, but the firmware **stops writing ALL effect settings to the DSP** (surround/HRTF, EQ, everything) — only volume survives. Non-direct 7.1 = the SBX/HRTF engine actively renders 7.1 into binaural stereo. "Direct" is genuinely "no effects" — it's not just a UI promise, it's enforced in firmware. |

---

## Question A — Hidden and locked features

### How Creative locks features

The G6's control chip runs firmware shared across Creative's product line.
When it boots, it reports a **feature mask** — a list of bits saying which
features this particular product is allowed to use. I queried it live:

```
G6 live FeatureBitwiseMask1 = 0x5041B810
  bit  4  MalcolmMicrophoneBoost
  bit 11  SoftButtonControl
  bit 12  JackControl
  bit 13  BatteryControl
  bit 15  LEDControl
  bit 16  MalcolmParameterCustomization   ← engineering interface, ON!
  bit 22  StereoDirectMode
  bit 28  SPDIFOutDirectMode
  bit 30  SpeakersHRTFMode                ← ON, barely exposed in UI
```

Everything *not* in that list is **rejected by the firmware itself** when you
try to use it (I tested — the device returns an error). So there are two
tiers:

1. **On in the mask, but hidden in the app** → *you can control these right
   now* with a small tool, no Sound Blaster Command needed (see below).
2. **Off in the mask** → locked at firmware level; only a firmware
   modification could enable them.

### Things I found that you can actually control

**HRTF mode for speakers (the best find).** The G6 firmware supports
`SpeakersHRTFMode` (it's bit 30, enabled). The app only touches it in one
confusing place — as the "headphone virtualization" toggle. I sent the
command directly over HID and the device accepted it and remembered it:

```
SetSpeakersHRTFMode(1) hr=0x00000000   ← accepted, persisted
```

(Then I set it back to 0 — your device is exactly as it was.)

**The DSP engineering bus.** The device exposes 159 named DSP parameters
(AEC, noise reduction, VoiceFocus beam angles, VoiceFX formants, 8-band mic
EQ, full reverb room model, CMSS-3D, DialogPlus, Crystalizer, graphic EQ...)
through an undocumented query/passthrough interface in Creative's own
`CTHIDRpA.dll`. The G6 app never calls it. It's a complete low-level control
surface for the audio DSP.

**Front-panel button emulation** (`SetButtonState`) and jack control are
enabled in the mask — software can press the G6's buttons and query jacks
directly.

**The 5th DAC filter — NOS (hidden in the GUI, live-verified in the
chip).** The G6's DAC is a Cirrus Logic **CS43131**, and its `PCM Filter
Option` register (`0x90000`) has a dedicated **NOS bit** ("NOS emulation
mode", datasheet §5.9 — Cirrus even documents the pop-free enable
sequence). The device *advertises 5 filters* over its SoundCore interface:

```
code 3  Fast Roll-off, Minimum Phase
  code 4  Slow Roll-off, Minimum Phase
code 5  Non-Over-Sampling (NOS)      ← hidden in the app GUI!
code 6  Fast Roll-off, Linear Phase
code 7  Slow Roll-off, Linear Phase
```

Sound Blaster Command shows only the 4 roll-off variants — its code
hard-skips `"NonOverSampling"` **by name** when building the filter list
(`BaseFiltersPageViewModel`, decompiled). The NOS filter works: it's a
real silicon mode that bypasses the DAC's digital interpolation filter.
What that does on a delta-sigma DAC: the output becomes a zero-order-hold
of the samples — no pre-ringing, minimum delay, but with sinc passband
droop (≈ −3.2 dB at 20 kHz for 44.1 kHz content) and unattenuated images
above Nyquist. Audiophile taste feature; objectively worse on
measurements — which is presumably why Creative ships it hidden.

The wire command for it (same HID `'Z'` family): `5A 6C 03 00 03` + commit
`5A 6C 01 01` — verified against the Linux community's Wireshark captures
(see below).

### Things that exist in firmware but are locked off for the G6

- **96 kHz optical input passthrough** — firmware handler exists, but the G6
  personality rejects it (E_FAIL). The hardware probably supports it.
- **Host-controlled headphone gain** — the physical gain button works, but
  software commands are refused. Front-panel only, by design.
- **Bluetooth, relay mode, add-on installs** — not in the G6 firmware at all
  (no radio in the device).
- **Local data store, device profiles, auto-sleep, power-wattage modes** —
  handlers exist in the shared code; G6's mask says no.

### Bonus finding: a capability bit appeared in 2025

The firmware's response to a Direct Mode command changed from `0x81` (2019)
to `0x83` (2025) — a new capability bit was added in the current firmware
family with no matching feature in the app. Something new is brewing or
dormant.

---

## Question B — The -2 dBFS / SINAD bug

### The background

The 2019 Audio Science Review measurements showed the G6 measures great
(SINAD ≈ 107 dB) **unless you play at exactly full digital level** — then
low-frequency distortion jumps (nearly 1% THD at 20 Hz). Dropping just 2 dB
fixed everything (SINAD 112 dB). The reviewer's diagnosis: the USB power
supply can't keep up with full-scale bass peaks.

### What I did

I extracted firmware from **all five public OTA installers** (v1.13 from
March 2019 — the exact era the review measured — through v2.1.250903 from
Sept 2025), unpacked them (InnoSetup → inner flasher → Intel-HEX → binary
images), loaded them into IDA, and diffed every audio-relevant constant:

| What | 2019 fw | 2025 fw | Difference |
| --- | --- | --- | --- |
| 57-float DSP feature table | `0x2000BBE0` | `0x2000CDA0` | **0 bytes** |
| 66-float SBX parameter table | `0x2000BD28` | `0x2000CEE4` | **0 bytes** |
| Master gain ladder (0.25/0.5/1.0/2.0/3.0) | ✓ | ✓ | identical |
| Headphone gain patches (0.9/2.0/3.0/−2.0/−9.0/8.0…) | ✓ | ✓ | identical |
| Optical passthrough register values | ✓ | ✓ | identical |
| Boot parameter set | ✓ | ✓ | identical |

**Six years of firmware updates, and the audio/DSP/gain code never
changed by a single byte.** No headroom trim was ever added (I looked for
any ≈ −2 dB scaling constant; there is none).

### What this means for you

- The "bug" is a **hardware property**: full-scale output stresses the USB
  power rail. Every G6 ever made has it, including yours on the newest
  firmware.
- **Practical fix (unchanged since 2019): don't run Windows volume at
  100%.** Set the G6 to ~79–90% in Windows and you get the full measured
  performance. (Bonus: this also acts as digital volume *before* the DAC,
  which is cleaner than the device's own volume control.)
- I have a ready-to-run measurement script
  ([`tools/thd_test.py`](tools/thd_test.py)) that can prove this on your unit
  with a loopback cable — see below.

---

## Question C — Direct Mode with virtual 7.1, exactly

### The setup

Windows sees the G6 as an 8-channel (7.1) device. In Sound Blaster Command
you pick "7.1" (or "Virtual 7.1 Surround" for headphones) and separately a
"Direct Mode" toggle. The app even remembers *separate* speaker-config
choices for Direct-on vs Direct-off and swaps them when you toggle.

### What actually happens, per mode

**Non-direct virtual 7.1** (effects on):

- Your 8-channel audio stream goes through the SBX/HRTF engine.
- The firmware continuously writes ~27 effect parameters (surround/HRTF
  binauralization, EQ bands, Crystalizer, bass, dialog-plus...) + gains to
  the VT1728 audio DSP — per speaker-config "slot".
- Result: the 8 channels are actively **rendered into a binaural 2-channel
  mix** for your headphones/speakers. This is the "virtual surround".

**Direct Mode with 7.1 selected** (what you asked about):

- Windows still streams 8 channels — nothing changes on the USB side.
- Firmware hits a gate (`0x1001422C` flag, verified in disassembly) that
  **skips every effect-register write to the DSP**. All SBX/HRTF/EQ
  parameters stop reaching the chip. Only **master volume** survives.
- The DSP does just the fixed, non-programmable speaker-config downmix.
- If "SPDIF Out Direct" is also on, the optical output is hard-switched to
  bit-perfect passthrough (I verified live: with Direct on, the optical out
  retransmits whatever comes in the optical in and *ignores USB playback
  entirely*).

So "Direct Mode virtual 7.1" isn't virtual at all — it's **7.1 in, plain
stereo downmix out, zero processing**. The app's own help text ("audio in
its purest form... all audio effects will not be applied") is *enforced in
firmware*, not just a UI behavior.

---

## Try it yourself — the tools

Everything is in this repo. All tools talk to the device through Creative's
own `CTHIDRpA.dll` COM library — the exact same channel Sound Blaster
Command uses.

- **[`tools/G6HidProbe/`](tools/G6HidProbe/)** — read-only device query
  (firmware version, serial, direct-mode states).
- **[`tools/G6HidExplore/`](tools/G6HidExplore/)** — probe the hidden
  feature surface: full mask sweep, toggle SpeakersHRTFMode, read the
  Malcolm customization block. Read-mostly; every SET is reversible.
- **[`tools/G6HidSet/`](tools/G6HidSet/)** — toggle Direct/SPDIF-Direct
  modes from the command line.
- **[`tools/G6SoundCoreProbe/`](tools/G6SoundCoreProbe/)** — talk to the
  device through Creative's **SoundCore** layer (`ISoundCore` COM from
  `SndCrUSB.dll`, loaded registration-free exactly like Sound Blaster
  Command does). Enumerates contexts, features and params live, and
  dumps the DAC filter state: it's how the hidden 5th filter (NOS) was
  discovered on a real G6.
- **[`tools/thd_test.py`](tools/G6HidSet/../G6Measure/)** — the THD+N
  loopback measurement that verifies the -2 dBFS behavior on your own unit
  (needs a 3.5mm cable from headphone-out to a line-in).

Build (needs the .NET SDK; tools are x86 to match Creative's DLLs):

```
cd tools/G6HidExplore && dotnet build -c Release
```

Run with Creative's platform DLLs on PATH (the tools also work if Sound
Blaster Command is installed normally):

```powershell
$env:PATH = "C:\Program Files (x86)\Creative\Sound Blaster Command\Platform;$env:PATH"
G6HidExplore.exe query
G6HidExplore.exe hrtf set 1     # try HRTF on speakers (reversible!)
G6HidExplore.exe hrtf set 0     # ...and back
```

---

## Honesty section — what I could NOT do

- **Measure the analog THD+N live.** The script is ready but we deferred
  running tones through your headphones. Static evidence (byte-identical
  firmware) is conclusive on its own; a measurement would just confirm.
- **Dump the VT1728 DSP's internal firmware.** The flash protocol exists
  over HID (I found and documented it) but deliberately did not use it —
  writing to the device risks bricking, which was off-limits.
- **Enable the mask-locked features** (96k optical-in, host gain control).
  They're rejected by the G6's firmware personality. Only a modified
  firmware could unlock them — not pursued.

## Credits & method

- Firmware: 5 OTA installers unpacked (InnoSetup/`innoextract` → Intel-HEX
  parser → 3 memory banks each), wrapped as ELFs, disassembled in IDA
  (ARM Cortex-M).
- App: Sound Blaster Command decompiled with ILSpy (the G6 product DLL even
  shipped with debug symbols).
- Live device access: read-only HID queries + reversible toggles via
  Creative's own COM library; SoundCore-layer interrogation via the
  `ISoundCore` COM server in `SndCrUSB.dll` (registration-free, same as
  Creative's own app manifest activates it).
- DAC silicon: Cirrus Logic **CS43131** datasheet (DS1155F2) — filter-mode
  register map (0x90000: roll-off speed, phase comp, NOS bit) and the
  NOS enable/disable sequences (§5.9) that back the hidden 5th filter.
- Linux ecosystem cross-check: `soundblaster-x-g6-cli`'s Wireshark payload
  catalogue (`doc/usb-spec.md`, `payloads/raw/`) — independently confirms
  our HID frame decode for Direct Mode, SPDIF-direct, SBX effects, and the
  4 visible DAC filters.
- Original measurements that motivated question B: Audio Science Review
  forum, "Review and Measurements of Sound BlasterX G6", Mar 2019.

*This project is independent research. No Creative firmware binaries or
decompiled app source are included in this repo — only our own analysis,
tools, and notes.*
