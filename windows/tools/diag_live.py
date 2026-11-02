"""diag_live.py - model the port in numpy and find out what the live capture
actually contains.

The live path now demonstrably runs the config (the audiodg trace shows the
`Matching stage "pre-mix"` and `If(inputChannelCount == 8) evaluated to true`
lines, and channels 3..8 of the loopback capture are exactly zero, which only
the final `Copy:` can produce). The front pair is nevertheless off by more than
rounding, so this rebuilds every intermediate signal of the chain and fits the
capture against them.

  python diag_live.py --stim work/stim8.f32 --ref work/ref_check.raw \
                      --cap work/live8.f32 --lag 13120
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# (b0, b1, b2, a1, a2) exactly as stored in g6ct.txt
AP = {
    "A": (0.9465699791908264, -1.9463200569152832, 1.0,
          -1.9463200569152832, 0.9465699791908264),
    "C": (-0.26050201058387756, 0.025690000504255295, 1.0,
          0.025690000504255295, -0.26050201058387756),
    "B": (0.06387999653816223, -0.8377400040626526, 1.0,
          -0.8377400040626526, 0.06387999653816223),
    "D": (0.8706859946250916, -1.868499994277954, 1.0,
          -1.868499994277954, 0.8706859946250916),
}


def allpass(x, coeffs):
    b0, b1, b2, a1, a2 = coeffs
    y = np.empty_like(x, dtype=np.float64)
    x1 = x2 = y1 = y2 = 0.0
    for i in range(len(x)):
        xn = x[i]
        yn = b0 * xn + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        y[i] = yn
        x2, x1 = x1, xn
        y2, y1 = y1, yn
    return y


def snr(ref, test):
    err = test - ref
    r = np.sqrt(np.mean(ref.astype(np.float64) ** 2))
    q = np.sqrt(np.mean(err.astype(np.float64) ** 2))
    return (20 * np.log10(r / q) if q > 0 else float("inf")), q, float(np.max(np.abs(err)))


def fit(a, b):
    """Scalar g minimising |a*g - b|, plus the residual SNR."""
    g = float(np.dot(a, b) / np.dot(a, a))
    s, q, m = snr(a * g, b)
    return g, s, q, m


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--stim", required=True)
    p.add_argument("--ref", required=True)
    p.add_argument("--cap", required=True)
    p.add_argument("--lag", type=int, required=True)
    p.add_argument("--channels", type=int, default=8)
    args = p.parse_args()

    stim = np.fromfile(args.stim, dtype=np.float32).reshape(-1, args.channels)
    ref = np.fromfile(args.ref, dtype=np.float32).reshape(-1, 2)
    cap = np.fromfile(args.cap, dtype=np.float32).reshape(-1, args.channels)
    n = min(len(stim), len(ref), len(cap) - args.lag)
    stim = stim[:n].astype(np.float64)
    ref = ref[:n].astype(np.float64)
    live = cap[args.lag:args.lag + n].astype(np.float64)
    print("frames: %d   lag: %+d" % (n, args.lag))

    FL, FR, FC, LFE, BL, BR, SL, SR = (stim[:, i] for i in range(8))
    k = 0.7070000171661377
    frontL = FL + k * FC + k * LFE
    frontR = FR + k * FC + k * LFE
    surL = (0.7860000133514404 * BL + 0.6190000176429749 * BR
            + 0.875 * SL + 0.48500001430511475 * SR)
    surR = (0.6190000176429749 * BL + 0.7860000133514404 * BR
            + 0.48500001430511475 * SL + 0.875 * SR)

    A_fl, C_sl = allpass(frontL, AP["A"]), allpass(surL, AP["C"])
    A_fr, C_sr = allpass(frontR, AP["A"]), allpass(surR, AP["C"])
    B_Afl, D_Csl = allpass(A_fl, AP["B"]), allpass(C_sl, AP["D"])
    B_Afr, D_Csr = allpass(A_fr, AP["B"]), allpass(C_sr, AP["D"])

    model = (B_Afl + D_Csl, B_Afr - D_Csr)

    print("\n=== the numpy model vs the C reference ===")
    for c in range(2):
        s, q, m = snr(ref[:, c], model[c])
        print("  ch%d  SNR %8.2f dB  rms_err %.3e  max_err %.3e" % (c + 1, s, q, m))

    print("\n=== what the capture looks like ===")
    names = {
        "model (full chain)": model,
        "front branch only": (B_Afl, B_Afr),
        "surround branch only": (D_Csl, D_Csr),
        "front+surround, no allpass": (frontL + surL, frontR - surR),
        "front only, no allpass": (frontL, frontR),
        "raw stimulus ch1/ch2": (FL, FR),
    }
    for label, pair in names.items():
        row = []
        for c in range(2):
            g, s, q, m = fit(pair[c], live[:, c])
            row.append("ch%d g=%.4f SNR %7.2f" % (c + 1, g, s))
        print("  %-28s %s" % (label, "   ".join(row)))

    print("\n=== two-term least squares: live ~ a*front + b*sur ===")
    X = np.stack([B_Afl, D_Csl], axis=1)
    coef, *_ = np.linalg.lstsq(X, live[:, 0], rcond=None)
    res = live[:, 0] - X @ coef
    print("  ch1  a=%.6f  b=%.6f  residual rms %.3e" %
          (coef[0], coef[1], float(np.sqrt(np.mean(res ** 2)))))
    X2 = np.stack([B_Afr, D_Csr], axis=1)
    coef2, *_ = np.linalg.lstsq(X2, live[:, 1], rcond=None)
    res2 = live[:, 1] - X2 @ coef2
    print("  ch2  a=%.6f  b=%.6f  residual rms %.3e" %
          (coef2[0], coef2[1], float(np.sqrt(np.mean(res2 ** 2)))))

    print("\n=== spectrum of the residual against the model ===")
    for c in range(2):
        g, s, q, m = fit(model[c], live[:, c])
        res = live[:, c] - model[c] * g
        spec = np.abs(np.fft.rfft(res * np.hanning(n)))
        freqs = np.fft.rfftfreq(n, 1 / 48000.0)
        idx = np.argsort(spec)[-6:][::-1]
        print("  ch%d residual peaks: %s" % (c + 1, ", ".join(
            "%.0f Hz (%.3e)" % (freqs[i], spec[i]) for i in idx)))
        spec_ref = np.abs(np.fft.rfft(model[c] * np.hanning(n)))
        idx2 = np.argsort(spec_ref)[-10:][::-1]
        print("       reference peaks: %s" % ", ".join(
            "%.0f Hz" % freqs[i] for i in idx2))


if __name__ == "__main__":
    main()
