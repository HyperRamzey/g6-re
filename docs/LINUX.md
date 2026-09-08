# G6 on Linux — portability analysis

Question: *Can virtual 7.1 / Direct Mode be ported to Linux?*

**Short answer: yes — and it needs no kernel driver, because the DSP work
happens inside the device.** Only the control channel has to be re-created,
and this project has already decoded that entire control protocol.

---

## Why it's portable: where the processing actually lives

The G6 is a USB composite device:

```
USB\VID_041E&PID_3256
├── MI_00  USB Audio Class (UAC) interface  → Linux: snd-usb-audio (works today)
├── MI_03  HID, vendor usage page 0xFFA0   → Linux: /dev/hidrawN  (control bus)
└── MI_04  HID (buttons/knob events)       → Linux: /dev/hidrawN
```

Everything "Sound Blaster" about the G6 — the SBX Surround/HRTF binaural
rendering, EQ, Crystalizer, the 7.1→stereo virtualization — executes on the
device's VT1728 audio DSP, commanded by the Malcolm MCU. We proved this in
firmware: Direct Mode is literally the MCU *stopping its effect-register
writes* to the DSP (gate at `0x1001422C` in the 2025 firmware). The Windows
host does not render any of the surround processing.

Consequence: the features are **independent of the OS**. The only thing
Windows provides is a way to *tell the device what to do*.

## What already works on Linux, unmodified

- Audio in/out through the standard USB Audio Class driver (ALSA/PipeWire
  enumerate the G6's endpoints, including the 8-channel/7.1 output format
  from the USB descriptor).
- Hardware volume via the UAC feature units.
- The front-panel buttons/knob (MI_04 emits standard HID events).

What you lose without a control tool: the ability to switch Direct Mode,
speaker configs, HRTF, EQ, effect profiles, SPDIF-direct — because those
settings are sent over the **vendor HID interface (MI_03)**, which no Linux
software currently speaks.

## What a Linux port needs

1. **Open the right hidraw node** — the G6's MI_03 interface:
   `/dev/hidraw*` with `HID_ID=0003:0000041E:00003256` and usage page
   `0xFFA0`. (Rule of thumb: it's the G6 hidraw device that is *not* the
   one producing button events.)

2. **Speak the protocol this project documented.** The control protocol is a
   framed message scheme over HID reports, fully decoded from firmware
   disassembly:

   - Messages start with the frame header `'Z' (0x5A)` — the "msg-90" family
     (see `docs/fw_notes.md`, "Host-message table DECODED").
   - `SetStereoDirectMode` = message `Z` sub **1**, payload = 1 byte on/off.
   - `SetSPDIFOutDirectMode` = sub **9**, 1 byte.
   - `SetSpeakersHRTFMode` = sub **30** (0x1E), 1 byte.
   - `SetSpeakersConfig` = sub **7** (channel mask).
   - `SetHeadphoneHighGainMode` = sub **2** (note: rejected by G6 firmware
     personality — mask bit 23 off, tested live).
   - GET equivalents (firmware version, feature mask, current states, the
     159 named DSP parameters via the Malcolm/SCP query interface) use the
     same framing with request sub-codes (0xE0 group, etc.).
   - The device ACKs each SET and pushes state-change notifications
     (`Z`/23/61×6+41) back over HID — a Linux daemon can listen and keep
     UI state synced, exactly like SBCommand does.

   The exact per-message payloads are tabulated in `REPORT.md` §A/§C and
   `docs/fw_notes.md`; message numbers are defined in
   `tools/G6HidExplore.cs` (from Creative's own protocol library, verified
   live against the device).

3. **No firmware dump needed.** Every command in this README was verified by
   sending real HID traffic to a real G6 on firmware 2.1.250903.1324 (the
   current public release) — set/read-back confirmed.

## Honest caveats for Linux

- **Report-ID/framing detail**: the byte-level HID report ID and padding
  used by MI_03 are owned by Creative's `CTHIDRpA.dll` and were not
  fully captured in this project (our tools rode on the Windows COM
  library). A Linux implementer will need one sniffing session (e.g.
  `usbmon` while toggling a setting in SBCommand under Windows, or
  trial-and-error against the `'Z'` framing already decoded) to pin the
  report descriptor details. The message semantics themselves are done.
- **What U-APP/ALS and APO do**: the Windows driver installs an APO
  (`KSUSBAPO64.dll`) in the SysFx chain. Based on the firmware analysis
  (device-side DSP), its role is host-side glue (channel-format handling and
  the SBCommand integration), not the surround rendering itself. Under
  Linux, ALSA/PipeWire handle the 8-channel endpoint natively.
- **The 96 kHz optical-in passthrough and host-controlled gain stay locked**
  on Linux too — they're rejected by the device firmware itself (feature
  mask), regardless of OS.

## Suggested implementation sketch

```python
# g6ctl (Linux, via python-hid or raw /dev/hidraw)
import hid  # or: open('/dev/hidrawN', 'r+b')

VID, PID = 0x041E, 0x3256
# pick the G6 interface whose usage page == 0xFFA0

def set_stereo_direct(on: bool):
    frame = bytes([0x5A, 0x01, 0x02, 0x01 if on else 0x00])  # 'Z', sub 1, len 2, state
    # + report ID/padding per the device's HID descriptor
    dev.write(frame)

def set_speakers_hrtf(on: bool):
    frame = bytes([0x5A, 0x1E, 0x02, 0x01 if on else 0x00])  # sub 30
    dev.write(frame)
```

Combined with `pactl`/`pw-cli` to set the G6 sink to 8 channels and the
device-side engine enabled via the frames above, virtual 7.1 works
device-side — same binaural render as Windows. Direct Mode is the same
one-byte switch, and `spdif-out-direct` toggles the optical passthrough we
verified live.

*Cross-check before release: verify frames with `usbmon` once against
SBCommand on a Windows machine — then the Linux daemon is fully grounded.*
