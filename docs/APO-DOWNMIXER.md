# The 7.1 → binaural downmixer is a host APO (KSUSBAPO64.dll)

**Status:** fully decoded, reimplemented, and verified **bit-exactly** against the
shipping DLL. The port and its test suite are in [`../port/`](../port/), the Wine
harness in [`../apo-harness/`](../apo-harness/).

This document also **corrects §C.2.4 and §C.4 of [`../REPORT.md`](../REPORT.md)**.
The earlier analysis concluded that with 7.1 selected the host streams 8 channels
and the device's fixed speaker-config downmix produces stereo. That is not what
happens on the G6 headphone endpoint: the 8 → 2 conversion is done **in the
Windows audio engine, by a Creative APO**, and the device only ever sees two
channels.

---

## 0. What was wrong, and why it matters

`REPORT.md` §C concluded:

> "The 7.1 'setting' then only selects the endpoint format + the device's fixed
> (non-programmable) speaker-config downmix."

The firmware half of that analysis is correct and stands: with Direct Mode on, the
firmware stops writing op-150 effect parameters to the VT1728 (§C.2.1). But the
downmix does not happen there. `KSUSBAPO64.dll` — the SysFx APO the installer
registers on the G6 endpoint — contains a node called `CMatrixEncoderEfxMod`,
and for `(device 38, headphone form factor)` it is placed in a three-node chain
that converts 8 channels to 2 with a matrix plus four second-order all-passes.

Consequences:

* The endpoint **presents** 8 channels to applications but **transmits** 2. That
  matches what the owner of the device measured on Windows: applications see a
  7.1 endpoint, the G6 receives stereo, and the "7.1 headphone" metadata makes no
  difference to what the device gets.
* **Direct Mode cannot disable it.** An APO runs inside `audiodg.exe`, upstream
  of the driver; the firmware gate that suppresses device effect writes has no
  authority over it. That resolves the apparent contradiction between "Direct =
  no effects" and "Direct + 7.1 still images outside the head": the device is
  doing nothing, and the binaural render has already happened on the host.
* Therefore the earlier verdict in [`LINUX.md`](LINUX.md) — "the APO is not where
  the virtual 7.1 render happens" — is wrong **for this mode**. The APO is
  exactly where it happens for 7.1 headphones in Direct Mode. What the device
  DSP does under Sound Blaster Command (non-Direct) is a separate, still-valid
  path.

---

## 1. Which node runs, and when

Everything below is from `KSUSBAPO64.dll` (2,172,904 bytes, 2020-10-14, image base
`0x180000000`), shipped in
`Creative Sound Blaster USB Audio Drivers Installer/.../Driver/WinVista/Bin/AMD64/`.

### 1.1 Chain selection

`sub_18001ECC0` maps `(deviceId, internalFormFactor, flag)` to a chain id. There
are four tables, selected by a mode field at `this+172`:

| mode | table | entries | record |
|---|---|---|---|
| 0, 1 | `0x1801CE070` | 249 | `{u32 deviceId, u32 formFactor, u32 flag, u32 chain}` (16 B) |
| 2 | `0x1801CD320` | 212 | same |
| 3 | `0x1801CF010` | 212 | same |
| 4 | `0x1801CC5D0` | 212 | same |

For the G6 (Malcolm, `APOINFO_HW_MALCOLM = 38`):

```
dev=38 ff=1 flag=0 -> chain 37     (speakers)
dev=38 ff=2 flag=0 -> chain 37     (headphones)   <-- ours
dev=38 ff=4 flag=0 -> chain 88
```

The chain table itself is at `0x1801CB7D0`, 149 records of
`{u32 chainId, void *nodes, u32 count}` (24 B). Chain 37 lives at
`0x1801CBB48`:

```
chain 37 = [ 1, 15, 1 ]
```

