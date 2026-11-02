"""livecheck_mpv.py - end-to-end null test with mpv as the client.

PortAudio refuses to open an 8-channel stream on a 2-channel endpoint (it
validates against the device's channel count), while WASAPI itself accepts a
7.1 shared-mode stream there - mpv proves it:

    [ao/wasapi] Trying 7.1 float (32/32 bits) @ 48000hz (shared) -> ok

So the stimulus player has to be mpv, and the capture is a plain 2-channel
loopback recorded in parallel. Everything after that is the same lag-search
null test as livecheck.py.

mpv is only a convenient 7.1 stream source. The EqualizerAPO effect lives in
the endpoint's SFX slot inside audiodg, so it sees every application's stream,
not just mpv's.

  python livecheck_mpv.py --wav ..\\work\\stim8.wav --ref ..\\work\\ref_check.raw
                          --out ..\\work\\live2ch.f32 [--volume 100]
"""
import argparse
import os
import subprocess
import threading
import time

import numpy as np
import pyaudiowpatch as pa

import livecheck as lc

# mpv is only used as a test client; point MPV at it if it is not on PATH.
MPV = os.environ.get("MPV", "mpv.exe")


class Recorder:
    """Records a loopback device from start() until stop() is called."""

    def __init__(self, loop_dev, in_ch, rate, chunk=480):
        self.in_ch = in_ch
        self.rate = rate
        self.chunk = chunk
        self.blocks = []
        self.error = None
        self._stop = threading.Event()
        self._thread = None
        self._pa = pa.PyAudio()
        try:
            self.stream = self._pa.open(
                format=pa.paFloat32, channels=in_ch, rate=rate, input=True,
                input_device_index=loop_dev["index"],
                frames_per_buffer=chunk)
        except Exception:
            self._pa.terminate()
            raise

    def _run(self):
        try:
            while not self._stop.is_set():
                self.blocks.append(self.stream.read(self.chunk,
                                                   exception_on_overflow=False))
        except Exception as e:  # noqa: BLE001 - re-raised by stop()
            self.error = e

    def start(self):
        self.stream.start_stream()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def stop(self, drain=0.35):
        # Let the tail the device still holds come through, then stop reading.
        time.sleep(drain)
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        try:
            self.stream.stop_stream()
            self.stream.close()
        finally:
            self._pa.terminate()
        if self.error is not None:
            raise self.error
        raw = b"".join(self.blocks)
        return np.frombuffer(raw, dtype=np.float32).reshape(-1, self.in_ch).copy()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", required=True)
    ap.add_argument("--ref", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="Logitech G733")
    ap.add_argument("--mpv", default=MPV)
    ap.add_argument("--volume", type=float, default=100.0)
    ap.add_argument("--start-delay", type=float, default=0.4,
                    help="seconds of loopback to record before mpv starts")
    args = ap.parse_args()

    ref2 = np.fromfile(args.ref, dtype=np.float32)
    if ref2.size % 2:
        raise SystemExit("reference must be interleaved 2ch float32")
    ref2 = ref2.reshape(-1, 2)

    p = pa.PyAudio()
    try:
        render_dev, loop_dev = lc.find_devices(p, args.name)
    finally:
        p.terminate()
    in_ch = int(loop_dev["maxInputChannels"])
    rate = int(render_dev["defaultSampleRate"])
    print("render  : idx %-3d %dch device  %dHz  %s"
          % (render_dev["index"], int(render_dev["maxOutputChannels"]), rate,
             render_dev["name"]))
    print("loopback: idx %-3d %dch  %s" % (loop_dev["index"], in_ch, loop_dev["name"]))

    # Volume stays at 100 with mpv's own softvol: passing --softvol=no makes
    # mpv exit with rc=1 before it ever opens the device (verified on this
    # machine), which silently turns every probe into a "silence" result.
    cmd = [args.mpv, "--no-video", "--no-config", "--really-quiet",
           "--audio-device=wasapi",
           "--audio-channels=8", "--volume=%g" % args.volume, args.wav]
    print("cmd     : " + " ".join(cmd))

    rec = Recorder(loop_dev, in_ch, rate).start()
    time.sleep(args.start_delay)
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    played = time.time() - t0
    cap = rec.stop()
    if r.returncode != 0:
        print("mpv failed (%d): %s" % (r.returncode, r.stderr[-800:]))
    print("mpv played %.2f s" % played)

    cap.astype(np.float32).tofile(args.out)
    print("captured %d frames (%.3f s) -> %s" % (len(cap), len(cap) / rate, args.out))

    lag = lc.best_lag(ref2[:, 0], cap[:, 0], max_lag=rate // 2)
    print("\nalignment: capture starts %+d samples after the reference" % lag)
    n = min(len(ref2), max(0, len(cap) - lag))
    if n <= 0:
        raise SystemExit("capture too short after alignment")
    print("comparing %d frames\n" % n)
    aligned = cap[lag:lag + n]

    front = [lc.stats(ref2[:n, c], aligned[:, c], "ch%d" % (c + 1))
             for c in range(min(in_ch, 2))]
    rest = [lc.stats(np.zeros(n, np.float32), aligned[:, c], "ch%d" % (c + 1))
            for c in range(2, in_ch)]

    print("\n=== least-squares gain: reference -> capture ===")
    gains = []
    for c in range(len(front)):
        a = ref2[:n, c].astype(np.float64)
        b = aligned[:, c].astype(np.float64)
        g = float(np.dot(a, b) / np.dot(a, a))
        e = b - g * a
        q = float(np.sqrt(np.mean(e ** 2)))
        rms = float(np.sqrt(np.mean(a ** 2)))
        snr = 20 * np.log10(rms * abs(g) / q) if q > 0 else float("inf")
        gains.append(g)
        print("  ch%d  gain %.9f (%+.3f dB)  SNR after gain %8.2f dB  max_err %.3e"
              % (c + 1, g, 20 * np.log10(abs(g)) if g else float("-inf"),
                 snr, float(np.max(np.abs(e)))))
    if len(gains) > 1:
        print("  L/R spread: %.3e" % (max(gains) - min(gains)))

    print()
    worst = min(r["snr"] for r in front)
    print("front pair: worst SNR %.2f dB, worst max_err %.4f LSB16"
          % (worst, max(r["peak_err"] for r in front) * 32768.0))
    if rest:
        print("ch3..ch%d  : worst residual %.3e"
              % (in_ch, max(r["rms_err"] for r in rest)))
    ok = worst >= 90.0
    print("\n%s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
