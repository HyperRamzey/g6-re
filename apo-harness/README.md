# Running the real Creative DSP under Wine

This directory contains the harness that executes `CMatrixEncoderEfxMod::Process`
from the shipping `KSUSBAPO64.dll` on Linux, so the port in [`../port/`](../port/)
can be checked against the actual binary rather than against a disassembly.

Nothing here contains Creative code. The harness takes the DLL path as its first
argument; you supply the DLL from the official installer.

---

## What it does

The APO container (`audiodg.exe`, the effect-chain plumbing) is not needed. The
object is driven directly:

1. `LoadLibraryA(KSUSBAPO64.dll)`.
2. `calloc(1024)` and call the constructor at RVA `0x678F0`.
3. Allocate the core (`calloc(1, 0x328)`) and store it at `this+0x218`.
   Normally `sub_180068EA0` does this, but it also reads a property store at
   `this+0x18`, which would have to be faked. Allocating the core directly is
   simpler and equivalent.
4. Point `this+0x08` at a fake upstream object whose `vtbl[8]` is our fill
   function.
5. `SetMaxFrames(this, N)` at RVA `0x69110` (`N` must be a multiple of 128).
   This allocates the scratch buffers and calls `sub_18006F890`, which **memsets
   the core** and points the 12 channel pointers into the scratch buffer.
   Calling it before step 3 is the one guaranteed crash — it writes to `NULL`.
6. Fill the input format (`this+0x20`: rate, channels, mask, bits) and the output
   format (`this+0x38`), and set the mask fields `this+0x28` / `this+0x40`.
7. Call `Process(this, N, &outdesc)` at RVA `0x67D80`.

### The contract with the upstream object

`Process` calls

```c
upstream->vtbl[8](upstream, frames, core);
```

and expects the callee to publish **both**:

* the 12 channel pointers at `core + 0x08` (indexed by WAVE bit position:
  0 FL, 1 FR, 2 FC, 3 LFE, 4 BL, 5 BR, 6 FLC, 7 FRC, 8 BC, 9 SL, 10 SR, 11 TC),
* `core + 0x04` = the number of valid frames. This is the loop bound — if it is
  left at zero, `Process` writes exactly one frame.

`Process` starts by clearing the scratch through `core->ch[0]` for
`12 * max_frames` floats, before it calls the upstream. The upstream call then
overwrites `core->ch[]` with the caller's planes. If `Process` is called a
second time without putting the scratch pointers back, that clear runs over
the caller's input buffer (observed as a page fault at `memset` `+0xC5713` on
the second call). The harness saves the 12 pointers after `SetMaxFrames` and
restores them before every `Process`; that is what makes chunked calls work.

Any frame count above 64 works for the tests here.

### The output descriptor

```c
struct { u32 frames; u32 written; float *ch[12]; };
```

`Process` writes the left ear to `ch[0]` and the right ear to `ch[1]` for this
chain, and increments `written` per frame.

---

## Build

```sh
sudo pacman -S mingw-w64-gcc wine        # or your distro's equivalent
x86_64-w64-mingw32-gcc -O2 -o harness.exe harness.c -lole32
```

A Wine prefix is needed only once:

```sh
WINEPREFIX=$PWD/prefix wineboot -i
```

## Modes

```sh
DLL='Z:\home\you\...\KSUSBAPO64.dll'

# dump the eight all-pass coefficient blocks from the live object
wine harness.exe "$DLL" coef

# render the 8x2 impulse-response matrix
wine harness.exe "$DLL" ir dll_ir        # -> dll_ir_0.raw ... dll_ir_7.raw

# render an arbitrary interleaved file (mask, chunk, channels are optional)
wine harness.exe "$DLL" run in8.raw out2.raw            # 7.1, one 48000-frame call
wine harness.exe "$DLL" run in8.raw out2.raw 0x3F 128   # 5.1, 128-frame Process calls
wine harness.exe "$DLL" run in12.raw out2.raw 0x73F 128 12   # 12ch, BC active
```

Paths inside the prefix use Windows syntax: `Z:\` is `/`.

## Comparison against the port

```sh
python3 compare_port.py      # impulse matrix: ../port/g6ct_cli vs the DLL
python3 compare_signal.py    # 7 signals: noise, -120 dBFS, denormals, DC, tones, step
python3 compare_masks.py     # 25 8ch + 8 12ch masks, plus 128/256-frame chunking
```

All scripts exit non-zero on any sample difference. `compare_port.py` builds
`../port/g6ct_cli` first if you run `make` there.

## Result on the G6 build

```
module base 00006FFFFC280000
ctor: +128=1 +92=128 +520=1 +524=0 core(+536)=0000000000000000
block 0 @0E8: 3F725269 BFF92104 3F800000 BFF92104 3F725269 00000000 00000000 00000000 00000000
...
TOTAL differing samples: 0
WORST abs error: 0.000000e+00
RESULT: PASS - bit-identical to the Creative DSP
```

Full log: [`verification_dll_wine.txt`](verification_dll_wine.txt).

Mask/chunk sweep (`compare_masks.py`): 25 8-channel masks and 8 12-channel
masks, 0 differing samples; 128/256-frame chunked `Process` calls are
bit-identical to a single 48000-frame call. Log:
[`verification_dll_masks.txt`](verification_dll_masks.txt).

---

## Gotchas found the hard way

* **Core first, then `SetMaxFrames`.** `sub_18006F890` does
  `memset(core, 0, 0x328)`; with `core == NULL` this faults inside the DLL at
  `+0xC5713`.
* **The upstream object is `{ void *vtbl; }`, not the vtable itself.** `Process`
  does `mov rax, [this+8]` then `call [rax+0x40]`, so `this+8` must point at a
  struct whose first qword is the vtable.
* **`core+4` is the frame count**, and it is set by the upstream, not by the
  caller.
* The DLL is loaded at `0x6FFFFC280000` under Wine, not at its preferred base —
  always compute entry points as `HMODULE + RVA`, never as an absolute address.
* `-lole32` is required only because the harness calls `CoInitializeEx`; the DSP
  functions themselves need nothing.
