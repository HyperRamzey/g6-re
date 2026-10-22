#!/usr/bin/env python3
"""Compare the port (g6ct_cli) against the real KSUSBAPO64.dll rendered under Wine."""
import os, struct, subprocess, sys

N = 4096
HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "..", "port", "g6ct_cli")
OUT = os.environ.get("G6CT_TMP", "/tmp/g6ct-ab")
os.makedirs(OUT, exist_ok=True)

def read_f32(path):
    with open(path, "rb") as f:
        return list(struct.unpack("<%df" % (os.path.getsize(path)//4), f.read()))

total_bad = 0
worst = 0.0
print(f"{'ch':>2} {'name':<4} {'max|err|':>12} {'bit-diffs':>10}  first taps (L)")
for ch in range(8):
    name = ["FL","FR","FC","LFE","BL","BR","SL","SR"][ch]
    # impulse input, 8ch interleaved
    frames = bytearray(N * 8 * 4)
    struct.pack_into("<f", frames, ch * 4, 1.0)
    inp = f"{OUT}/in_{ch}.raw"
    with open(inp, "wb") as f:
        f.write(frames)
    outp = f"{OUT}/port_{ch}.raw"
    subprocess.run([CLI, inp, outp, str(0x63F)], check=True)
    port = read_f32(outp)
    dll  = read_f32(os.path.join(HERE, f"dll_ir_{ch}.raw"))
    assert len(port) == len(dll) == N * 2, (len(port), len(dll))
    maxerr = 0.0
    diffs = 0
    for a, b in zip(port, dll):
        if a != b:
            diffs += 1
        e = abs(a - b)
        if e > maxerr:
            maxerr = e
    worst = max(worst, maxerr)
    total_bad += diffs
    total_bad += 0
    print(f"{ch:>2} {name:<4} {maxerr:12.3e} {diffs:10d}  "
          + " ".join(f"{dll[i*2]:+.6f}" for i in range(3)))
print()
print("TOTAL differing samples:", total_bad)
print("WORST abs error: %.6e" % worst)
print("RESULT:", "PASS - bit-identical to the Creative DSP" if total_bad == 0 else "FAIL")
sys.exit(0 if total_bad == 0 else 1)
