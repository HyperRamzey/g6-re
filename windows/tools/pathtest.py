"""pathtest.py - which VAIO endpoint actually reaches a VoiceMeeter bus?

Plays a tone into a candidate render endpoint and records a VoiceMeeter bus
tap ("Voicemeeter Out A1", "Out B1", ...). Because VoiceMeeter mirrors every
bus as a recording device, this works even when the physical device is held
exclusively by VoiceMeeter - unlike loopback capture.

  python pathtest.py --all
  python pathtest.py --src {guid} --name X --tap "Voicemeeter Out A1"
"""
import argparse
import os
import subprocess
import sys
import time

import numpy as np
import pyaudiowpatch as pa

from bridge_probe import VAIO, WORK, make_tone
from livecheck_mpv import MPV


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


def play_capture(src_guid, tap_name, tone, seconds=2.0):
    dev = find_capture(tap_name)
    if dev is None:
        raise SystemExit("no capture device matching %r" % tap_name)
    rate = int(dev["defaultSampleRate"])
    ch = int(dev["maxInputChannels"])

    p = pa.PyAudio()
    try:
        rec = p.open(format=pa.paFloat32, channels=ch, rate=rate, input=True,
                     input_device_index=dev["index"], frames_per_buffer=480)
    except Exception:
        p.terminate()
        raise
    blocks = []
    rec.start_stream()
    time.sleep(0.35)
    proc = subprocess.Popen(
        [MPV, "--no-video", "--no-config", "--really-quiet",
         "--audio-channels=2", "--volume=100",
         "--audio-device=wasapi/%s" % src_guid, tone],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    t0 = time.time()
    try:
        while proc.poll() is None and time.time() - t0 < seconds + 8:
            blocks.append(rec.read(480, exception_on_overflow=False))
        time.sleep(0.25)
        while True:
            blocks.append(rec.read(480, exception_on_overflow=False))
            if sum(len(b) for b in blocks) > (seconds + 2.0) * rate * ch * 4:
                break
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        rec.stop_stream()
        rec.close()
        p.terminate()

    raw = b"".join(blocks)
    x = np.frombuffer(raw, dtype=np.float32).reshape(-1, ch).astype(np.float64)
    rms = float(np.sqrt(np.mean(x ** 2))) if x.size else 0.0
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    return rms, peak, x.shape[0], ch


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src")
    ap.add_argument("--name", default="?")
    ap.add_argument("--tap", default="Voicemeeter Out A1")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--seconds", type=float, default=1.8)
    args = ap.parse_args()

    tone = os.path.join(WORK, "tone440.wav")
    make_tone(tone, 2.5)

    targets = list(VAIO.items()) if args.all else [(args.name, args.src)]
    print("tap: %r" % args.tap)
    print("%-24s %-38s %10s %10s %s" % ("endpoint", "guid", "rms", "peak", "frames"))
    print("-" * 96)
    for name, guid in targets:
        try:
            rms, peak, n, ch = play_capture(guid, args.tap, tone, args.seconds)
        except Exception as e:  # noqa: BLE001
            print("%-24s %-38s  ERROR %s" % (name, guid, e))
            continue
        verdict = "REACHES" if peak > 0.005 else "silent"
        print("%-24s %-38s %10.6f %10.6f %8d  %s"
              % (name, guid, rms, peak, n, verdict))
    return 0


if __name__ == "__main__":
    sys.exit(main())
