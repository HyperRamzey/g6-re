"""vst_nulltest.py - offline host for g6ct.dll, null-tested against the oracle.

Drives the VST2 plugin exactly the way a host does (VSTPluginMain with a stub
audioMaster, effSetSampleRate / effSetBlockSize / effMainsChanged, then
processReplacing over blocks) and compares the output with work/ref_check.raw,
the g6ct_cli_f64 render that is the authoritative reference.

The plugin is 8 in / 2 out.  It also exposes its meter levels as VST
parameters and owns an editor, both of which are checked here.

  python vst_nulltest.py
  python vst_nulltest.py --block 128 --double
"""
import argparse
import ctypes
import hashlib
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DLL = os.path.join(ROOT, "plugin", "g6ct.dll")
STIM = os.path.join(ROOT, "work", "stim8.f32")
REF = os.path.join(ROOT, "work", "ref_check.raw")

CH = 8       # plugin inputs
OUT = 2      # plugin outputs
RATE = 48000
NPARAMS = CH + OUT

# --- VST2 ABI -------------------------------------------------------------

DISP = ctypes.CFUNCTYPE(ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_int32,
                        ctypes.c_int32, ctypes.c_ssize_t, ctypes.c_void_p,
                        ctypes.c_float)
FLOATPROC = ctypes.CFUNCTYPE(None, ctypes.c_void_p,
                             ctypes.POINTER(ctypes.POINTER(ctypes.c_float)),
                             ctypes.POINTER(ctypes.POINTER(ctypes.c_float)),
                             ctypes.c_int32)
DOUBLEPROC = ctypes.CFUNCTYPE(None, ctypes.c_void_p,
                              ctypes.POINTER(ctypes.POINTER(ctypes.c_double)),
                              ctypes.POINTER(ctypes.POINTER(ctypes.c_double)),
                              ctypes.c_int32)
GETPARAM = ctypes.CFUNCTYPE(ctypes.c_float, ctypes.c_void_p, ctypes.c_int32)


class ERect(ctypes.Structure):
    _fields_ = [("top", ctypes.c_short), ("left", ctypes.c_short),
                ("bottom", ctypes.c_short), ("right", ctypes.c_short)]


class AEffect(ctypes.Structure):
    _fields_ = [
        ("magic", ctypes.c_int32),
        ("dispatcher", ctypes.c_void_p),
        ("process", ctypes.c_void_p),
        ("setParameter", ctypes.c_void_p),
        ("getParameter", ctypes.c_void_p),
        ("numPrograms", ctypes.c_int32),
        ("numParams", ctypes.c_int32),
        ("numInputs", ctypes.c_int32),
        ("numOutputs", ctypes.c_int32),
        ("flags", ctypes.c_int32),
        ("ptr1", ctypes.c_void_p),
        ("ptr2", ctypes.c_void_p),
        ("initialDelay", ctypes.c_int32),
        ("realQualities", ctypes.c_int32),
        ("offQualities", ctypes.c_int32),
        ("ioRatio", ctypes.c_float),
        ("object", ctypes.c_void_p),
        ("user", ctypes.c_void_p),
        ("uniqueID", ctypes.c_int32),
        ("version", ctypes.c_int32),
        ("processReplacing", ctypes.c_void_p),
        ("processDoubleReplacing", ctypes.c_void_p),
        ("future", ctypes.c_char * 56),
    ]


effClose = 1
effEditOpen = 14
effEditClose = 15
effGetParamName = 8
effSetSampleRate = 10
effSetBlockSize = 11
effMainsChanged = 12
effEditGetRect = 13
effGetParamDisplay = 7
effGetEffectName = 45
effGetVstVersion = 58
effFlagsHasEditor = 1 << 0
effFlagsCanReplacing = 1 << 4
effFlagsCanDoubleReplacing = 1 << 12
kEffectMagic = 0x56737450


