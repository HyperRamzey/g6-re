"""vmlvl.py - map VoiceMeeter VAIO endpoints to mixer strips using level meters.

The G733 is held exclusively by VoiceMeeter, so loopback capture is not
available to check routing. VoiceMeeter's Remote API exposes per-channel level
meters instead: play a tone into one VAIO endpoint and see which strip and
which bus light up.

  python vmlvl.py --all                 # play into every VAIO endpoint in turn
  python vmlvl.py --src {guid} --name X # one endpoint

Strip channels are reported as strip*8+ch so a multi-channel strip is obvious.
"""
import argparse
import os
import subprocess
import sys
import time

import ctypes

from bridge_probe import VAIO, WORK, make_tone
from livecheck_mpv import MPV

DLL = r"C:\Program Files (x86)\VB\Voicemeeter\VoicemeeterRemote64.dll"


def load():
    vm = ctypes.WinDLL(DLL)
    vm.VBVMR_Login.restype = ctypes.c_long
    vm.VBVMR_Logout.restype = ctypes.c_long
    vm.VBVMR_GetLevel.argtypes = [ctypes.c_long, ctypes.c_long, ctypes.POINTER(ctypes.c_float)]
    vm.VBVMR_GetLevel.restype = ctypes.c_long
    vm.VBVMR_GetParameterStringA.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_long]
    vm.VBVMR_GetParameterStringA.restype = ctypes.c_long
    return vm


def levels(vm, ntype, nch=64):
    out = []
    for c in range(nch):
        v = ctypes.c_float()
        rc = vm.VBVMR_GetLevel(ntype, c, ctypes.byref(v))
        out.append(float(v.value) if rc == 0 else None)
    return out


def snapshot(vm):
    inp = levels(vm, 0)
    out = levels(vm, 1)
    return inp, out


def play_measure(vm, guid, seconds=1.6, tone=None):
    """Play into `guid`, sample meters while it runs, return the peak per channel."""
    peak_in = [0.0] * 64
    peak_out = [0.0] * 64
    p = subprocess.Popen(
        [MPV, "--no-video", "--no-config", "--really-quiet",
         "--audio-channels=2", "--volume=100",
         "--audio-device=wasapi/%s" % guid, tone],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    t0 = time.time()
    try:
        while time.time() - t0 < seconds:
            a, b = snapshot(vm)
            for i, v in enumerate(a):
                if v is not None and v > peak_in[i]:
                    peak_in[i] = v
            for i, v in enumerate(b):
                if v is not None and v > peak_out[i]:
                    peak_out[i] = v
            time.sleep(0.05)
    finally:
        p.terminate()
        p.wait(timeout=10)
    return peak_in, peak_out


def fmt(peaks, threshold=2.0):
    return [(i, v) for i, v in enumerate(peaks) if v > threshold]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src")
    ap.add_argument("--name", default="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--seconds", type=float, default=1.6)
    args = ap.parse_args()

    tone = os.path.join(WORK, "tone440.wav")
    make_tone(tone, 2.5)

    vm = load()
    if vm.VBVMR_Login() not in (0, 1):
        print("login failed - is VoiceMeeter running?")
        return 1
    try:
        base_in, base_out = snapshot(vm)
        quiet = max([v for v in base_in + base_out if v is not None] or [0.0])
        print("idle meter max: %.1f" % quiet)

        targets = list(VAIO.items()) if args.all else [(args.name, args.src)]
        for name, guid in targets:
            pin, pout = play_measure(vm, guid, args.seconds, tone)
            hi = fmt(pin)
            ho = fmt(pout)
            strips = sorted({"%d" % (i // 8) for i, _ in hi})
            print("%-24s strip %-10s  in-peaks %-28s  bus-peaks %s"
                  % (name, ",".join(strips) or "-",
                     " ".join("%d:%.0f" % (i, v) for i, v in hi[:8]) or "-",
                     " ".join("%d:%.0f" % (i, v) for i, v in ho[:8]) or "-"))
    finally:
        vm.VBVMR_Logout()
    return 0


if __name__ == "__main__":
    sys.exit(main())
