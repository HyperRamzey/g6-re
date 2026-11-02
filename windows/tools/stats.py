"""per-channel stats of a WAV: peak, rms, and magnitude at the probe tones."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wavio

TONES = [440.0, 660.0, 880.0, 60.0, 1000.0, 1300.0, 1700.0, 2100.0]

for path in sys.argv[1:]:
    w = wavio.read(path)
    print("=== %s  %dch %s %dHz  %d frames" % (os.path.basename(path), w.ch, w.bits, w.rate, len(w.frames)))
    for c in range(w.ch):
        pk = wavio.peak(w.frames, c)
        r = wavio.rms(w.frames, c)
        mags = sorted(((wavio.goertzel(w.frames, c, f, w.rate), f) for f in TONES), reverse=True)
        top = " ".join("%.0f:%.4f" % (f, m) for m, f in mags[:3] if m > 1e-5) or "silent"
        print("  ch%d  peak %.6f  rms %.6f  %s" % (c + 1, pk, r, top))
