"""chmap.py - which insert channel does a given Windows 7.1 channel land on?

VoiceMeeter names its insert channels `IN#5 Left Right Center LFE SL SR BL BR`,
which is *not* the WAVEFORMATEXTENSIBLE 7.1 order (`FL FR FC LFE BL BR SL SR`).
If VM reorders, the matrix would feed the side coefficients into the back
channels and vice versa - a wrong binaural image that no amount of DSP
correctness can fix.

So: play a tone on exactly one Windows channel, capture the insert buffers with
asiocapture, and see which insert channel carries it.

    python chmap.py                 # all eight channels
    python chmap.py --only 5        # just BL
"""
import argparse
import os
import subprocess
import sys
import time

import numpy as np

import asiocapture
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORK = os.path.join(ROOT, "work")
MPV = os.path.join(os.path.dirname(ROOT), "mpv.exe")
VM_INPUT = "{e6d2cba7-c801-4b78-a409-5f557fe3f61d}"

NAMES = ["FL", "FR", "FC", "LFE", "BL", "BR", "SL", "SR"]


def make_wav(path, ch, seconds=3.0, rate=48000, freq=440.0, amp=0.3):
    n = int(seconds * rate)
    t = np.arange(n) / rate
    x = np.zeros((n, 8), dtype=np.float32)
    x[:, ch - 1] = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    pcm = np.clip(x * 32767.0, -32768, 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(8)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def one(ch, seconds, driver):
    wav = os.path.join(WORK, "chonly_%d.wav" % ch)
    make_wav(wav, ch)
    proc = subprocess.Popen(
        [MPV, "--no-video", "--no-config", "--really-quiet",
         "--audio-channels=8", "--volume=100",
         "--audio-device=wasapi/%s" % VM_INPUT, wav],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)
    try:
        result = asiocapture.capture(driver, seconds, False, None)
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    if not result:
        return None
    data, names = result
    peaks = np.max(np.abs(data), axis=1)
    loud = [(c, names[c], float(peaks[c])) for c in range(len(names))
            if peaks[c] > 0.01]
    return loud


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=int)
    ap.add_argument("--seconds", type=float, default=1.0)
    ap.add_argument("--driver", default="Voicemeeter Insert Virtual ASIO")
    args = ap.parse_args()

    chans = [args.only] if args.only else list(range(1, 9))
    print("%-4s %-6s  -> insert channels carrying the tone" % ("win", "name"))
    print("-" * 78)
    for ch in chans:
        loud = one(ch, args.seconds, args.driver)
        if loud is None:
            print("%-4d %-6s  capture failed" % (ch, NAMES[ch - 1]))
            continue
        if not loud:
            print("%-4d %-6s  (nothing - insert carries no signal)" % (ch, NAMES[ch - 1]))
            continue
        txt = ", ".join("%d %s (%.3f)" % (c, n, p) for c, n, p in loud)
        print("%-4d %-6s  %s" % (ch, NAMES[ch - 1], txt))
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
