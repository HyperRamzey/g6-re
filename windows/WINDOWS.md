# g6ct on Windows — Creative MatrixEncoder 7.1→binaural on the G733

A port of Creative's `CMatrixEncoderEfxMod` (from `KSUSBAPO64.dll`, the
Sound BlasterX G6 driver) to Windows. The DSP is bit-for-bit the same transfer
function as the G6's; only the host changed (Linux LADSPA → Windows APO → VST2).

There are **two hosts**, and they exist because the G733 changed underneath us:

| host | when to use it | status |
|---|---|---|
| **Equalizer APO** (`out/g6ct.txt`) | the endpoint is a real 8-channel render device | verified, live null test 142 dB |
| **VST2 insert** (`plugin/g6ct.dll`) | the endpoint is 2.0 (modded INF) and a virtual 7.1 device carries the stream | verified offline, bit-exact |

Equalizer APO cannot serve the second case: VoiceMeeter's VAIO endpoints
expose **no APO slots at all** (`FxProperties` has 0 values and no
`{d04e05a6-…}` entries), which matches the long-standing "EAPO does not affect
VM Virtual Input" reports. With a 2.0 physical endpoint the DSP therefore has
to run in user space, inside a VST host, and the only sanctioned way in and out
of VoiceMeeter is its **Insert Virtual ASIO** driver.


## What it does

    frontL = FL + 0.707*FC + 0.707*LFE
    frontR = FR + 0.707*FC + 0.707*LFE
    surL   = 0.786*BL + 0.619*BR + 0.875*SL + 0.485*SR
    surR   = 0.619*BL + 0.786*BR + 0.485*SL + 0.875*SR
    outL   = B(A(frontL)) + D(C(surL))
    outR   = B(A(frontR)) - D(C(surR))

`A..D` are second-order all-passes (b0 == a2, b1 == a1, b2 == 1), so the
branches are phase-only; the sign flip on the right surround is the
out-of-phase cross-feed that puts the image behind the listener. Output is two
channels; the other six are written to zero.

Channel order is the device's for mask `0x63F`:
`1 FL  2 FR  3 FC  4 LFE  5 BL  6 BR  7 SL  8 SR`.

## Layout

| path | what |
|---|---|
| `upstream/` | the shared DSP core, its LADSPA wrapper, the CLI and the `test_ir` oracle (same files as `../port/`) |
| `out/g6ct.txt` | **the generated EqualizerAPO config** - deliverable for the 8-channel path |
| `plugin/g6ct_vst.c` | **the VST2 insert wrapper** - deliverable for the 2.0 + virtual-7.1 path |
| `plugin/g6ct.dll` | build output: 8 in / 2 out, f64 internal, VST-parameter + window metering (not tracked, see `plugin/build.ps1`) |
| `plugin/build.ps1` | mingw64 build (no MSVC, no Windows SDK needed) |
| `tools/mkconfig.py` | generator; edit this, never the output |
| `tools/runtests.py` | 9-vector offline null-test suite (acceptance test) |
| `tools/taps.py` | impulse taps vs the `test_ir` oracle |
| `tools/vst_nulltest.py` | drives `g6ct.dll` as a host would and null-tests both process paths |
| `tools/livecheck.py` | end-to-end test: WASAPI render + 8ch loopback capture |
| `tools/idcheck.py` | measures the endpoint alone (identity config) |
| `tools/apply_apo.ps1` | attach/detach EqualizerAPO on the endpoint (elevated) |
| `tools/set_config.ps1` | hot-swap the live config (elevated) |
| `tools/trace_on.ps1` | toggle audiodg's EqualizerAPO trace log |
| `tools/scan_endpoints.py` | endpoint / APO / format dump (`--name`) |
| `tools/vmstate.py` | VoiceMeeter Remote API snapshot (strips, buses, patch matrices) |
| `tools/pathtest.py` | plays a tone into an endpoint, records a VM bus tap |
| `work/` | the four stimulus/reference files the acceptance tests read (see `work/README.md`) |

`bench32/` on the authoring machine held `Benchmark.exe` and its DLLs for the
EqualizerAPO suite; it is not tracked here. Use the EqualizerAPO you installed,
plus `BenchmarkFloat.exe` as described under *Known gaps*.

