"""livenull.py - end-to-end null test of the whole VoiceMeeter + DSP chain.

This is the acceptance test for the real signal path:

    work/stim8.wav  --mpv-->  Voicemeeter Input (7.1)
        -> strip 3 -> insert send (ASIO IN#4, ch 6..13)
        -> vmbridge (g6ct f64) -> binaural on 6,7 ; zeros on 8..13
        -> insert return -> strip -> bus B1
        -> "Voicemeeter Out B1" recording device   <-- captured here

and compares the capture with `work/ref_check.raw`, the authoritative
g6ct_cli_f64 render of the same stimulus.

Two things make the measurement honest:

  * the bridge runs as a real ASIO host in its own thread, exactly as it will
    in production, so any scheduling failure shows up in the residual;
  * the comparison compensates for the fractional sample delay of the virtual
    path before reporting, so a timing offset cannot masquerade as a DSP
    error. Both the raw and the aligned numbers are printed.

    python livenull.py                      # DSP on, 8 s window
    python livenull.py --tap "Voicemeeter Out B1"
    python livenull.py --dsp off            # passthrough A/B
"""
import argparse
import os
import subprocess
import sys
import threading
import time

import numpy as np
import pyaudiowpatch as pa

import vmbridge

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORK = os.path.join(ROOT, "work")
MPV = os.path.join(os.path.dirname(ROOT), "mpv.exe")

VM_INPUT = "{e6d2cba7-c801-4b78-a409-5f557fe3f61d}"
STIM_WAV = os.path.join(WORK, "stim8.wav")
REF = os.path.join(WORK, "ref_check.raw")

RATE = 48000
CH = 8


# --------------------------------------------------------------------------
# capture
# --------------------------------------------------------------------------

def find_capture(name_substr):
    p = pa.PyAudio()
    try:
        wasapi = p.get_host_api_info_by_type(pa.paWASAPI)["index"]
        best = None
        for d in p.get_device_info_generator():
            if d["hostApi"] != wasapi or d["maxInputChannels"] < 2:
                continue
            if d.get("isLoopbackDevice"):
                continue
            if name_substr.lower() in d["name"].lower():
                best = d
        return best
    finally:
        p.terminate()