Node 1 is the channel swapper (`CSwap`), node 15 is `CMatrixEncoderEfxMod` — the
class whose `Process` this document describes. The two swaps put the encoder in
the middle of an otherwise pass-through chain.

### 1.2 The feature mask can delete it

`sub_18001EE40` builds the chain: it looks up the chain id, reads a property from
the endpoint property store, and passes the node list through `sub_18006FD40`.

* Property key: `{EB2FF3AE-3ED4-4F61-BFE4-4553708A402E}`, pid 0, `VT_UI4`
  (read via `GetValue` at vtable `+0x28`, key descriptor `unk_180161270`).
* `sub_18006FD40` assigns each node id a mask bit and **drops the node when its
  bit is set**. Node 15 → bit `0x4000` (verified: `case 0xF: if ((a2 & 0x4000) == 0)
  goto LABEL_92;`).
* If nothing survives, the chain degrades to `[0, 0, 0]` (three null nodes,
  i.e. pass-through).
* The property is normally **absent**, so the mask is 0 and the full chain runs.

So the encoder is unconditional on a stock install: a `.ini` that set bit 14
would be the only way to bypass it.

### 1.3 What the endpoint actually carries

```
in : 8 ch float32 48 kHz   mask 0x63F  (FL FR FC LFE BL BR SL SR)
out: 2 ch float32 48 kHz   mask 0x003  (FL FR)
```

`Process` validates the output rate into `[44100, 192000]` and requires a nonzero
block size (128 samples) and a live upstream connection; otherwise it delegates.

---

## 2. Process

`sub_180067D80`, `this` layout (only the fields that matter here):

| offset | meaning |
|---|---|
| `+0x08` | upstream connection object (`vtbl[8]` = fill-request) |
| `+0x20` | input `WAVEFORMATEXTENSIBLE` (24 B: rate, channels, mask, 0, bits, type) |
| `+0x28` | input channel mask (u32) |
| `+0x38` | output format (24 B) |
| `+0x40` | output channel mask (u32) |
| `+0x5C` | block size, 128 |
| `+0x80` | "initialised" flag, must be nonzero |
| `+0x218` | core object pointer (allocated separately, `0x328` bytes) |
| `+0x250` | `12 × frames` (bytes for the upstream buffer clear) |

Core object (`0x328` bytes):

| offset | meaning |
|---|---|
| `+0x00` | frames |
| `+0x04` | **valid frames, written by the upstream** — this is the loop bound |
| `+0x08..+0x67` | 12 input channel pointers, indexed by WAVE bit position |

Output descriptor passed as the third argument:

```c
struct { u32 frames; u32 written; float *ch[12]; };
```

### 2.1 Dispatch

```
out_mask == 4                  -> mono copy
out_mask == 3, in_mask == 4    -> duplicate one channel
out_mask == 3, in_mask == 3    -> stereo pass-through
out_mask == 3, other in_mask   -> matrix + all-pass path @0x18006805E   <-- ours
```

For the G6: `out_mask == 3`, `in_mask == 0x63F`, so the matrix path runs.

### 2.2 The functions needed to run it outside the APO container

| RVA | role |
|---|---|
| `0x678F0` | constructor: writes the 8 all-pass coefficient blocks, sets `+0x5C = 128`, `+0x80 = 1` |
| `0x68EA0` | allocates the core at `+0x218` (needs a property store at `+0x18`) |
| `0x69110` | `SetMaxFrames(n)` — requires `n % 128 == 0`, allocates the scratch buffers, calls `0x6F890` |
| `0x6F890` | zeroes the core and points the 12 channel pointers into the scratch buffer |
| `0x67D00` | the biquad |
| `0x67D80` | `Process` |

`Sub_18006F890` memsets the **core** (`0x328` bytes), so the core must be allocated
before `SetMaxFrames` is called — otherwise it writes to `NULL`. This is the one
non-obvious ordering constraint; the harness in [`../apo-harness/`](../apo-harness/)
does it explicitly.

