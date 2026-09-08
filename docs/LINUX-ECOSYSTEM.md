# The G6-on-Linux ecosystem — existing projects

*Survey date: this repo's analysis session. All projects verified live against
your exact firmware (2.1.250903.1324) unless noted.*

**Short answer: yes — there is an active, surprisingly mature ecosystem.**
Four projects control the G6 on Linux today, three of them actively
maintained in 2026. One already does **Direct Mode, SPDIF-direct, and 7.1
speaker/headphone configs** — the exact features from our Question C — plus
DAC filters and the full SBX suite. Our firmware-level findings corroborate
their protocol work and fill in the "why it works" for several open items
(see *What this repo adds* below).

---

## 1. `linuxblaster_control` — RizeCrime (Rust GUI)

<https://github.com/RizeCrime/linuxblaster_control> · MIT · 35★ · **active (Mar 2026)**

The deepest protocol work of the bunch. A native Rust GUI (GTK) with
AutoEq integration, state reading from the device, and per-output profiles
(the G6 keeps separate HP/speaker slots — matches our fw finding of the
268B/384B per-config shadow tables).

- **Best protocol doc**: `UsbProtocol.md` documents the exact transport —
  USB HID `SET_REPORT` on **interface 4** (`bmRequestType 0x21, bRequest
  0x09, wValue 0x0200, wIndex 0x04, wLength 0x40`), 64-byte zero-padded
  frames `5A CMD LEN PAYLOAD`, and the **Linux quirk: the interrupt-IN
  endpoint needs a `USBDEVFS_RESET` once per USB session** or the device
  won't respond. That detail alone un-blocks any Linux port.
- Full command family docs: `0x95` playback/routing, `0x96` SBX/EQ,
  `0x97` hardware, `0x39` Direct Mode, init handshake phases, and a
  `sniffer/` + `bitmask_sniffer.py` toolkit.
- Their honest note: earlier protocol docs (from the CLI project below)
  mislabeled device→host readbacks as host commands — v2 of their RE
  corrected it. Our fw disassembly confirms the split: e.g. `5a 1103` =
  device status response, `5a 1207` = host write (op 0x12 write /
  0x11 read + commit pattern).
- Direct Mode listed under "not planned" for their UI, but their protocol
  doc documents the frames (`0x39` sub 0x03/0x01) — implemented by the CLI
  project below.

## 2. `soundblaster-x-g6-cli` — Nils Skowasch (Python CLI)

<https://github.com/nils-skowasch/soundblaster-x-g6-cli> · GPL-2 · 33★ · **active (v1.1.0, Apr 2026)** · [PyPI](https://pypi.org/project/soundblaster-x-g6-cli/)

The most feature-complete controller, installable via `pipx install
soundblaster-x-g6-cli`. **Tested against firmware 2.1.250903.1324 — the
same build as the device analyzed in this repo.**

Already implements, over the vendor HID protocol:

- **`--playback-direct-mode {Enabled|Disabled}`** ← Direct Mode
- **`--playback-spdif-out-direct-mode`** ← SPDIF-Out Direct
- **`--playback-speakers-to-7-1` / `--playback-headphones-to-7-1`** (+5.1,
  stereo) ← the speaker-config switching (via USB AudioControl SET_CUR on
  the UAC feature units — the standard side, not vendor HID)
- **DAC filter selection** (fast/slow roll-off, min/linear phase)
- Full SBX suite: Surround/Crystalizer/Bass/SmartVolume/Dialog+ values and
  toggles, SBX profile switch (Gaming/Music/Cinema/Special)
- Recording: mic boost, noise reduction, AEC, smart volume, mic-EQ with
  presets, mic monitoring
- Mixer: per-input monitoring/recording volumes, What-U-Hear
- Lighting RGB, decoder modes (Normal/Full/Night)
- A `--claim-and-release` mechanism for the UAC-control commands (kernel
  must release the interface first) — clever handling of the two-interface
  split.

Their `doc/usb-spec.md` is a full hex-payload capture catalogue
(USBPAP/Wireshark from Sound Blaster Command) — including the Direct Mode
and SPDIF-direct frames, mic-EQ preset coefficient dumps, and per-volume-
percent volume words (0x00C0=0% … 0x0000=100% inverted scale, matching the
UAC feature-unit semantics).

## 3. `soundblaster-g6x-linux-controller` — dreamzone-cc (desktop app)

<https://github.com/dreamzone-cc/soundblaster-g6x-linux-controller> · GPLv3 (MIT upstream) · **active (v2.0.10, Feb 2026)**

