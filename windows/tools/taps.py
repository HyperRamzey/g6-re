#!/usr/bin/env python
"""
taps.py - per-channel impulse response of the EqualizerAPO path, compared with
the numbers test_ir (upstream oracle) prints for the C port.

test_ir renders a unit impulse per input channel and prints the first taps of
the resulting L and R signals. If the config really implements the same matrix
and the same four all-pass branches, the taps must agree.

    channel     first taps L
    FL       +0.060467 -0.748967 +0.396100 +0.352166 +0.243675
    FR       +0.000000 -0.000000 ...
    FC       +0.042750 -0.529520 +0.280043 +0.248981 +0.172278
    LFE      +0.042750 -0.529520 +0.280043 +0.248981 +0.172278
    BL       -0.178277 +0.071635 +0.674108 -0.155703 +0.043191
    BR       -0.140399 +0.056415 +0.530882 -0.122621 +0.034014
    SL       -0.198464 +0.079746 +0.750439 -0.173334 +0.048081
    SR       -0.110005 +0.044202 +0.415957 -0.096076 +0.026651
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)
WORK = os.path.join(ROOT, "work")
BENCH = r"C:\Program Files\EqualizerAPO\BenchmarkFloat.exe"

NAMES = ["FL", "FR", "FC", "LFE", "BL", "BR", "SL", "SR"]
EXPECT_L = {
    1: [0.060467, -0.748967, 0.396100, 0.352166, 0.243675],
    2: [0.0, 0.0, 0.0, 0.0, 0.0],
    3: [0.042750, -0.529520, 0.280043, 0.248981, 0.172278],
    4: [0.042750, -0.529520, 0.280043, 0.248981, 0.172278],
    5: [-0.178277, 0.071635, 0.674108, -0.155703, 0.043191],
    6: [-0.140399, 0.056415, 0.530882, -0.122621, 0.034014],
    7: [-0.198464, 0.079746, 0.750439, -0.173334, 0.048081],
    8: [-0.110005, 0.044202, 0.415957, -0.096076, 0.026651],
}


def render(ch, seconds=0.2):
    import wavio
    base = os.path.join(WORK, "tap_%d" % ch)
    subprocess.run([sys.executable, os.path.join(HERE, "mkwav.py"), "--out", base,
                    "--channels", "8", "--bits", "f32", "--seconds", str(seconds),
                    "--mode", "impulse", "--only", str(ch)],
                   check=True, capture_output=True)
    out = base + ".eapo.wav"
    subprocess.run([BENCH, "-i", base + ".wav", "-o", out, "-r", "48000",
                    "-c", "8", "--nopause"], check=True, capture_output=True)
    w = wavio.read(out)
    taps = ([w.frames[i][0] for i in range(5)], [w.frames[i][1] for i in range(5)])
    for ext in (".wav", ".f32", ".eapo.wav"):
        try:
            os.remove(base + ext)
        except OSError:
            pass
    return taps


def main():
    print("%-4s %-32s %-32s %s" % ("ch", "L (measured)", "L (test_ir)", "max dev"))
    print("-" * 96)
    worst = 0.0
    fails = 0
    for ch in range(1, 9):
        tl, tr = render(ch)
        exp = EXPECT_L[ch]
        dev = max(abs(a - b) for a, b in zip(tl, exp))
        worst = max(worst, dev)
        ok = dev < 5e-7
        if not ok:
            fails += 1
        print("%-4s %-32s %-32s %.2e %s"
              % (NAMES[ch - 1], " ".join("%+9.6f" % v for v in tl),
                 " ".join("%+9.6f" % v for v in exp), dev, "" if ok else "  <-- MISMATCH"))
        if ch in (5, 6, 7, 8):
            print("     %-32s %-32s" % (" ".join("%+9.6f" % v for v in tr), "(R: cross term)"))
    print("-" * 96)
    print("worst deviation from test_ir taps: %.2e   (%d mismatches)" % (worst, fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
