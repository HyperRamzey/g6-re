#!/usr/bin/env python
"""
runtests.py - full null-test suite for the g6ct EqualizerAPO port.

For every stimulus it renders the reference with g6ct_cli (the port) and the
actual result through the installed EqualizerAPO config, then compares sample
by sample.

The vectors mirror the ones test_ir.c checks on the C port: the full 7.1 mask,
each matrix input in isolation, an impulse response, broadband noise, and the
stereo-bypass case.
"""
import argparse
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wavio

ROOT = os.path.dirname(HERE)
WORK = os.path.join(ROOT, "work")
BENCH = r"C:\Program Files\EqualizerAPO\BenchmarkFloat.exe"
CLI = os.path.join(ROOT, "build", "g6ct_cli_f64.exe")

# name, channels, mode, only, min SNR (dB) or None for bit-exact
VECTORS = [
    ("tones8",   8, "tones",        "",      130.0),
    ("impulse8", 8, "impulse",      "",      130.0),
    ("noise8",   8, "noise",        "",      130.0),
    ("front",    8, "tones",      "1,2",     130.0),
    ("center",   8, "tones",      "3",       130.0),
    ("lfe",      8, "tones",      "4",       130.0),
    ("back",     8, "tones",      "5,6",     130.0),
    ("side",     8, "tones",      "7,8",     130.0),
    ("stereo2",  2, "tones",        "",        None),
]


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace")


def compare(ref_path, test_path, n, ch_idx):
    """Return (rms_ref, rms_err, max_err, snr, identical, total)."""
    with open(ref_path, "rb") as f:
        raw = f.read()
    vals = struct.unpack("<%df" % (len(raw) // 4), raw)
    w = wavio.read(test_path)
    if w.ch < max(ch_idx) + 1:
        raise SystemExit("%s: %d channels, wanted %s" % (test_path, w.ch, ch_idx))

    stats = []
    for c, src in enumerate(ch_idx):
        acc_ref = acc_err = 0.0
        max_err = 0.0
        ident = 0
        for i in range(n):
            r = vals[i * 2 + c]
            t = w.frames[i][src]
            e = t - r
            acc_ref += r * r
            acc_err += e * e
            if abs(e) > max_err:
                max_err = abs(e)
            if struct.pack("<f", t) == struct.pack("<f", r):
                ident += 1
        stats.append(((acc_ref / n) ** 0.5, (acc_err / n) ** 0.5, max_err, ident, n))
    return stats


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seconds", type=float, default=2.0)
    p.add_argument("--keep", action="store_true", help="keep intermediate files")
    args = p.parse_args()

    os.makedirs(WORK, exist_ok=True)
    rows = []
    failures = 0

    for name, ch, mode, only, snr_min in VECTORS:
        base = os.path.join(WORK, "vt_" + name)
        cmd = [sys.executable, os.path.join(HERE, "mkwav.py"),
               "--out", base, "--channels", str(ch), "--bits", "f32",
               "--seconds", str(args.seconds), "--mode", mode]
        if only:
            cmd += ["--only", only]
        r = run(cmd)
        if r.returncode != 0:
            print("FAIL %-9s generator: %s" % (name, r.stderr.strip()))
            failures += 1
            continue

        ref = base + ".ref.raw"
        if ch == 8:
            r = run([CLI, base + ".f32", ref, "0x63F", "8"])
            if r.returncode != 0:
                print("FAIL %-9s g6ct_cli: %s" % (name, r.stderr.strip()))
                failures += 1
                continue
        else:
            # stereo bypass: the DLL copies the front pair untouched, so the
            # reference is the stimulus itself
            with open(base + ".f32", "rb") as f:
                data = f.read()
            with open(ref, "wb") as f:
                f.write(data)

        out = base + ".eapo.wav"
        r = run([BENCH, "-i", base + ".wav", "-o", out, "-r", "48000",
                 "-c", str(ch), "--nopause"])
        if not os.path.exists(out):
            print("FAIL %-9s equalizerapo: %s" % (name, (r.stdout + r.stderr).strip()[:400]))
            failures += 1
            continue
        if "EndIf was" in r.stdout or "not closed" in r.stdout:
            print("WARN %-9s config: %s" % (name, r.stdout.strip()))

        n = min(len(wavio.read(out).frames), os.path.getsize(base + ".f32") // (4 * ch))
        n = min(n, int(round(args.seconds * 48000)))

        stats = compare(ref, out, n, [0, 1])
        snr = min(20.0 * __import__("math").log10(s[0] / s[1]) if s[1] > 0 else float("inf")
                  for s in stats)
        max_err = max(s[2] for s in stats)
        worst_lsb = max_err * 32768.0

        if snr_min is None:
            ok = max_err == 0.0
            verdict = "PASS (bit-exact)" if ok else "FAIL"
        else:
            ok = snr >= snr_min
            verdict = "PASS" if ok else "FAIL"
        if not ok:
            failures += 1

        rows.append((name, ch, snr, max_err, worst_lsb, verdict))

        if not args.keep:
            for ext in (".wav", ".f32", ".ref.raw", ".eapo.wav"):
                try:
                    os.remove(base + ext)
                except OSError:
                    pass

    print()
    print("%-10s %3s %10s %12s %10s  %s" % ("vector", "ch", "SNR dB", "max_err", "LSB16", "result"))
    print("-" * 68)
    for name, ch, snr, max_err, lsb, verdict in rows:
        print("%-10s %3d %10.2f %12.3e %10.5f  %s"
              % (name, ch, snr, max_err, lsb, verdict))
    print("-" * 68)
    print("%d/%d passed" % (len(rows) - failures, len(rows)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
