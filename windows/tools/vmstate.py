"""vmstate.py - dump the live VoiceMeeter routing via its Remote API.

VoiceMeeter exposes a flat, name-addressed parameter space over
VoicemeeterRemote64.dll. Reading it is the only reliable way to know what the
running mixer is actually doing (strip labels, bus devices, patch insert and
patch composite matrices, limiter, per-bus modes).

  python vmstate.py            # summary
  python vmstate.py --raw      # every parameter that resolves
"""
import argparse
import ctypes
import sys

DLL = r"C:\Program Files (x86)\VB\Voicemeeter\VoicemeeterRemote64.dll"

TYPES = {1: "Voicemeeter (standard)", 2: "Voicemeeter Banana", 3: "Voicemeeter Potato"}

# Strip / bus mode flags that change the channel handling - exactly what decides
# whether an 8-channel strip survives to a 2-channel bus.
STRIP_MODES = ("normal", "Amix", "Bmix", "Repeat", "Composite", "TVMix",
               "UpMix21", "UpMix41", "UpMix61", "CenterOnly", "LFEOnly", "RearOnly")
BUS_MODES = STRIP_MODES


def load():
    vm = ctypes.WinDLL(DLL)
    vm.VBVMR_Login.restype = ctypes.c_long
    vm.VBVMR_Logout.restype = ctypes.c_long
    vm.VBVMR_GetVoicemeeterType.argtypes = [ctypes.POINTER(ctypes.c_long)]
    vm.VBVMR_GetVoicemeeterType.restype = ctypes.c_long
    vm.VBVMR_GetVoicemeeterVersion.argtypes = [ctypes.POINTER(ctypes.c_long)]
    vm.VBVMR_GetVoicemeeterVersion.restype = ctypes.c_long
    vm.VBVMR_GetParameterFloat.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_float)]
    vm.VBVMR_GetParameterFloat.restype = ctypes.c_long
    vm.VBVMR_GetParameterStringA.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_long]
    vm.VBVMR_GetParameterStringA.restype = ctypes.c_long
    return vm


def f(vm, name):
    v = ctypes.c_float()
    rc = vm.VBVMR_GetParameterFloat(name.encode(), ctypes.byref(v))
    return (float(v.value), rc)


def s(vm, name, size=512):
    buf = ctypes.create_string_buffer(size)
    rc = vm.VBVMR_GetParameterStringA(name.encode(), buf, size)
    return (buf.value.decode("latin-1", "replace"), rc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", action="store_true")
    args = ap.parse_args()

    vm = load()
    rc = vm.VBVMR_Login()
    if rc not in (0, 1):
        print("VBVMR_Login failed: %d (is VoiceMeeter running?)" % rc)
        return 1

    try:
        t = ctypes.c_long()
        ver = ctypes.c_long()
        vm.VBVMR_GetVoicemeeterType(ctypes.byref(t))
        vm.VBVMR_GetVoicemeeterVersion(ctypes.byref(ver))
        print("type    : %s (%d)" % (TYPES.get(t.value, "?"), t.value))
        print("version : %d.%d.%d.%d"
              % ((ver.value >> 24) & 0xFF, (ver.value >> 16) & 0xFF,
                 (ver.value >> 8) & 0xFF, ver.value & 0xFF))
        print("login rc: %d" % rc)

        print("\n=== strips ===")
        for i in range(8):
            label, rl = s(vm, "Strip[%d].Label" % i)
            if rl != 0:
                continue
            gain, _ = f(vm, "Strip[%d].gain" % i)
            mute, _ = f(vm, "Strip[%d].mute" % i)
            flags = []
            for b in range(5):
                on, r = f(vm, "Strip[%d].A%d" % (i, b + 1))
                if r == 0 and on:
                    flags.append("A%d" % (b + 1))
            for b in range(3):
                on, r = f(vm, "Strip[%d].B%d" % (i, b + 1))
                if r == 0 and on:
                    flags.append("B%d" % (b + 1))
            modes = []
            for m in STRIP_MODES:
                on, r = f(vm, "Strip[%d].mode.%s" % (i, m))
                if r == 0 and on:
                    modes.append(m)
            print("  [%d] %-16r gain %6.1f dB mute %d  route %-10s modes %s"
                  % (i, label, gain, mute, ",".join(flags) or "-",
                     ",".join(modes) or "-"))

        print("\n=== buses ===")
        for i in range(8):
            name, rn = s(vm, "Bus[%d].device.name" % i)
            if rn != 0:
                continue
            on, _ = f(vm, "Bus[%d].on" % i)
            sr, _ = f(vm, "Bus[%d].sr" % i)
            modes = []
            for m in BUS_MODES:
                v, r = f(vm, "Bus[%d].mode.%s" % (i, m))
                if r == 0 and v:
                    modes.append(m)
            print("  [%d] on=%d  %6.0f Hz  %-55r modes %s"
                  % (i, on, sr, name, ",".join(modes) or "-"))

        print("\n=== patch insert (non-zero) ===")
        rows = []
        for i in range(0, 22 * 8):
            v, r = f(vm, "PatchInsert[%d]" % i)
            if r == 0 and v:
                rows.append(i)
        print("  active indices: %s" % (rows or "none"))
        if args.raw:
            for i in rows:
                print("     PatchInsert[%d] = 1" % i)

        print("\n=== patch composite (non-zero) ===")
        rows = []
        for i in range(0, 8 * 8):
            v, r = f(vm, "PatchComposite[%d]" % i)
            if r == 0 and v:
                rows.append(i)
        print("  active indices: %s" % (rows or "none"))

        print("\n=== option probes ===")
        for name in ("Option.limiter", "Option.sr", "Option.asio", "Option.buffer",
                     "Option.delay", "Option.mode"):
            v, r = f(vm, name)
            if r == 0:
                print("  %-18s = %g" % (name, v))
            else:
                print("  %-18s rc=%d" % (name, r))
    finally:
        vm.VBVMR_Logout()
    return 0


if __name__ == "__main__":
    sys.exit(main())
