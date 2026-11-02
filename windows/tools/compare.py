#!/usr/bin/env python
"""
compare.py - null-test the EqualizerAPO rendering against the g6ct CLI reference.

  compare.py --ref ref2.raw --test out.wav [--lag-search N]

--ref is raw interleaved float32 (g6ct_cli output, 2 channels).
--test is the WAV written by Benchmark; its first two channels are outL/outR.

Reports the residual as absolute error, dB relative to the reference, and in
bits of the 16-bit output, plus how many samples are bit-identical.
"""
import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wavio


def read_raw_f32(path, channels=2):
    with open(path, "rb") as f:
        raw = f.read()
    n = len(raw) // (4 * channels)
    vals = struct.unpack("<%df" % (n * channels), raw[:n * channels * 4])
    return [[vals[i * channels + c] for c in range(channels)] for i in range(n)]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ref", required=True)
    p.add_argument("--test", required=True)
    p.add_argument("--test-channels", default="0,1")
    p.add_argument("--lag-search", type=int, default=0)
    p.add_argument("--label", default="")
    args = p.parse_args()

    ref = read_raw_f32(args.ref, 2)
    w = wavio.read(args.test)
    tch = [int(x) for x in args.test_channels.split(",")]
    if w.ch < max(tch) + 1:
        raise SystemExit("%s has %d channels, cannot read %s" % (args.test, w.ch, tch))

    n = min(len(ref), len(w.frames))
    if len(ref) != len(w.frames):
        print("WARNING: length mismatch ref=%d test=%d, comparing %d frames"
              % (len(ref), len(w.frames), n))

    lag = 0
    if args.lag_search:
        best = None
        for cand in range(-args.lag_search, args.lag_search + 1):
            acc = 0.0
            cnt = 0
            for i in range(0, n - abs(cand), 7):
                r = ref[i]
                j = i + cand
                if j < 0 or j >= n:
                    continue
                acc += (r[0] - w.frames[j][tch[0]]) ** 2 + (r[1] - w.frames[j][tch[1]]) ** 2
                cnt += 2
            if cnt and (best is None or acc / cnt < best[0]):
                best = (acc / cnt, cand)
        lag = best[1]

    print("=== %s" % (args.label or args.test))
    print("    ref : %s  (%d frames)" % (os.path.basename(args.ref), len(ref)))
    print("    test: %s  (%d frames, %d ch %s, read ch %s)" %
          (os.path.basename(args.test), len(w.frames), w.ch, w.bits, tch))
    print("    lag : %+d samples" % lag)

    per = []
    for c, src in enumerate(tch):
        crest = 0.0
        acc_ref = acc_err = 0.0
        maxerr = 0.0
        maxerr_at = -1
        ident = 0
        for i in range(n):
            j = i + lag
            if j < 0 or j >= n:
                continue
            r = ref[i][c]
            t = w.frames[j][src]
            e = t - r
            crest = max(crest, abs(r))
            acc_ref += r * r
            acc_err += e * e
            if abs(e) > maxerr:
                maxerr, maxerr_at = abs(e), i
            if struct.pack("<f", t) == struct.pack("<f", r):
                ident += 1
        rms_ref = (acc_ref / n) ** 0.5
        rms_err = (acc_err / n) ** 0.5
        snr = 20.0 * __import__("math").log10(rms_ref / rms_err) if rms_err > 0 else float("inf")
        lsb16 = maxerr * 32768.0
        per.append((crest, rms_err, snr, maxerr, lsb16, ident))
        print("    ch%d peak_ref %.6f  rms_err %.3e  SNR %.2f dB  max_err %.3e "
              "(%.4f LSB16 @ %d)  bit-identical %d/%d"
              % (c + 1, crest, rms_err, snr, maxerr, lsb16, maxerr_at, ident, n))

    worst = max(p[1] for p in per)
    worst_lsb = max(p[4] for p in per)
    print("    ---> worst rms_err %.3e   worst max_err %.4f LSB16" % (worst, worst_lsb))


if __name__ == "__main__":
    main()
