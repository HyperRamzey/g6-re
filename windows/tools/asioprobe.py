"""asioprobe.py - ask an installed ASIO driver what it actually offers.

Reads the driver's CLSID from HKLM\\SOFTWARE\\ASIO, creates it in-process and
calls the ASIO entry points through its vtable. This answers the questions that
decide the insert architecture without any host UI: how many input and output
channels the driver exposes, their order and names, the buffer limits and the
current sample rate.

  python asioprobe.py
  python asioprobe.py --name "Voicemeeter Insert Virtual ASIO"
"""
import argparse
import ctypes
import sys
from ctypes import wintypes

ASIO_NAMES = [
    "Voicemeeter Insert Virtual ASIO",
    "Voicemeeter Potato Insert Virtual ASIO",
    "Voicemeeter Virtual ASIO",
    "Voicemeeter AUX Virtual ASIO",
    "Voicemeeter VAIO3 Virtual ASIO",
]

ASE_OK = 0
ASE_NotPresent = -1000

CLSCTX_INPROC_SERVER = 0x1


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32),
                ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16),
                ("Data4", ctypes.c_ubyte * 8)]


class ASIOChannelInfo(ctypes.Structure):
    _fields_ = [("channel", ctypes.c_long),
                ("isInput", ctypes.c_long),
                ("channelGroup", ctypes.c_long),
                ("isActive", ctypes.c_long),
                ("channelType", ctypes.c_long),
                ("name", ctypes.c_char * 32)]


def hidden_window():
    """A real HWND. ASIO drivers reject Init(NULL); hosts pass their main
    window handle, and VoiceMeeter's driver is no exception."""
    user32 = ctypes.WinDLL("user32")
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    hwnd = user32.CreateWindowExW(0, "STATIC", "asio probe", 0, 0, 0, 0, 0,
                                  None, None, None, None)
    return hwnd


def read_clsid(name):
    import winreg
    key = r"SOFTWARE\ASIO\%s" % name
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
        clsid, _ = winreg.QueryValueEx(k, "CLSID")
        desc, _ = winreg.QueryValueEx(k, "Description")
    return clsid, desc


def vtable_call(obj, index, restype, *argtypes):
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return proto(vtbl[index])


def probe(name):
    clsid_str, desc = read_clsid(name)
    print("== %s" % name)
    print("   description: %s" % desc)
    print("   clsid      : %s" % clsid_str)

    ole32 = ctypes.WinDLL("ole32")
    ole32.CoInitialize(None)

    guid = GUID()
    hr = ole32.CLSIDFromString(ctypes.c_wchar_p(clsid_str), ctypes.byref(guid))
    if hr < 0:
        print("   CLSIDFromString failed 0x%08X" % (hr & 0xFFFFFFFF))
        return None

    ptr = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(ctypes.byref(guid), None, CLSCTX_INPROC_SERVER,
                                ctypes.byref(guid), ctypes.byref(ptr))
    if hr < 0 or not ptr:
        print("   CoCreateInstance failed 0x%08X" % (hr & 0xFFFFFFFF))
        return None

    try:
        # init() returns ASIOBool (1 == ASIOTrue == success), not ASIOError.
        init = vtable_call(ptr, 3, ctypes.c_long, ctypes.c_void_p)
        hwnd = hidden_window()
        rc = init(ptr, ctypes.c_void_p(hwnd) if hwnd else None)
        if rc != 1:
            print("   Init(hwnd=0x%X) -> %d (not ASIOTrue)" % (hwnd or 0, rc))
            return None

        nm = ctypes.create_string_buffer(64)
        vtable_call(ptr, 4, None, ctypes.c_char_p)(ptr, nm)

        ver = vtable_call(ptr, 5, ctypes.c_long)(ptr)

        n_in = ctypes.c_long()
        n_out = ctypes.c_long()
        vtable_call(ptr, 9, ctypes.c_long,
                    ctypes.POINTER(ctypes.c_long),
                    ctypes.POINTER(ctypes.c_long))(ptr, ctypes.byref(n_in),
                                                   ctypes.byref(n_out))
        print("   driver     : %r  version %d" % (nm.value.decode("latin-1"), ver))
        print("   channels   : %d in / %d out" % (n_in.value, n_out.value))

        mn, mx, pref, gran = (ctypes.c_long() for _ in range(4))
        vtable_call(ptr, 11, ctypes.c_long,
                    *(ctypes.POINTER(ctypes.c_long),) * 4)(ptr, ctypes.byref(mn),
                                                          ctypes.byref(mx),
                                                          ctypes.byref(pref),
                                                          ctypes.byref(gran))
        print("   buffer     : min %d  max %d  preferred %d  granularity %d"
              % (mn.value, mx.value, pref.value, gran.value))

        sr = ctypes.c_double()
        vtable_call(ptr, 13, ctypes.c_long, ctypes.POINTER(ctypes.c_double))(
            ptr, ctypes.byref(sr))
        print("   sample rate: %.0f Hz" % sr.value)

        for is_input, count in ((1, n_in.value), (0, n_out.value)):
            if count <= 0:
                continue
            print("   %s channels:" % ("input" if is_input else "output"))
            for c in range(count):
                info = ASIOChannelInfo()
                info.channel = c
                info.isInput = is_input
                vtable_call(ptr, 18, ctypes.c_long,
                            ctypes.POINTER(ASIOChannelInfo))(ptr, ctypes.byref(info))
                print("     %2d  group %d  active %d  type %d  %r"
                      % (c, info.channelGroup, info.isActive, info.channelType,
                         info.name.decode("latin-1")))

        stop = vtable_call(ptr, 8, ctypes.c_long)
        stop(ptr)
        return (n_in.value, n_out.value)
    finally:
        release = vtable_call(ptr, 2, ctypes.c_ulong)
        release(ptr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    names = [args.name] if args.name else ASIO_NAMES
    results = {}
    for n in names:
        try:
            r = probe(n)
        except FileNotFoundError:
            print("== %s: not registered" % n)
            r = None
        except Exception as e:  # noqa: BLE001
            print("== %s: ERROR %s" % (n, e))
            r = None
        results[n] = r
        print()

    print("summary")
    for n, r in results.items():
        print("  %-42s %s" % (n, "not available" if r is None else "%d in / %d out" % r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
