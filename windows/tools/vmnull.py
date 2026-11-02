"""vmnull.py - does VoiceMeeter hand the insert the 7.1 stream untouched?

Captures the insert send for `Voicemeeter Input` (IN#4, ASIO channels 6..13)
while a known 8-channel stimulus plays into that endpoint, then runs the port
over the captured audio and null-tests it against the reference render. If the
residual is at the float32 floor, VoiceMeeter is a transparent carrier and the
only remaining hop is the 2-channel bus to the G733.

    python vmnull.py                       # stim8.f32 vs work/ref_check.raw
    python vmnull.py --stim work/noise8.f32 --ref work/noise8.ref.raw
"""
import argparse
import os
import subprocess
import sys
import threading
import time

import numpy as np

import asiocapture

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORK = os.path.join(ROOT, "work")
MPV = os.path.join(os.path.dirname(ROOT), "mpv.exe")
CLI = os.path.join(ROOT, "build", "g6ct_cli_f64.exe")

VM_INPUT = "{e6d2cba7-c801-4b78-a409-5f557fe3f61d}"
INSERT_GROUP_OFFSET = 6     # IN#4 Left .. IN#4 BR
CH = 8


def capture_during_playback(driver, wav, seconds):
    result = {}

    def run():
        result["r"] = asiocapture.capture(driver, seconds, False, None)

    t = threading.Thread(target=run)
    t.start()
    time.sleep(0.5)
    proc = subprocess.Popen(
        [MPV, "--no-video", "--no-config", "--really-quiet",
         "--audio-channels=8", "--volume=100",
         "--audio-device=wasapi/%s" % VM_INPUT, wav],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    t.join()
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except Exception:
        pass
    return result.get("r")


def best_offset(cap, ref, max_lag=200000):
    """Sample offset that best aligns `cap` (1 ch) onto `ref` (1 ch)."""
    a = cap.astype(np.float64)
    b = ref.astype(np.float64)
    n = 1 << int(np.ceil(np.log2(len(a) + len(b))))
    corr = np.fft.irfft(np.fft.rfft(a, n) * np.conj(np.fft.rfft(b, n)), n)
    lag = int(np.argmax(corr[:max_lag]))
    return lag


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stim", default=os.path.join(WORK, "stim8.f32"))
    ap.add_argument("--ref", default=os.path.join(WORK, "ref_check.raw"))
    ap.add_argument("--wav", default=os.path.join(WORK, "stim8.wav"))
    ap.add_argument("--driver", default="Voicemeeter Insert Virtual ASIO")
    ap.add_argument("--seconds", type=float, default=4.0)
    args = ap.parse_args()

    stim = np.fromfile(args.stim, dtype=np.float32).reshape(-1, CH)
    ref = np.fromfile(args.ref, dtype=np.float32).reshape(-1, 2)
    want = stim.shape[0]
    print("stimulus: %d frames (%.2f s), ref %d frames"
          % (want, want / 48000.0, ref.shape[0]))

    res = capture_during_playback(args.driver, args.wav, args.seconds)
    if not res:
        print("capture failed")
        return 1
    data, names = res
    print("captured: %d frames on %d insert channels" % (data.shape[1], data.shape[0]))

    grp = data[INSERT_GROUP_OFFSET:INSERT_GROUP_OFFSET + CH, :]
    print("group   : %s" % " ".join(names[c] for c in
                                    range(INSERT_GROUP_OFFSET, INSERT_GROUP_OFFSET + CH)))

    lag = best_offset(grp[0], stim[:, 0])
    print("align   : capture leads stimulus by %d frames (%.1f ms)"
          % (lag, lag / 48.0))
    if lag < 0 or lag + want > grp.shape[1]:
        print("capture too short after alignment (%d + %d > %d)"
              % (lag, want, grp.shape[1]))
        return 1

    seg = np.ascontiguousarray(grp[:, lag:lag + want].T)   # (frames, 8)
    seg.tofile(os.path.join(WORK, "vm_insert.raw"))

    # Is the capture the stimulus itself (before any VoiceMeeter processing)?
    d = seg.astype(np.float64) - stim.astype(np.float64)
    print("\ncapture vs stimulus   : peak %.3e  rms %.3e"
          % (np.max(np.abs(d)), np.sqrt(np.mean(d ** 2))))

    out_raw = os.path.join(WORK, "vm_insert_dsp.raw")
    r = subprocess.run([CLI, os.path.join(WORK, "vm_insert.raw"), out_raw,
                        "0x63F", "8"], capture_output=True, text=True)
    if r.returncode != 0:
        print("g6ct_cli failed: %s" % r.stderr.strip())
        return 1

    got = np.fromfile(out_raw, dtype=np.float32)
    ref_flat = ref.reshape(-1)[:got.size]
    got = got[:ref_flat.size]
    err = got.astype(np.float64) - ref_flat.astype(np.float64)
    sig = float(np.sqrt(np.mean(ref_flat.astype(np.float64) ** 2)))
    rms = float(np.sqrt(np.mean(err ** 2)))
    null = 20 * np.log10(rms / sig) if rms > 0 else float("-inf")
    print("port on captured audio vs ref_check:")
    print("  max_err %.3e  rms %.3e  null %.2f dB  %s"
          % (np.max(np.abs(err)), rms, null,
             "TRANSPARENT" if null < -120 else "NOT transparent"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
