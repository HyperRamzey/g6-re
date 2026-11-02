"""idcheck.py - what does the G733 endpoint do to an 8-channel stream on its own?

Plays the null-test stimulus with an identity EqualizerAPO config installed and
records the loopback. With no DSP of ours in the path, whatever shows up is the
endpoint's own transfer function: gain, filtering, crosstalk, limiting.

Reports, per capture channel:
  * the best-fit scalar gain from the matching stimulus channel
  * the residual SNR after that gain (distortion / modulation)
  * the full 8x8 least-squares mixing matrix stim -> capture, which exposes any
    hidden downmix or crosstalk between channels.

  python idcheck.py --stim work/stim8.f32 --out work/id8.f32 [--scale 1.0]
"""
import argparse

import numpy as np

import livecheck


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stim", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="Logitech G733")
    ap.add_argument("--scale", type=float, default=1.0,
                    help="multiply the stimulus (probe level dependence)")
    ap.add_argument("--lag", type=int, default=None)
    args = ap.parse_args()

    import pyaudiowpatch as pa

    p = pa.PyAudio()
    try:
        render_dev, loop_dev = livecheck.find_devices(p, args.name)
    finally:
        p.terminate()

    ch = int(render_dev["maxOutputChannels"])
    rate = int(render_dev["defaultSampleRate"])
    stim = np.fromfile(args.stim, dtype=np.float32).reshape(-1, ch) * args.scale
    print("render idx %d  %dch %dHz   stimulus %d frames peak %.6f (scale %.3f)"
          % (render_dev["index"], ch, rate, len(stim),
             float(np.max(np.abs(stim))), args.scale))

    cap = livecheck.record(render_dev, loop_dev, stim, rate, ch)
    cap.astype(np.float32).tofile(args.out)
    print("captured %d frames -> %s" % (len(cap), args.out))

    if args.lag is None:
        # correlate the loudest stimulus channel with the same capture channel
        loud = int(np.argmax(np.max(np.abs(stim), axis=0)))
        lag = livecheck.best_lag(stim[:, loud], cap[:, loud], max_lag=rate // 2)
    else:
        lag = args.lag
    print("alignment: capture starts %+d samples after the stimulus" % lag)

    n = min(len(stim), len(cap) - lag)
    s = stim[:n].astype(np.float64)
    c = cap[lag:lag + n].astype(np.float64)
    print("comparing %d frames\n" % n)

    print("=== per-channel gain and residual ===")
    print("  cap  stimpk    cappk      gain    SNR(dB)  max_err")
    for k in range(ch):
        a, b = s[:, k], c[:, k]
        rms_a = float(np.sqrt(np.mean(a ** 2)))
        if rms_a < 1e-9:
            print("  ch%d  %8.6f  %8.6f  %9s  %8s  %.3e"
                  % (k + 1, rms_a, float(np.max(np.abs(b))), "-", "-",
                     float(np.max(np.abs(b)))))
            continue
        g = float(np.dot(a, b) / np.dot(a, a))
        e = b - g * a
        q = float(np.sqrt(np.mean(e ** 2)))
        snr = 20 * np.log10(rms_a * abs(g) / q) if q > 0 else float("inf")
        print("  ch%d  %8.6f  %8.6f  %9.6f  %8.2f  %.3e"
              % (k + 1, rms_a, float(np.max(np.abs(b))), g, snr,
                 float(np.max(np.abs(e)))))

    print("\n=== 8x8 mixing matrix  (rows = capture ch, cols = stimulus ch) ===")
    print("        " + "".join("   stim%d " % (k + 1) for k in range(ch)))
    for r in range(ch):
        row = []
        for k in range(ch):
            a = s[:, k]
            den = float(np.dot(a, a))
            row.append(float(np.dot(a, c[:, r]) / den) if den > 1e-12 else 0.0)
        print("  cap%d  " % (r + 1) + "".join("%+8.5f" % v for v in row))

    print("\n=== is the capture a scaled copy of the stimulus on the diagonal? ===")
    diag = [float(np.dot(s[:, k], c[:, k]) / np.dot(s[:, k], s[:, k]))
            for k in range(ch) if np.dot(s[:, k], s[:, k]) > 1e-12]
    print("  diagonal gains: " + " ".join("%.6f" % g for g in diag))
    print("  spread: %.3e" % (np.max(diag) - np.min(diag)))

    print("\n=== largest residual samples, capture ch1 ===")
    a, b = s[:, 0], c[:, 0]
    g = float(np.dot(a, b) / np.dot(a, a))
    e = b - g * a
    idx = np.argsort(np.abs(e))[-8:][::-1]
    for i in idx:
        print("  %6d  stim %+8.6f  cap %+8.6f  g*stim %+8.6f  err %+8.6f"
              % (i, a[i], b[i], g * a[i], e[i]))


if __name__ == "__main__":
    main()