A polished fork/rebuild of linuxblaster: native window (wry+tao) with a
SvelteKit dark-theme UI, tray, autostart, and packaging for **.deb,
AppImage, and Flatpak**. Supports **both G6 (041e:3256) and G6X
(041e:3263)**. SBX profiles, 10-band EQ with custom presets, mixer with
mute, per-channel volume.

## 4. `Sound-BlasterX-G6-Control` — xuda-ye-math (CLI + egui GUI)

<https://github.com/xuda-ye-math/Sound-BlasterX-G6-Control> · MIT · 1★ · **active (Aug 2026)** · AUR: `sound-blasterx-g6-control-git`

Rust workspace (`g6-core`/`g6-cli`/`g6-gui`), Arch-focused with a PKGBUILD.
JSON profile snapshots of all 28 features, OBS-style level meters, live EQ
response curve, tray mixer, autostart. Built (credited) in part with Claude
Code. **Roadmap explicitly includes a Direct Mode toggle** and notes the
sample-rate switch (96/192 kHz) command is not yet RE'd.

## Packaging

Both AUR packages exist: `sound-blasterx-g6-control-git` (project 4) and
`linuxblaster-control-git` (project 1).

---

## Coverage vs our findings

| Feature (from our RE) | lb_control | x-g6-cli | g6x-ctrl | G6-Control | Our repo |
| --- | --- | --- | --- | --- | --- |
| SBX suite (Surround/Cryst/Bass/SV/Dialog+) | ✅ | ✅ | ✅ | ✅ | protocol ref |
| 10-band EQ | ✅ | — (mic-EQ only) | ✅ | ✅ | protocol ref |
| Direct Mode (msg 90/1) | documented, UI "not planned" | ✅ | — | roadmap | **fw gate proven** |
| SPDIF-Out Direct (msg 90/9) | — | ✅ | — | — | **fw I2C regs proven** |
| Speakers/HP 7.1 config | — | ✅ (UAC) | — | — (48kHz note) | fw engine map |
| DAC filters (cmd 0x6c) | ✅ | ✅ | — | — | fw ladder |
| HRTF / SpeakersHRTFMode (msg 30) | — | — | — | — | **found + live-verified controllable** |
| RGB lighting | roadmap | ✅ | — | roadmap | fw handler map |
| Mic suite (AEC/NR/SVM/MicEQ) | — | ✅ | — | — | fw engine map |
| 96/192 kHz native clock | — | — | — | not RE'd | **fw clock ladder decoded** (÷256/512/768 + ±2304 jumps) |
| Feature-mask gate (0x5041B810) | — | — | — | — | **decoded + live-tested** (what's lockable vs rejected) |
| -2dBFS/SINAD root cause | — | — | — | — | **byte-identical fw proof** |

## What this repo adds to that ecosystem

1. **Firmware-level ground truth.** Their docs come from USB sniffing of
   the Windows app; ours comes from disassembling the device firmware
   itself. The two independently agree on the wire format — and our fw
   analysis explains *why* several things behave the way they do (the
   DATA/COMMIT split, the 0x95/0x96/0x97 register families = our
   op-149/op-150/op-151 engine, the per-output profile slots).
2. **The features nobody has yet**: SpeakersHRTFMode (we toggled it live,
   it's mask-enabled and app-hidden — a prime candidate to add to any of
   these tools), the 159-param Malcolm/SCP debug namespace, the 96 kHz
   clock-switch command location, and the feature-mask gate table (what
   will E_FAIL vs work).
3. **Direct Mode internals** — we prove Direct = firmware-side suppression
   of op-150 effect writes, not a DSP-mode switch. Useful for anyone
   debugging "why does Direct change X".
4. **The -2dBFS verdict** — device-inherent, never fixed, workaround
   = volume < 100%. Directly relevant to Linux users: set the G6 sink
   volume in PipeWire below 100% and you get the clean condition.

## Suggested synergies

- Port our `G6HidExplore` HRTF toggle (msg `5A 1E …`, one byte) into
  `soundblaster-x-g6-cli` and `linuxblaster_control` — smallest possible
  patch, immediately gives every Linux user the hidden feature.
- Our fw notes' clock-ladder decode (sub_20003DFC equivalent) is the
  missing piece for the 96/192 kHz native-rate goal on G6-Control's
  roadmap.
- The `sniffer/` work in linuxblaster + our firmware function map would
  let someone map the remaining 0x3a RGB subs cleanly.