## Installing

1. EqualizerAPO installed to `C:\Program Files\EqualizerAPO`.
2. Attach it to the G733 render endpoint — **elevated**:

       powershell -NoProfile -ExecutionPolicy Bypass -File tools\apply_apo.ps1 -Mode sfx

   `-Mode sfx` puts EqualizerAPO in the endpoint's **SFX** slot
   (`{d04e05a6-…},5`) and deletes the LFX/GFX/MFX/EFX values so the matrix runs
   exactly once. The LFX slot does not work on this endpoint (see below).

3. Deploy the config:

       powershell -NoProfile -ExecutionPolicy Bypass -File tools\set_config.ps1 -File out\g6ct.txt

   `config.txt` in the install directory must be `Include: g6ct.txt`.
   EqualizerAPO watches the directory and reloads on write — no service
   restart needed.

4. Playing a 2-channel stream leaves it untouched: the config is wrapped in
   `If: inputChannelCount == 8`, which reproduces the DLL's stereo bypass.

## The VST2 insert (2.0 endpoint + virtual 7.1)

The physical G733 is a **2.0** device after the modded INF, but applications
must still see a 7.1 device. The chain is therefore:

    app ──7.1──▶ Voicemeeter Input (VAIO, 8ch/48 kHz, mask 0x63F)
                 │
                 ▼  strip → Insert Virtual ASIO, IN#4 (8 of the 22 channels)
              Element  ──  g6ct.dll  ──▶  binaural L/R
                 │
                 ▼  bus A1, exclusive WDM
              G733 @ 2ch/48k/16-bit  (VM's engine owns the device, no APOs)

Element is the host. It is a graph host with an ASIO backend, it keeps the
plugin's state alive across device changes, and it can patch a single stereo
output pair back onto the insert bus. Nothing else is doing the fold: the
plugin is the only 7.1→2.0 stage in the chain.

### Plugin contract

| | |
|---|---|
| format | VST 2.4, plain C, `__declspec(dllexport)`, no C++ runtime |
| channels | **8 in / 2 out** |
| in 1–8 | `FL FR FC LFE BL BR SL SR` (WAVEFORMATEXTENSIBLE 7.1 order, = VST `kSpeakerArr71`) |
| out 1–2 | binaural left / right |
| parameters | 10 read-only meters: `In1..In8`, `OutL`, `OutR` |
| editor | 340×250 child window, input/output bars, 33 ms repaint |
| arithmetic | f64 throughout (`-DG6CT_DOUBLE`); the float32 I/O path converts per sample |
| coefficient contract | `-ffp-contract=off -fno-fast-math`, same as the oracles |
| uniqueID / version | `0x47364354` ('G6CT') / 1100 |

**Two outputs, not eight.** A VoiceMeeter insert is a round trip: the strip is
handed to the ASIO host and whatever comes back is put on the matching
channels. An 8-out plugin has to *actively zero* channels 3–8 or the six
channels the matrix just consumed survive and get summed back in, doubling the
surround content. With only two output ports there is nothing to zero — the
host simply has no third port to connect, so the failure mode is unreachable
instead of merely handled.

### Metering

Levels are exposed twice, from the same peak-hold state (`0.30 s` release,
instant attack):

1. **As VST parameters**, so any host can draw them. Each parameter is a
   normalised dB scale: `0.0` = −60 dB, `1.0` = 0 dB, so the float a host
   reads and the string `effGetParamDisplay` returns always agree (checked
   programmatically: all ten within 0.15 dB).
2. **In the plugin's own editor**, which shows the real dB value including
   overshoot above 0 dB, plus a red clip flag on any channel that went over.

The meters are display-only and computed after the DSP, in `double` peak
detection stored as `float`; they never touch the audio path.

### Build

    powershell -NoProfile -ExecutionPolicy Bypass -File plugin\build.ps1

No MSVC and no Windows SDK: `C:\ProgramData\mingw64\mingw64\bin\gcc.exe`
plus `-static-libgcc` is the whole toolchain. Exports are undecorated
x64 symbols: `VSTPluginMain` (and `main` for pre-2.4 hosts).

### Static analysis

Two linters, both clean on the shipped sources:

    # cppcheck 2.19.0 (choco install cppcheck); --library=windows replaces the
    # mingw headers, which cppcheck cannot fully evaluate.
    cppcheck --enable=warning,style,performance,portability --inconclusive ^
             --std=c11 --platform=win64 --library=windows ^
             --suppress=missingIncludeSystem -I upstream ^
             plugin\g6ct_vst.c upstream\g6ct.c

    # gcc's own analyzer, stricter warnings than the build uses
    gcc -std=c11 -O2 -Wall -Wextra -Wpedantic -Wshadow -Wconversion ^
        -Wsign-conversion -Wcast-qual -fanalyzer -DG6CT_DOUBLE ^
        -I upstream -c plugin\g6ct_vst.c -o NUL

`upstream/g6ct.c` produces no findings at all. `plugin/g6ct_vst.c` produces one
cppcheck style note (`dsp_get_parameter` could take a const `AEffect*`) and
three `-Wmain` warnings — both are ABI artefacts: the VST2 callback signature
is fixed by the host, and the spec *requires* exporting a symbol named `main`,
which is why `build.ps1` passes `-Wno-main`. The findings that were real are
fixed: a null-dereference ordering bug (`e->numInputs` read before the `e`
check in both process paths), five over-wide variable scopes, and three
missing `const`s.

### Offline verification

`tools/vst_nulltest.py` loads the DLL exactly the way a host does — a stub
`audioMaster`, `effSetSampleRate` / `effSetBlockSize` / `effMainsChanged`, then
`processReplacing` over blocks — and compares with `work/ref_check.raw`, the
`g6ct_cli_f64` render:

| path | residual (peak) | null depth | sha256 (16) | verdict |
|---|---|---|---|---|
| `processReplacing` (float32 I/O, f64 internal) | **0.000e+00** | −∞ dB | `08e56173fa90ac5d` = ref | **bit-exact** |
| `processDoubleReplacing` (f64 end to end) | 5.96e-08 | −152.01 dB | `cb94ad5a9f531ffe` | f64 vs the reference's own float32 rounding |

Block-size invariance (`stim8.f32` and `noise8.f32`, 144000 frames each, one
fresh plugin instance per block size):

| block | 37 | 128 | 256 | 480 | 512 | 1000 | 1024 | 4096 | 144000 |
|---|---|---|---|---|---|---|---|---|---|
| max error | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| sha256 (16) | `08e56173fa90ac5d` everywhere | | | | | | | | |

Every block size produces the identical hash, so the internal 1024-frame chunk
loop is transparent. `noise8.f32` gives `99842c3447ef99a1` with the same zero
residual across the same nine block sizes.

Also asserted by the harness:

* the ten meter parameters equal their own `effGetParamDisplay` strings within
  0.15 dB after playback;
* `effEditOpen` returns 1 and creates a child window on a real parent HWND;
  `effEditClose` removes it again;
* degraded-host paths — fewer than 8 inputs (missing channels read as
  silence), fewer than 2 outputs (the missing side sinks into scratch instead
  of a NULL pointer), `n == 0`, and a NULL `AEffect*` — all run without
  touching a bad pointer.

### VoiceMeeter settings the chain depends on

1. `Voicemeeter Input` set as the Windows default playback device, and its
   endpoint format must be **8ch / 48 kHz / mask 0x63F**. If it negotiates
   stereo, every application sees stereo and the matrix has nothing to fold.
2. **Out Limiter → Off** in VM System Settings. It is a look-ahead limiter on
   the A1 bus and it destroys bit-exactness.
3. **PATCH INSERT** for the strip carrying the virtual input, all 8 channels
   enabled, both directions.
4. **PATCH COMPOSITE** 8-channel for that strip, so all eight channels reach
   the insert rather than being pre-folded.
5. Host graph: the insert driver gives Element 22 inputs / 22 outputs; only
   the eight that belong to `Voicemeeter Input` (IN#4, ASIO channels 6–13) and
   the stereo pair the plugin returns are wired.

### Which insert channels carry which speaker

Measured live, one channel at a time, into a Banana `Voicemeeter Input` strip
(`IN#4` = ASIO channels 6–13, 0-based):

| strip channel | ASIO ch | VM's label there | actual content |
|---|---|---|---|
| 1 | 6 | FL | FL |
| 2 | 7 | FR | FR |
| 3 | 8 | FC | FC |
| 4 | 9 | LFE | LFE |
| 5 | 10 | SL | **BL** |
| 6 | 11 | SR | **BR** |
| 7 | 12 | BL | **SL** |
| 8 | 13 | BR | **SR** |

Positions are 1:1 with WAVEFORMATEXTENSIBLE 7.1 order; only Banana's *labels*
on channels 10–13 are crossed. The plugin maps by position, so `In5` is BL and
`In7` is SL as the header says, which is what the matrix expects. Do not
"fix" this by relabelling — the audio is already in the right slots.

Bus taps are usable but **not sample-exact**: `Voicemeeter Out B1` reaches as a
plain 2-channel digital device (measured peak 0.249969 on a −12 dBFS tone), and
VM's virtual path adds a small fractional delay — a 440 Hz tone comes back at
correlation 0.99973, i.e. about 0.38 samples of delay, and the noise IR is a
unity delta at tap 0 (peak 0.9974). A capture at B1 can therefore confirm
routing and gain, but it can never null to zero against a bit-exact reference.
The offline plugin test above is the verification of record for the transfer
function; the live chain is confirmed by ear and by the Insert-driver channel
map measured above.

## Evidence — the EqualizerAPO path

Offline, against `g6ct_cli_f64` (float64 reference), 2 s per vector:

| vector | ch | SNR dB | max_err LSB16 |
|---|---|---|---|
| tones8 | 8 | 143.58 | 0.00586 |
| impulse8 | 8 | 141.91 | 0.00781 |
| noise8 | 8 | 143.25 | 0.00781 |
| front / center / lfe | 8 | 148.86 / 145.18 / 147.45 | ≤ 0.002 |
| back / side | 8 | 144.87 / 145.12 | ≤ 0.002 |
| stereo2 | 2 | ∞ | 0 — bit-exact |

`9/9 passed`.

Impulse taps vs the `test_ir` oracle: all eight channels match, worst deviation
`4.90e-07`, 0 mismatches.

Live, through audiodg → the installed APO → the G733 loopback (3 s, 8-channel
stimulus, reference peak 0.908):

    ch1  SNR 142.38 dB   max_err 1.192e-07  (0.0039 LSB16)  49370/144000 bit-identical
    ch2  SNR 142.33 dB   max_err 1.192e-07  (0.0039 LSB16)  50009/144000 bit-identical
    ch3..ch8  all zero, 144000/144000 bit-identical

The residual against a float64 reference is float32 rounding, not error: the
same 142 dB appears at 0.45 and 0.91 reference peak, i.e. it is level
independent.

## The endpoint's limiter — read this before judging a hot test

The G733 endpoint is **transparent** on its own: with an identity config
installed the loopback capture is bit-exact on all eight channels.

It is *not* transparent above full scale. Feed it 8 channels and scale the
stimulus, and the endpoint returns:

| stimulus peak | measured gain |
|---|---|
| 0.51 | 1.000000 (bit-exact) |
| 1.02 | 0.9676 |
| 1.53 | 0.6451 |

The captured peak pins at **0.9853 (−0.13 dBFS)** in every over-full-scale
case: that is a peak limiter in the endpoint, not a bug in the port. A null
test run with our matrix's natural output (+3.6 dBFS for a 0.51-peak 8-channel
stimulus) therefore measures the limiter and lands at ~31 dB, which is what it
should do.

So: to verify the transfer function, keep the output under about −0.15 dBFS.
Either scale the source down, or add a preamp above the stage line:

    Preamp: -4 dB

The matrix itself is unity gain, like the DLL. Its rows sum to as much as
+7.6 dB, so a hot 7.1 mix will reach the limiter no matter what; that is normal
playback behaviour, not a defect.

## A/B and revert

    # restore the vendor chain (Logitech HX2E + 670173e3/e4/e5)
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\apply_apo.ps1 -Revert

    # swap the DSP out without touching the APO attachment
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\set_config.ps1 -File tools\identity.txt

Pre-change registry exports are in `work/`: `g733_render_before.reg`,
`eqapo_before.reg`. The original `config.txt` is `work/config.txt.bak`.

## Why the SFX slot

EqualizerAPO in the LFX slot (`{d04e05a6-…},1`) is **never instantiated** on
this endpoint — `audiodg.exe` loads no `EqualizerAPO.dll` and writes no trace
log. Move the same GUID to the SFX slot (`,5`), with
`{d3993a3f-…},5 = {C18E2F7E-933D-4965-B7D1-1EEF228D2AF3}`, and audiodg loads
`EqualizerAPO.dll`, `fftw3f.dll` and `sndfile.dll`. `apply_apo.ps1` writes those
keys through .NET `RegistryKey` with `KEY_SET_VALUE` only, because the MMDevices
keys do not grant Administrators `KEY_ALL_ACCESS` and PowerShell's `HKLM:`
provider asks for exactly that.

A side benefit of the SFX slot: it sees the *stream* format, not the endpoint's
mix format, so a 2-channel stream hits `inputChannelCount == 8` and bypasses —
the same condition the DLL uses.

## Diagnostics

    # is the APO live? what did it parse?  (elevated)
    powershell -NoProfile -ExecutionPolicy Bypass -File _probe\apo_loaded.ps1

    # the trace log itself
    C:\Windows\ServiceProfiles\LocalService\AppData\Local\Temp\EqualizerAPO.log

The log proves instantiation: `Initialize`, `APO GUID`, `Endpoint GUID`,
`RequestedInputFormat`, `Loading configuration from …g6ct.txt`,
`Matching stage "pre-mix"`, `If(inputChannelCount == 8) evaluated to true`,
then every `Copy:` and every `Adding IIR filter of order 2` with its
coefficients.

## Rebuilding the C binaries

`upstream/` is the shared DSP core plus the CLI and the oracle test, and it is
the same code as `../port/`. Build everything with mingw64:

    choco install mingw -y

    cd upstream
    mingw32-make CC=gcc               # g6ct_cli, g6ct_cli64, test_ir, test_ir64, ...

    # or by hand, which is what the build/ directory on the authoring machine held
    gcc -O2 -std=c11 -o g6ct_cli_f32.exe g6ct_cli.c g6ct.c -lm
    gcc -O2 -std=c11 -DG6CT_DOUBLE -o g6ct_cli_f64.exe g6ct_cli.c g6ct.c -lm
    gcc -O2 -std=c11 -o test_ir_f32.exe test_ir.c g6ct.c -lm
    gcc -O2 -std=c11 -DG6CT_DOUBLE -o test_ir_f64.exe test_ir.c g6ct.c -lm

The oracles pass on Windows: `test_ir_f32` -> `0x684d7c9b2515f759`,
`test_ir_f64` -> `0x5f78798536b3fa72`, both `PASSED (0 failures)`
(`verification_test_ir_f32.txt`, `verification_test_ir_f64.txt`).

## Known gaps

* `Benchmark.exe` hardcodes 16-bit output. `C:\Program Files\EqualizerAPO\BenchmarkFloat.exe`
  is a one-byte-patched copy (offset `505232`, `0x02` → `0x06`) that writes
  8-channel float32; the offline suite depends on it.
* The offline suite's reference `work/ref_check.raw` is authoritative;
  `work/ref_f32.raw` is stale (differs by 2.8e-05).
* `tools/runtests.py` and `tools/taps.py` compare against
  `g6ct_cli_f64.exe`, so float32-vs-float64 rounding is the floor at ~142 dB.
* **The VST2 chain is verified offline only.** VM's insert path is not
  sample-exact (fractional delay, ~0.38 samples on the tone test), so the live
  segment cannot be null-tested to zero even with a working tap. The offline
  test proves the DSP and the host contract; the live chain is proven by
  measurement of the insert channel map plus listening.
* Element caches plugin metadata in
  `%APPDATA%\Kushview\Element\plugins.xml`, and the cached entry still says
  8 in / 8 out from the earlier build. Delete and re-add the plugin node (or
  rescan) after rebuilding with a different channel count, otherwise the graph
  keeps the stale port layout.
