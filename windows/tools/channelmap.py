"""Identify which logical channel each WAVE index carries.

Runs inside the EqualizerAPO Benchmark harness, so the index space here is
exactly the one `Copy:`/`Channel:` addresses.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wavio

TONES = [440.0, 660.0, 880.0, 60.0, 1000.0, 1300.0, 1700.0, 2100.0]
NAMES = ["FL", "FR", "FC", "LFE", "BL", "BR", "SL", "SR"]

work = sys.argv[1]

print("reference tones8.wav (input), per-channel dominant tone:")
ref = wavio.read(os.path.join(work, "tones8.wav"))
for c in range(ref.ch):
    mags = [(wavio.goertzel(ref.frames, c, f, ref.rate), f) for f in TONES]
    mags.sort(reverse=True)
    print("  wav ch%d  tone %.0f Hz  (mag %.4f)" % (c + 1, mags[0][1], mags[0][0]))

print("\nzeroed-channel runs (config: Copy: N=0.0):")
for n in range(1, 9):
    path = os.path.join(work, "z%d.wav" % n)
    w = wavio.read(path)
    silent = [c + 1 for c in range(w.ch) if wavio.peak(w.frames, c) < 1e-6]
    # which tone is missing, i.e. which source channel was silenced
    missing = []
    for c in range(w.ch):
        for idx, f in enumerate(TONES):
            m = wavio.goertzel(w.frames, c, f, w.rate)
            if m < 1e-4 and wavio.goertzel(ref.frames, c, f, ref.rate) > 1e-3:
                missing.append((c + 1, NAMES[idx]))
    print("  config Copy:%d=0.0 -> zero channels %s | missing tone in %s"
          % (n, silent, missing))
