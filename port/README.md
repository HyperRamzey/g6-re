# g6ct — Creative MatrixEncoder 7.1 → binaural stereo

A dependency-free C11 implementation of the node that the Windows APO runs on the
Sound BlasterX G6 headphone endpoint when the format is 7.1:

```
KSUSBAPO64.dll   CMatrixEncoderEfxMod   chain 37 = SWAP | MATRIXENC | SWAP
```

Not SBX Surround, not the CMSS-3D virtualizer, not an HRTF. Same matrix weights,
same all-pass coefficients, same float behaviour as the shipping driver, verified
sample-for-sample against the binary — see
[`../docs/APO-DOWNMIXER.md`](../docs/APO-DOWNMIXER.md) for the full analysis and
[`../apo-harness/`](../apo-harness/) for the A/B test.

## The DSP

```
frontL = FL + 0.707·FC + 0.707·LFE
frontR = FR + 0.707·FC + 0.707·LFE
surL   = 0.786·BL + 0.619·BR + 0.875·SL + 0.485·SR     (+0.707·BC)
surR   = 0.619·BL + 0.786·BR + 0.485·SL + 0.875·SR     (+0.707·BC)

outL = B(A(frontL)) + D(C(surL))
outR = B(A(frontR)) − D(C(surR))
```

`A..D` are second-order all-passes (`b0 == a2`, `b1 == a1`, `b2 == 1`), so every
branch is phase-only. Each biquad adds `1e-10` to its input (the original's
denormal guard):

```
y = b0·x + b1·x1 + b2·x2 − a1·y1 − a2·y2
```

| section | `b0 = a2` | `b1 = a1` | pole radius |
|---|---|---|---|
| A | `0x3F725269` | `0xBFF92104` | 0.99485 |
| B | `0x3D82D384` | `0xBF567621` | 0.75289 |
| C | `0xBE856085` | `0x3CD273D6` | 0.52340 |
| D | `0x3F5EE547` | `0xBFEF2B02` | 0.98048 |

The core of the design is the 90° relationship between the two branches: both
are unit magnitude at all frequencies, and `phase(AB) − phase(CD) = −90°` from
100 Hz to 12 kHz, so `|AB ± CD| ≈ √2` and the sum/difference never comb-filter.
The right surround branch is subtracted, which is what puts the surround image
behind the listener. Details and measurements: §4 of the analysis document.

## Files

| File | Purpose |
|---|---|
| `g6ct.h` / `g6ct.c` | the port; libm only |
| `g6ct_cli.c` → `g6ct_cli`, `g6ct_cli64` | raw interleaved f32 8ch → 2ch reference renderer |
| `g6ct_ladspa.c` → `libg6ct_ladspa.so`, `libg6ct_ladspa_f64.so` | LADSPA plugin for PipeWire |
| `test_ir.c` → `test_ir`, `test_ir64` | IR matrix, all-pass magnitude, pole stability |
| `verify_pipewire.sh [f32\|f64]` | end-to-end test through a live PipeWire graph |
| `verification_unit_test*.txt`, `verification_pipewire*.txt` | saved results |

## Build

```sh
make            # everything, both precisions
make check      # unit tests, writes verification_unit_test*.txt
```

`-ffp-contract=off` is in the default flags: it stops the compiler from fusing
multiply-adds, so the arithmetic keeps the same order as the original.

### Two precisions

| build | flag | plugin | behaviour |
|---|---|---|---|
| float32 (default) | — | `libg6ct_ladspa.so` | bit-identical to `KSUSBAPO64.dll` |
| float64 | `-DG6CT_DOUBLE` | `libg6ct_ladspa_f64.so` | same transfer function, 60 dB closer to an exact render |

Measured against an 80-bit (`long double`) reference running the same
coefficients in the same order — 1 s, front-left, random 0.25 (−12.07 dBFS rms):

| build | error rms | error peak | below signal |
|---|---|---|---|
| float32 | −104.00 dBFS | −92.96 dBFS | 91.9 dB |
| float64 | −164.01 dBFS | −147.69 dBFS | 151.9 dB |

So float64 removes 60.0 dB of arithmetic noise. It is **not** bit-identical to
the DLL: nulling the two builds on a hot 10 s 8-channel signal gives peak
−86.4 dBFS / rms −100.0 dBFS, and 958373 of 960000 samples differ. That
divergence is the DLL's own float32 rounding leaking through the r = 0.99485
pole, so it accumulates rather than sitting at a fixed floor, and it does not
shrink with level. Use float32 to reproduce Windows exactly; use float64 for the
cleanest render. CPU cost is nil — 60 s of 8-channel audio renders in ~100 ms in
both builds (~600× realtime).

The double build uses the same coefficients (each is the exact float the
constructor writes, promoted losslessly) and the same operation order. It is a
separate `.so` because the symbols have the same names with a different scalar
type. `g6ct_process` takes `g6ct_real *const in[12]`, indexed by WAVE bit
position: 0 FL, 1 FR, 2 FC, 3 LFE, 4 BL, 5 BR, 6 FLC, 7 FRC, 8 BC, 9 SL, 10 SR,
11 TC. A `NULL` channel is silence.