def load_effect():
    lib = ctypes.WinDLL(DLL)
    lib.VSTPluginMain.restype = ctypes.POINTER(AEffect)
    lib.VSTPluginMain.argtypes = [ctypes.c_void_p]

    def audio_master(effect, opcode, index, value, ptr, opt):
        return 0

    cb = DISP(audio_master)          # keep alive for the plugin's lifetime
    eff = lib.VSTPluginMain(ctypes.cast(cb, ctypes.c_void_p))
    if not eff:
        raise SystemExit("VSTPluginMain returned NULL")
    return lib, eff, cb


def text_of(disp, eff, op, index=0, size=64):
    buf = ctypes.create_string_buffer(size)
    disp(eff, op, index, 0, ctypes.cast(buf, ctypes.c_void_p), 0.0)
    return buf.value.decode("latin-1")


def describe(eff, disp):
    e = eff.contents
    rect = ctypes.POINTER(ERect)()
    has_rect = disp(eff, effEditGetRect, 0, 0,
                    ctypes.cast(ctypes.byref(rect), ctypes.c_void_p), 0.0)

    names = [text_of(disp, eff, effGetParamName, i, 8) for i in range(e.numParams)]

    return {
        "magic_ok": e.magic == kEffectMagic,
        "name": text_of(disp, eff, effGetEffectName, 0, 32),
        "in": e.numInputs,
        "out": e.numOutputs,
        "params": e.numParams,
        "param_names": names,
        "flags": e.flags,
        "has_editor": bool(e.flags & effFlagsHasEditor),
        "can_replace": bool(e.flags & effFlagsCanReplacing),
        "can_double": bool(e.flags & effFlagsCanDoubleReplacing),
        "editor_rect": (rect.contents.right, rect.contents.bottom) if has_rect and rect else None,
        "vst_version": disp(eff, effGetVstVersion, 0, 0, None, 0.0),
        "uniqueID": hex(e.uniqueID & 0xFFFFFFFF),
    }


def run(eff, disp, proc_kind, stim, block):
    """Feed `stim` (frames, 8) through the plugin in `block` chunks."""
    n = stim.shape[0]
    is_float = proc_kind == "float"
    dtype = np.float32 if is_float else np.float64
    ptype = ctypes.POINTER(ctypes.c_float if is_float else ctypes.c_double)
    itemsize = np.dtype(dtype).itemsize
    fn_t = FLOATPROC if is_float else DOUBLEPROC

    if is_float:
        fn = fn_t(ctypes.cast(eff.contents.processReplacing,
                              ctypes.c_void_p).value)
    else:
        fn = fn_t(ctypes.cast(eff.contents.processDoubleReplacing,
                              ctypes.c_void_p).value)

    src = np.ascontiguousarray(stim, dtype=dtype)
    outs = [np.zeros(n, dtype=dtype) for _ in range(OUT)]

    # One contiguous buffer per channel: a column of an interleaved (n, 8)
    # array is strided, and the plugin walks each channel linearly.
    chans = [np.ascontiguousarray(src[:, c]) for c in range(CH)]
    ibase = [chans[c].ctypes.data for c in range(CH)]
    obase = [outs[c].ctypes.data for c in range(OUT)]

    in_ptrs = (ptype * CH)()
    out_ptrs = (ptype * OUT)()

    for off in range(0, n, block):
        k = min(block, n - off)
        for c in range(CH):
            in_ptrs[c] = ctypes.cast(ibase[c] + itemsize * off, ptype)
        for c in range(OUT):
            out_ptrs[c] = ctypes.cast(obase[c] + itemsize * off, ptype)
        fn(eff, in_ptrs, out_ptrs, k)

    return outs


