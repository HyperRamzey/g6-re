"""bridge_probe.py - does audio played into this endpoint reach the G733?

The VoiceMeeter VAIO family exposes eight render endpoints, but only some of
them are consumed by the running mixer. Playing a known tone into a candidate
endpoint and capturing the G733 loopback answers it empirically:

  source reached A1  ->  tone appears in the loopback
  source is orphaned ->  loopback stays silent

  python bridge_probe.py --src {guid} --seconds 2
  python bridge_probe.py --all          # probe every VAIO endpoint
"""
import argparse
import os
import struct
import subprocess
import sys
import time
import wave

import numpy as np
import pyaudiowpatch as pa

import livecheck as lc
from livecheck_mpv import MPV, Recorder

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(os.path.dirname(HERE), "work")

VAIO = {
    "Voicemeeter Input":      "{e6d2cba7-c801-4b78-a409-5f557fe3f61d}",
    "Voicemeeter AUX Input":  "{f2c4317e-c10e-4cb8-890f-abe89863fad5}",
    "Voicemeeter VAIO3 Input": "{63fbb270-91ba-4afe-a7ac-3624ac2d78d9}",
    "Voicemeeter In 1":       "{14f6eeea-27c8-4bbb-b5dc-67ec00498a4c}",
    "Voicemeeter In 2":       "{f3bc9dd0-39ea-41b8-b2ce-eff0bca6b329}",
    "Voicemeeter In 3":       "{f84dc10a-344f-46a5-a0f4-7204d730bfa1}",
    "Voicemeeter In 4":       "{ed432e15-a3b4-42a1-a606-035c262a28cd}",
    "Voicemeeter In 5":       "{42d31dec-1485-49a9-a275-36c3232da7b4}",
}


def make_tone(path, seconds=2.0, rate=48000, freq=440.0, amp=0.25):
    """Stereo 16-bit tone. 440 Hz at 48 kHz is exact, so no beat artefacts."""
    n = int(seconds * rate)
    t = np.arange(n) / rate
    x = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    pcm = np.stack([x, x], axis=1)
    pcm16 = np.clip(pcm * 32767.0, -32768, 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm16.tobytes())


def probe(src_guid, name, tone, seconds, dev_name="Logitech G733"):
    p = pa.PyAudio()
    try:
        render_dev, loop_dev = lc.find_devices(p, dev_name)
    finally:
        p.terminate()
    rate = int(render_dev["defaultSampleRate"])
    in_ch = int(loop_dev["maxInputChannels"])

    rec = Recorder(loop_dev, in_ch, rate).start()
    time.sleep(0.30)
    cmd = [MPV, "--no-video", "--no-config", "--really-quiet",
           "--audio-channels=2", "--volume=100",
           "--audio-device=wasapi/%s" % src_guid, tone]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    cap = rec.stop()
    if r.returncode != 0:
        return None, "mpv rc=%d %s" % (r.returncode, r.stderr.strip()[-200:])

    if cap.size == 0:
        return None, "no capture"
    rms = float(np.sqrt(np.mean(cap.astype(np.float64) ** 2)))
    peak = float(np.max(np.abs(cap)))
    per = [float(np.max(np.abs(cap[:, c]))) for c in range(cap.shape[1])]
    return dict(rms=rms, peak=peak, per=per, frames=len(cap)), None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", help="endpoint GUID to play into")
    ap.add_argument("--name", help="label for --src")
    ap.add_argument("--all", action="store_true", help="probe every VAIO endpoint")
    ap.add_argument("--seconds", type=float, default=2.0)
    ap.add_argument("--tone", default=None)
    args = ap.parse_args()

    tone = args.tone or os.path.join(WORK, "tone440.wav")
    make_tone(tone, args.seconds)

    targets = []
    if args.all:
        targets = list(VAIO.items())
    elif args.src:
        targets = [(args.name or args.src, args.src)]
    else:
        print("give --src or --all")
        return 2

    print("%-24s %-38s %10s %10s  per-channel peak" % ("endpoint", "guid", "rms", "peak"))
    print("-" * 100)
    for name, guid in targets:
        try:
            res, err = probe(guid, name, tone, args.seconds)
        except Exception as e:  # noqa: BLE001 - report and continue
            res, err = None, str(e)
        if err:
            print("%-24s %-38s  ERROR %s" % (name, guid, err))
            continue
        print("%-24s %-38s %10.6f %10.6f  %s"
              % (name, guid, res["rms"], res["peak"],
                 " ".join("%.4f" % v for v in res["per"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
