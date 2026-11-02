# work/ - the stimulus and reference files the acceptance test needs

Four files, nothing else. They are byte-identical to the ones the port was
verified against, so `tools/vst_nulltest.py` reproduces the published result
without regenerating anything.

| file | shape | what it is |
|---|---|---|
| `stim8.f32` | 144000 x 8, float32, interleaved | primary 3 s stimulus at 48 kHz: one tone per channel - 440, 660, 880, 60, 1000, 1300, 1700, 2100 Hz - each 3 dB below the one before (fresh 0.51 peak down to 0.15), so a mis-ordered channel shows up immediately in the per-channel meter dump |
| `ref_check.raw` | 144000 x 2, float32, interleaved | `g6ct_cli_f64` render of `stim8.f32`. **Authoritative** reference: every null test in this directory compares against this file |
| `noise8.f32` | 144000 x 8, float32, interleaved | broadband stimulus, used for block-size invariance and for the live chain (an IR survives the fractional delay a tone does not) |
| `noise8.ref.raw` | 144000 x 2, float32, interleaved | `g6ct_cli_f64` render of `noise8.f32` |

Interleaved means frame-major: frame 0 channel 0..7, frame 1 channel 0..7, and
so on. Channel order is WAVEFORMATEXTENSIBLE 7.1 for mask `0x63F`:

    1 FL   2 FR   3 FC   4 LFE   5 BL   6 BR   7 SL   8 SR

The reference renders come from `g6ct_cli_f64.exe` (see `../upstream/`), which
is the float64 build of the same `g6ct_process()`. Regenerate a reference with:

```powershell
build\g6ct_cli_f64.exe stim8.f32 ref_check.raw 0x63F 8
```

Usage is `<in.raw> <out2.raw> [mask] [channels]`; the CLI assumes 48 kHz, which
is the format this whole chain runs at.

`ref_f32.raw` is deliberately absent: it is stale by 2.8e-05 against the
float64 render and comparing against it hides real errors.
