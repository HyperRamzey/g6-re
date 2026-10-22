#!/usr/bin/env python3
"""Sweep channel masks and Process chunk sizes against the real DLL under Wine.

Runs the same deterministic 8-channel and 12-channel signals through
KSUSBAPO64.dll (via harness.exe) and through ../port/g6ct_cli, then compares
the raw float32 output byte for byte.  Also verifies that a chunked Process
(128 or 256 frames per call) is bit-identical to one 48000-frame call.

Build the two programs first:
    x86_64-w64-mingw32-gcc -O2 -o harness.exe harness.c -lole32
    make -C ../port g6ct_cli

Then:
    python3 compare_masks.py

G6CT_DLL overrides the DLL path, WINEPREFIX the Wine prefix.
"""
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("G6CT_TMP", "/tmp/g6ct-masks")
DLL = os.environ.get(
    "G6CT_DLL",
    "Z:" + os.path.abspath(os.path.join(HERE, "KSUSBAPO64.dll")).replace("/", "\\"),
)
HARNESS = os.path.join(HERE, "harness.exe")
PORT = os.path.join(HERE, "..", "port", "g6ct_cli")
ENV = dict(
    os.environ,
    WINEPREFIX=os.environ.get("WINEPREFIX", os.path.join(HERE, "prefix")),
    WINEDEBUG="-all",
)
FRAMES = 48000

# Every interesting combination of the mask bits the port gates on, plus the
# masks that select no extra channel (0, 0x1, 0x2) and the 0x3 stereo bypass.
MASKS8 = [
    0x63F, 0x3F, 0x3, 0x0, 0x60F, 0x30F, 0x30, 0x600, 0x61F,
    0x43F, 0xFF, 0x73F, 0x1, 0x2, 0x7, 0xF, 0x13, 0x103,
    0x203, 0x303, 0x403, 0x603, 0x703, 0x63B, 0x63D,
]
MASKS12 = [0x63F, 0x73F, 0x7FF, 0x3F, 0x3, 0x0, 0x7F, 0x6FF]

# (mask, frames per Process call, input channels)
CHUNKS = [(0x63F, 128, 8), (0x3F, 256, 8), (0x3, 128, 8),
          (0x73F, 128, 12), (0x7FF, 128, 12)]


def gen(path, frames, channels):
    """Same LCG as the golden inputs, so every run sees identical data."""
    x = 0x67365431
    buf = bytearray(frames * channels * 4)
    off = 0
    for _ in range(frames * channels):
        x = (1664525 * x + 1013904223) & 0xFFFFFFFF
        struct.pack_into("<f", buf, off, ((x >> 8) - 8388608) / 8388608.0)
        off += 4
    with open(path, "wb") as f:
        f.write(buf)


def run(cmd):
    r = subprocess.run(cmd, cwd=HERE, env=ENV, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True)
    if r.returncode:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit("failed: %s" % " ".join(cmd))


def read(path):
    with open(path, "rb") as f:
        return f.read()


def maxerr(a, b):
    n = len(a) // 4
    fa = struct.unpack("<%df" % n, a)
    fb = struct.unpack("<%df" % n, b)
    worst = 0.0
    diffs = 0
    for x, y in zip(fa, fb):
        if x != y:
            diffs += 1
        e = abs(x - y)
        if e > worst:
            worst = e
    return diffs, n, worst


def main():
    os.makedirs(OUT, exist_ok=True)
    inputs = {}
    for ch in (8, 12):
        p = os.path.join(OUT, "in%d.raw" % ch)
        gen(p, FRAMES, ch)
        inputs[ch] = p

    single = {}
    failures = 0

    print("mask sweep (DLL vs port, single Process call):")
    for ch, masks in ((8, MASKS8), (12, MASKS12)):
        for mask in masks:
            tag = "%dch_%03X" % (ch, mask)
            dllp = os.path.join(OUT, "dll_%s.raw" % tag)
            portp = os.path.join(OUT, "port_%s.raw" % tag)
            run(["wine", HARNESS, DLL, "run", inputs[ch], dllp,
                 hex(mask), "0", str(ch)])
            run([PORT, inputs[ch], portp, hex(mask), str(ch)])
            d, p = read(dllp), read(portp)
            single[(ch, mask)] = d
            if len(d) != len(p):
                print("%2dch mask 0x%03X  length %d vs %d  FAIL" % (ch, mask, len(d), len(p)))
                failures += 1
                continue
            diffs, n, worst = maxerr(d, p)
            ok = diffs == 0
            failures += not ok
            print("%2dch mask 0x%03X  bit-diffs %6d/%d  max|err| %.3e  %s"
                  % (ch, mask, diffs, n, worst, "PASS" if ok else "FAIL"))

    print("\nProcess chunking (DLL single vs DLL chunked vs port):")
    for mask, chunk, ch in CHUNKS:
        base = single[(ch, mask)]
        tag = "%dch_%03X_%d" % (ch, mask, chunk)
        dllp = os.path.join(OUT, "chunk_%s.raw" % tag)
        portp = os.path.join(OUT, "chunkport_%s.raw" % tag)
        run(["wine", HARNESS, DLL, "run", inputs[ch], dllp,
             hex(mask), str(chunk), str(ch)])
        run([PORT, inputs[ch], portp, hex(mask), str(ch)])
        d, p = read(dllp), read(portp)
        diffs, n, worst = maxerr(base, d)
        pdiffs, _, pworst = maxerr(d, p)
        ok = diffs == 0 and pdiffs == 0 and len(p) == len(d)
        failures += not ok
        print("%2dch mask 0x%03X chunk %3d  single-vs-chunked %d/%d  port %d/%d  %s"
              % (ch, mask, chunk, diffs, n, pdiffs, n, "PASS" if ok else "FAIL"))

    print("\n%s" % ("PASS - all masks and chunk sizes bit-identical"
                    if failures == 0 else "FAIL - %d case(s)" % failures))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