---

## 3. The DSP

Per frame, with the driver's float constants:

```
frontL = FL + 0.707·FC + 0.707·LFE
frontR = FR + 0.707·FC + 0.707·LFE

surL   = 0.786·BL + 0.619·BR + 0.875·SL + 0.485·SR     (+ 0.707·BC)
surR   = 0.619·BL + 0.786·BR + 0.485·SL + 0.875·SR     (+ 0.707·BC)

outL   = B(A(frontL)) + D(C(surL))
outR   = B(A(frontR)) − D(C(surR))
```

`A`, `B`, `C`, `D` are second-order all-passes in direct form I:

```
y = b0·x + b1·x1 + b2·x2 − a1·y1 − a2·y2        x = input + 1e-10
```

| section | `b0 = a2` | `b1 = a1` | `b2` | pole radius |
|---|---|---|---|---|
| A | `0x3F725269` | `0xBFF92104` | 1.0 | 0.99485 |
| B | `0x3D82D384` | `0xBF567621` | 1.0 | 0.75289 |
| C | `0xBE856085` | `0x3CD273D6` | 1.0 | 0.52340 |
| D | `0x3F5EE547` | `0xBFEF2B02` | 1.0 | 0.98048 |

Because `b0 == a2`, `b1 == a1`, `b2 == 1`, each section is exactly all-pass:
`|H(e^jω)| = 1` at every frequency, phase only. Left and right use **identical**
coefficient sets — there is no head-shadow model.

Constants in the image:

| value | address | bits |
|---|---|---|
| 0.7070000171661377 | `0x180173CD8` | `0x3F34FDF4` |
| 0.48500001430511475 | `0x1801756DC` | `0x3EF851EC` |
| 0.6190000176429749 | `0x1801756E0` | `0x3F1E76C9` |
| 0.7860000133514404 | `0x1801756E4` | `0x3F49374C` |
| 0.875 | `0x1801756E8` | `0x3F600000` |
| 1.0000000134e-10 (denormal guard) | `0x1801756D8` | `0x2EDBE6FF` |

The guard is added to every biquad input, and it is the reason a silent input
does not produce exactly zero output.

---

## 4. Why it images outside the head, and why it does not colour

This is not an HRTF and it does not try to be one. Both branches are phase-only,
so the design controls exactly one thing: the phase relationship between them.

Measured from the coefficients above:

```
phase(AB) − phase(CD) = −90.0°   from 100 Hz to 12 kHz
                        −86.5°   at 16 kHz
                        (below 100 Hz and above 16 kHz the quadrature degrades)
```

Two unit-magnitude branches 90° apart give

```
|AB + CD| = |AB − CD| = √2      measured 1.405 … 1.457 over 100 Hz … 16 kHz
```

So the sum (mono fold-down) and the difference both have an essentially flat
magnitude response. Nothing can cancel: no comb filtering, no notch, no boost,
no "hollow" colouration, and the mix folds to mono cleanly.

The spatial cue is the **sign inversion of the right surround branch**. Content
present equally in both surrounds arrives at the two ears as `+2.765·CD` and
`−2.765·CD` — broadband interaural anti-phase, which the auditory system reads as
"not in front". Front content arrives in phase at both ears, and the quadrature
term keeps front and surround from cancelling each other.

An HRIR does the opposite: it imposes a specific pinna's magnitude notches
(5–10 dB deep, narrow, highly individual) on a listener whose pinna is different,
which is where the "in-head", "plastic" and front/back-flipped sensations come
from. This filter never asserts a pinna transfer function, which is why it is
listener- and headphone-independent — and why it is what ships.

Magnitude flatness was measured directly: `|A|,|B|,|C|,|D|` deviate from unity by
at most **3 × 10⁻¹⁴** across 20 Hz – 20 kHz.

---

## 5. Verification

### 5.1 Against the shipping DLL (`apo-harness/`)