def report(label, got, ref):
    d = got.astype(np.float64) - ref.astype(np.float64)
    peak = float(np.max(np.abs(d))) if d.size else 0.0
    rms = float(np.sqrt(np.mean(d ** 2))) if d.size else 0.0
    rref = float(np.sqrt(np.mean(ref.astype(np.float64) ** 2))) if d.size else 0.0
    null_db = 20 * np.log10(rms / rref) if rms > 0 and rref > 0 else float("-inf")
    h = hashlib.sha256(got.tobytes()).hexdigest()[:16]
    hr = hashlib.sha256(ref.astype(got.dtype).tobytes()).hexdigest()[:16]
    print("  %-7s peak %.3e  rms %.3e  null %8.2f dB  sha %s %s"
          % (label, peak, rms, null_db, h, "== ref" if h == hr else "!= ref"))
    return peak, null_db


def param_db(v):
    """Parameters are a normalised dB scale: 0 = -60 dB, 1 = 0 dB."""
    return v * 60.0 - 60.0


def show_meters(eff):
    getp = GETPARAM(ctypes.cast(eff.contents.getParameter, ctypes.c_void_p).value)
    disp = DISP(eff.contents.dispatcher)
    vals = [getp(eff, i) for i in range(NPARAMS)]
    names = [text_of(disp, eff, effGetParamName, i, 8) for i in range(NPARAMS)]

    print("  " + "  ".join("%s %6.1f dB" % (names[i], param_db(vals[i]))
                           for i in range(CH)))
    print("  " + "  ".join("%s %6.1f dB" % (names[CH + i],
                                           param_db(vals[CH + i]))
                           for i in range(OUT)))
    disp_txt = [text_of(disp, eff, effGetParamDisplay, i, 24)
                for i in range(NPARAMS)]
    print("  display strings: " + " ".join(disp_txt))
    for i in range(NPARAMS):
        if abs(float(disp_txt[i]) - param_db(vals[i])) > 0.15:
            print("  INCONSISTENT: %s param says %.1f dB, display says %s"
                  % (names[i], param_db(vals[i]), disp_txt[i]))
            return None
    print("  parameter values agree with the display strings")
    return vals