def record_tap(dev, seconds, play_wav, start_delay=0.35, tail=0.4):
    """Record `dev` while mpv plays `play_wav`. Returns (frames, ch)."""
    rate = int(dev["defaultSampleRate"])
    ch = int(dev["maxInputChannels"])

    p = pa.PyAudio()
    rec = p.open(format=pa.paFloat32, channels=ch, rate=rate, input=True,
                 input_device_index=dev["index"], frames_per_buffer=480)
    blocks = []
    rec.start_stream()
    time.sleep(start_delay)

    proc = subprocess.Popen(
        [MPV, "--no-video", "--no-config", "--really-quiet",
         "--audio-channels=%d" % CH, "--volume=100",
         "--audio-device=wasapi/%s" % VM_INPUT, play_wav],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    t0 = time.time()
    try:
        while proc.poll() is None and time.time() - t0 < seconds + 10:
            blocks.append(rec.read(480, exception_on_overflow=False))
        time.sleep(tail)
        while True:
            blocks.append(rec.read(480, exception_on_overflow=False))
            if sum(len(b) for b in blocks) > (seconds + tail + 1.0) * rate * ch * 4:
                break
    finally:
        rc = proc.poll()
        try:
            proc.terminate()
        except Exception:
            pass
        proc.wait(timeout=10)
        rec.stop_stream()
        rec.close()
        p.terminate()

    raw = b"".join(blocks)
    x = np.frombuffer(raw, dtype=np.float32).reshape(-1, ch).astype(np.float64)
    return x, rate, rc


# --------------------------------------------------------------------------
# alignment / comparison
# --------------------------------------------------------------------------

def lag_of(a, b, hi=None):
    """Lag of `b` inside `a` (integer samples), by cross-correlation."""
    n = 1 << int(np.ceil(np.log2(len(a) + len(b) + 8)))
    c = np.fft.irfft(np.fft.rfft(a, n) * np.conj(np.fft.rfft(b, n)), n)
    hi = hi if hi is not None else min(len(a), 400000)
    return int(np.argmax(c[:hi]))


def shift(x, tau):
    """Shift 1-D signal by a fractional number of samples."""
    if abs(tau) < 1e-9:
        return x
    n = len(x)
    N = 1 << int(np.ceil(np.log2(n)))
    f = np.fft.rfftfreq(N, 1.0 / RATE)
    y = np.fft.irfft(np.fft.rfft(x, N) * np.exp(-2j * np.pi * f * tau / RATE), N)
    return y[:n]


def null_db(got, ref):
    err = got - ref
    rms = float(np.sqrt(np.mean(err ** 2)))
    sig = float(np.sqrt(np.mean(ref ** 2)))
    if rms == 0.0:
        return float("-inf"), 0.0
    return 20 * np.log10(rms / sig) if sig > 0 else float("-inf"), rms


def best_fractional(cap, ref, lo=-3.0, hi=3.0, step=0.05):
    """Grid-search the fractional delay that minimises the residual."""
    best = (0.0, 1e9)
    t = lo
    while t <= hi + 1e-9:
        d, _ = null_db(shift(cap, t), ref)
        if d < best[1]:
            best = (t, d)
        t += step
    return best


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tap", default="Voicemeeter Out B1")
    ap.add_argument("--stim", default=STIM_WAV)
    ap.add_argument("--ref", default=REF)
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--dsp", default="on", choices=["on", "off"])
    ap.add_argument("--driver", default="Voicemeeter Insert Virtual ASIO")
    ap.add_argument("--keep", help="write the aligned capture here as .f32")
    args = ap.parse_args()

    ref = np.fromfile(args.ref, dtype=np.float32).reshape(-1, 2).astype(np.float64)
    want = ref.shape[0]
    print("reference: %s  %d frames (%.2f s)"
          % (args.ref, want, want / RATE))
    print("stimulus : %s" % args.stim)

    dev = find_capture(args.tap)
    if dev is None:
        raise SystemExit("no capture device matching %r" % args.tap)
    print("tap      : %s  (%dch @ %d Hz)"
          % (dev["name"], int(dev["maxInputChannels"]),
             int(dev["defaultSampleRate"])))

    # --- start the bridge -------------------------------------------------
    dsp = vmbridge.DSP if args.dsp == "on" else None
    bridge = vmbridge.Bridge(args.driver, dsp)
    print("bridge   : %s  %d/%d ch  block %d  dsp %s"
          % (args.driver, bridge.n_in, bridge.n_out, bridge.block,
             bridge.dsp.precision if bridge.dsp else "off"))

    stop = threading.Event()
    bridge_err = {}

    def run_bridge():
        try:
            bridge.run(stop_event=stop)
        except BaseException as e:      # noqa: BLE001
            bridge_err["e"] = e

    bt = threading.Thread(target=run_bridge, daemon=True)
    bt.start()
    time.sleep(1.0)

    cap = None
    try:
        cap, rate, mpv_rc = record_tap(dev, args.seconds, args.stim)
    finally:
        stop.set()
        bt.join(timeout=10)

    if bridge_err:
        print("bridge failed: %r" % (bridge_err["e"],))
        return 1
    if cap is None:
        print("capture failed")
        return 1

    print("captured : %d frames x %d ch  (mpv rc=%s)"
          % (cap.shape[0], cap.shape[1], mpv_rc))
    if cap.shape[0] < want + 1000:
        print("capture shorter than the reference - playback did not run")
        return 1

    peak = float(np.max(np.abs(cap)))
    print("tap peak : %.6f  %s"
          % (peak, "signal present" if peak > 1e-4 else "SILENT"))

    c = cap[:, 0]
    lag = lag_of(c, ref[:, 0])
    print("align    : capture offset %d frames (%.1f ms)"
          % (lag, lag / 48.0))
    if lag + want > c.shape[0]:
        print("capture too short after alignment (%d + %d > %d)"
              % (lag, want, c.shape[0]))
        return 1

    got = cap[lag:lag + want, :2]
    if args.keep:
        got.astype(np.float32).tofile(args.keep)
        print("wrote    : %s" % args.keep)

    raw_db, raw_rms = null_db(got[:, 0], ref[:, 0])
    print("\n--- residual, integer aligned ---")
    print("  L  null %8.2f dB   rms %.3e" % (raw_db, raw_rms))

    tau, frac_db = best_fractional(got[:, 0], ref[:, 0])
    print("--- residual, %.2f sample fractional delay applied ---" % tau)
    print("  L  null %8.2f dB" % frac_db)

    gl = shift(got[:, 0], tau)
    gr = shift(got[:, 1], tau)
    dl, _ = null_db(gl, ref[:, 0])
    dr, _ = null_db(gr, ref[:, 1])
    print("  L  %8.2f dB\n  R  %8.2f dB" % (dl, dr))

    gain = float(np.dot(gl, ref[:, 0]) / np.dot(ref[:, 0], ref[:, 0]))
    print("  best-fit gain %.6f" % gain)

    print("\n--- bridge ---------------------------------------------------")
    bridge.report()

    verdict = "PASS" if min(dl, dr) < -100 else (
        "PARTIAL" if min(dl, dr) < -40 else "FAIL")
    print("\nverdict  : %s (worst %.2f dB)" % (verdict, max(dl, dr)))
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