The APO container is bypassed: the object is created with its own constructor,
the core is allocated, a fake upstream object publishes the channel pointers and
`core+4`, and `Process` is called directly — the same call the Windows audio
engine makes.

| Test | Result |
|---|---|
| 8 coefficient blocks read from the live object | identical to the port's table |
| 8 × 2 impulse-response matrix, 4096 frames | **0 differing samples** of 65536 |
| 7 arbitrary signals, 57344 samples (full-scale noise, −120 dBFS noise, denormal-scale noise, DC, multi-tone, one-sided, step) | **0 differing samples** |

Log: [`../apo-harness/verification_dll_wine.txt`](../apo-harness/verification_dll_wine.txt).

### 5.2 The port in isolation

`port/test_ir` checks the matrix weights, the all-pass magnitude (unity to
machine precision), the sign inversion on the right surround terms, and pole
stability. `port/test_ir64` repeats it in double precision. Both pass with 0
failures.

### 5.3 Through the live Linux graph

`port/verify_pipewire.sh` plays a known 8-channel signal into the PipeWire
filter-chain node, records what the chain hands to the sound card, and compares
it against the reference render of the same code: **max abs error 0.000e+00** over
192000 frames × 2 channels, in both float32 and float64 builds.

---

## 6. The port

[`../port/`](../port/) is a dependency-free C11 implementation of exactly this
node: `g6ct.c` / `g6ct.h` (core), `g6ct_ladspa.c` (LADSPA plugin for
`libpipewire-module-filter-chain`), `g6ct_cli.c` (reference renderer), `test_ir.c`
(unit test), `Makefile`.

The default build is float32 and reproduces the DLL bit for bit. `-DG6CT_DOUBLE`
builds a second object with the same coefficients and operation order in double
precision; it is *not* bit-identical to the DLL (it differs by up to 9.4 × 10⁻⁷,
which is the DLL's own rounding error) but is the more accurate renderer.

Linear phase was deliberately not implemented: a linear-phase all-pass is a pure
delay, which would make `AB ≡ CD`, destroy the quadrature above and reintroduce
comb filtering. The phase *is* the effect.

---

## 7. What this means

* **For Windows users:** "Direct Mode" does not remove the 7.1 binaural downmix,
  because the downmix lives in the host APO. Device-side effects are off; the
  APO is not device-side. Setting the endpoint to stereo bypasses the APO path
  entirely (chain 37 is selected for 8-channel formats).
* **For Linux users:** a Linux stack that sends 8 channels to the G6 is not
  reproducing the Windows Direct-Mode path. On Windows the device receives two
  channels; the 8 → 2 matrix has already happened. The port here is the missing
  piece, and it is verified sample-identical.
* **For the repo's earlier claims:** `REPORT.md` §C.2.4/§C.4 and the verdict in
  `docs/LINUX.md` are corrected as described in §0. The firmware findings
  themselves (effect-write suppression, SPDIF gating, capability bits) are
  unaffected.

---

## 8. Reproducing

```sh
# analysis: IDA, image base 0x180000000, addresses as cited above
# port + tests
cd port && make && ./test_ir && ./test_ir64

# A/B against the real DLL (needs wine + mingw-w64 + the Creative installer)
cd ../apo-harness
x86_64-w64-mingw32-gcc -O2 -o harness.exe harness.c -lole32
WINEPREFIX=./prefix wine harness.exe 'Z:\path\to\KSUSBAPO64.dll' coef
WINEPREFIX=./prefix wine harness.exe 'Z:\path\to\KSUSBAPO64.dll' ir  dll_ir
python3 compare_port.py      # impulse matrix, port vs DLL
python3 compare_signal.py    # arbitrary signals, port vs DLL
```

No Creative binaries are included in this repository; the harness takes the DLL
path as an argument. `cfSB1770.ini`, the installer and the DLL are copyrighted
and must be obtained by the user.
