# Repo layout

```
README.md              — plain-language findings (start here)
REPORT.md              — full technical report with evidence trail
docs/fw_notes.md       — analysis notebook: every address, function, live test
fw_extract/            — our scripts to unpack G6 OTA installers → firmware banks
  scan_installer.py      scan installers for embedded container formats
  pe_info.py             PE section/string dump to identify packers
  parse_all.py           Intel-HEX parser → per-bank .bin images
  make_elf.py            wrap raw banks as loadable ELFs for IDA
  verify_banks.py        Cortex-M vector sanity check
tools/                 — host-side tools (talk via Creative's CTHIDRpA COM)
  G6HidProbe.cs          read-only device query (fw, serial, mode states)
  G6HidSet.cs            toggle StereoDirect / SPDIF-Out Direct
  G6HidExplore.cs        hidden-feature probe: mask sweep, HRTF toggle, etc.
  decode_mask.py         decode FeatureBitwiseMask1/2 values
  thd_test.py            THD+N loopback measurement (run when device is free)
  g6_volume.py           per-endpoint volume control helper
  optical_tap.py         SPDIF/optical domain tests
```

## What is NOT in this repo (on purpose)

- No Creative firmware binaries, no extracted `.bin`/`.elf`/`.i64` images
  (copyright). Use `fw_extract/` scripts on the official OTA installers.
- No decompiled Sound Blaster Command source (copyright). The evidence in
  REPORT.md cites file/line references from a local decompile you can repeat
  with ILSpy.
- No Creative DLLs. Tools load them from the official Sound Blaster Command
  installation at runtime.

## Requirements

- .NET SDK (any modern) for the C# tools — must be built/published as **x86**
  to match Creative's 32-bit COM DLLs.
- Python 3.10+ with `numpy`, `sounddevice`, `pycaw` for measurement scripts.
- `innoextract` (winget install dscharrer.innoextract) for OTA unpacking.
- IDA (with idalib) for the firmware analysis scripts' output.