def test_editor(eff, disp):
    """Open the plugin's editor on a real parent HWND, like a host does."""
    user32 = ctypes.WinDLL("user32")
    user32.CreateWindowExW.restype = ctypes.c_void_p
    user32.CreateWindowExW.argtypes = [
        ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    user32.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    user32.GetWindow.restype = ctypes.c_void_p

    parent = user32.CreateWindowExW(0, "STATIC", "host", 0,
                                    0, 0, 800, 600, None, None, None, None)
    if not parent:
        print("editor  : could not create a host window")
        return False

    rc = disp(eff, effEditOpen, 0, 0, ctypes.c_void_p(parent), 0.0)
    child = user32.GetWindow(ctypes.c_void_p(parent), 5)  # GW_CHILD
    ok = rc == 1 and bool(child)

    rc2 = disp(eff, effEditClose, 0, 0, None, 0.0)
    child_after = user32.GetWindow(ctypes.c_void_p(parent), 5)
    user32.DestroyWindow(ctypes.c_void_p(parent))

    print("editor  : effEditOpen -> %d, child hwnd %s, effEditClose -> %s, "
          "child after close %s"
          % (rc, "0x%X" % child if child else "none", rc2,
             "0x%X" % child_after if child_after else "none"))
    return ok and not child_after


def test_degraded(eff):
    """Paths a host can hit that are not the happy one: fewer ports than the
    plugin declares, an empty block, a null AEffect.  None of them may read or
    write outside the buffers."""
    fn = FLOATPROC(ctypes.cast(eff.contents.processReplacing,
                               ctypes.c_void_p).value)
    n = 8
    src = np.zeros(CH * n, dtype=np.float32)
    dst = np.zeros(OUT * n, dtype=np.float32)
    ptr_t = ctypes.POINTER(ctypes.c_float)

    in_ptrs = (ptr_t * CH)(*[ctypes.cast(src.ctypes.data + 4 * i * n, ptr_t)
                             for i in range(CH)])
    out_ptrs = (ptr_t * OUT)(*[ctypes.cast(dst.ctypes.data + 4 * i * n, ptr_t)
                               for i in range(OUT)])

    saved_in = eff.contents.numInputs
    saved_out = eff.contents.numOutputs
    cases = []
    try:
        eff.contents.numInputs = 2
        fn(eff, in_ptrs, out_ptrs, n)
        cases.append("2 in / 2 out")

        eff.contents.numInputs = saved_in
        eff.contents.numOutputs = 1
        fn(eff, in_ptrs, out_ptrs, n)
        cases.append("8 in / 1 out")

        eff.contents.numOutputs = 0
        fn(eff, in_ptrs, out_ptrs, n)
        cases.append("8 in / 0 out")

        eff.contents.numOutputs = saved_out
        fn(eff, in_ptrs, out_ptrs, 0)
        cases.append("n = 0")

        fn(None, in_ptrs, out_ptrs, n)
        cases.append("NULL AEffect")
    finally:
        eff.contents.numInputs = saved_in
        eff.contents.numOutputs = saved_out

    finite = bool(np.all(np.isfinite(dst)))
    print("degraded: %s -> no crash, output buffers finite: %s"
          % (", ".join(cases), finite))
    return finite


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--block", type=int, default=512)
    ap.add_argument("--double", action="store_true", help="also test f64 path")
    args = ap.parse_args()

    stim = np.fromfile(STIM, dtype=np.float32).reshape(-1, CH)
    ref = np.fromfile(REF, dtype=np.float32).reshape(-1, OUT)
    if stim.shape[0] != ref.shape[0]:
        raise SystemExit("frame mismatch: stim %d vs ref %d"
                         % (stim.shape[0], ref.shape[0]))

    lib, eff, cb = load_effect()
    disp = DISP(eff.contents.dispatcher)
    info = describe(eff, disp)
    print("plugin  : %s" % DLL)
    for k in ("magic_ok", "name", "in", "out", "params", "param_names",
              "has_editor", "editor_rect", "can_replace", "can_double",
              "vst_version", "uniqueID"):
        print("  %-12s %s" % (k, info[k]))

    if not info["magic_ok"]:
        raise SystemExit("bad AEffect magic")
    if info["in"] != CH or info["out"] != OUT:
        raise SystemExit("expected %d in / %d out, got %d/%d"
                         % (CH, OUT, info["in"], info["out"]))
    if info["params"] != NPARAMS:
        raise SystemExit("expected %d params, got %d" % (NPARAMS, info["params"]))

    disp(eff, effSetSampleRate, 0, 0, None, float(RATE))
    disp(eff, effSetBlockSize, 0, args.block, None, 0.0)
    disp(eff, effMainsChanged, 0, 1, None, 0.0)

    print("stim    : %d frames, block %d" % (stim.shape[0], args.block))
    print("ref     : %s" % REF)

    ok = True
    outs = run(eff, disp, "float", stim, args.block)
    print("processReplacing (float32 I/O, f64 internal):")
    p1, d1 = report("float", np.stack(outs, axis=1).reshape(-1),
                    ref.reshape(-1))
    ok = ok and p1 < 1e-7
    print("meters after playback:")
    ok = (show_meters(eff) is not None) and ok
    ok = test_editor(eff, disp) and ok
    ok = test_degraded(eff) and ok

    if args.double:
        disp(eff, effMainsChanged, 0, 1, None, 0.0)
        outs = run(eff, disp, "double", stim, args.block)
        print("processDoubleReplacing (f64 end to end):")
        p2, d2 = report("double", np.stack(outs, axis=1).reshape(-1),
                        ref.astype(np.float64).reshape(-1))
        ok = ok and p2 < 1e-7

    disp(eff, effClose, 0, 0, None, 0.0)
    print("\n%s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