**Linear phase was deliberately not implemented.** A linear-phase all-pass is a
pure delay: `AB` would collapse onto `CD`, the quadrature would vanish and the
comb filtering would come back. The phase is the effect.

## PipeWire

```ini
# ~/.config/pipewire/pipewire.conf.d/99-g6-ct-downmix.conf
context.modules = [
    { name = libpipewire-module-filter-chain
        args = {
            filter.graph = {
                nodes = [
                    { type = ladspa name = enc
                      plugin = "/path/to/libg6ct_ladspa.so"
                      label = "g6ct_matrix_encoder"
                      control = { "Channel Mask" = 1599 } }
                ]
                inputs  = [ "enc:FL" "enc:FR" "enc:FC" "enc:LFE" "enc:BL" "enc:BR" "enc:SL" "enc:SR" ]
                outputs = [ "enc:OutL" "enc:OutR" ]
            }
            capture.props = {
                node.name = "g6_ct_downmix"
                media.class = Audio/Sink
                audio.channels = 8
                audio.position = [ FL FR FC LFE RL RR SL SR ]
            }
            playback.props = {
                node.name = "g6_ct_downmix.output"
                node.passive = true
                audio.channels = 2
                audio.position = [ FL FR ]
                target.object = "alsa_output.usb-...-pro-output-0"
            }
        }
    }
]
```

Channel positions must be `RL RR` for the rear pair — PipeWire parses `BL`/`BR`
as unknown and remixes them. `Channel Mask` is a control: `1599` (0x63F) is 7.1,
`255` (0xFF) is FL FR FC LFE BL BR FLC FRC.

The plugin is rate independent, like the original (which only checks that the
rate is within 44100–192000). PipeWire runs it at the graph rate.

## Players

Any client can render through the chain by selecting the sink. For mpv:

```ini
# ~/.config/mpv/mpv.conf
audio-device=pipewire/g6_ct_downmix
audio-channels=7.1,5.1,stereo
audio-format=float
audio-samplerate=48000

# optional: linear-phase correction IR, applied per channel ahead of the downmixer
af=lavfi=[amovie=/path/to/ir.wav[ir2];[in][ir2]afir=irfmt=mono:irnorm=-1:wet=1:minp=4096:maxp=4096:precision=double]
```

`audio-format=float` is not cosmetic: without it mpv's PipeWire AO negotiates
`s16le` and the chain receives 16-bit-quantised input. `audio-channels` keeps
the source layout (no forced upmix). `irnorm=-1` makes `afir` use the raw IR —
the default would auto-normalise its gain.

Verified with mpv 0.41 (`--ao=pipewire`) by measuring the hardware sink's
monitor — the same silent tap `verify_pipewire.sh` uses:

| source | result |
|---|---|
| 7.1, one tone per channel | FL/FR/FC/LFE in phase (unity / 0.707); BL 0.786/0.619, BR 0.619/0.786, SL 0.875/0.485, SR 0.485/0.875 — every surround term 180° out of phase |
| 7.1 TrueHD + Atmos (24-bit 48 kHz, 8 ch), 15 s | mpv sends `f32le 8ch 48 kHz`; capture vs offline reference (ffmpeg decode → same `afir` → `g6ct_cli64`): **residual rms −223.6 dBFS, peak −186.2 dBFS, correlation 1.00000000** |
| stereo | L → L, R → R at unity; no leakage into centre or surrounds |
| 5.1, rear-left only | L 0.786, R 0.619, 180° — rears map to the rear pair, as on Windows |

The correction IR is applied per channel before the matrix. It is mono and the
downmix is linear, so this is identical to filtering after the mix. The IR is
linear phase: measured group delay is flat at **100.0 ms** across the band, so
it delays audio relative to video — add `audio-delay=-0.1` if you want lip sync
back.

mpv opens the stream with the source layout and PipeWire maps by channel
position, so stereo music only ever touches the phase-only front path. To bypass
the chain for one file, pass `--audio-device=pipewire`.

## Verification

```
$ ./test_ir | tail -1
PASSED (0 failures)
$ ./test_ir64 | tail -1
PASSED (0 failures)
```

`verify_pipewire.sh` mutes the hardware sink for the run (the monitor tap is
pre-mute, so the measurement is unaffected) and compares a 4 s noise+tones
stimulus against the reference render:

```
recorded frames 335872 reference frames 192000
max abs error 0.000e+00   rms error 0.000e+00
PASS
```

Against the real DLL (Wine): 0 differing samples across the 8×2 impulse matrix
and seven arbitrary signals. See
[`../apo-harness/verification_dll_wine.txt`](../apo-harness/verification_dll_wine.txt).

## Notes

* The G6 must be in **Direct Mode** with SBX/HRTF disabled on the device, or its
  own DSP colours the output on top of this.
* On Windows the equivalent node runs in `audiodg.exe`; the device itself only
  ever receives stereo. This port is what Linux needs to match that path.
* To revert: remove the filter-chain config and reload PipeWire.
