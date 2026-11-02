"""scan_endpoints.py - list every render endpoint with its speaker config, device
format, and the APO values that decide whether EqualizerAPO runs on it.

The modded INF re-enumerates the G733 as a plain 2.0 USB audio device, which
changes the endpoint GUID and resets FxProperties. This prints what is there now
so the APO attachment can be re-applied to the right key.

  python scan_endpoints.py [--name G733]
"""
import argparse
import struct
import sys

import winreg

RENDER = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render"
MASK = {0x1: "FL", 0x2: "FR", 0x4: "FC", 0x8: "LFE", 0x10: "BL", 0x20: "BR",
        0x40: "FLC", 0x80: "FRC", 0x100: "BC", 0x200: "SL", 0x400: "SR"}

KEYS = {
    "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},0": "FX Association",
    "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},1": "FX PreMix",
    "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},2": "FX UserMode/GFX",
    "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},5": "FX Stream/SFX",
    "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},6": "FX Mode/MFX",
    "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},7": "FX Endpoint/EFX",
    "{d3993a3f-99c2-4402-b5ec-a92a0367664b},1": "modes LFX",
    "{d3993a3f-99c2-4402-b5ec-a92a0367664b},5": "modes SFX",
    "{d3993a3f-99c2-4402-b5ec-a92a0367664b},6": "modes MFX",
    "{d3993a3f-99c2-4402-b5ec-a92a0367664b},7": "modes EFX",
    "{1da5d803-d492-4edd-8c23-e0c0ffee7f0e},3": "PhysicalSpeakers",
    "{f19f064d-082c-4e27-bc73-6882a1bb8e4c},0": "DeviceFormat",
    "{e4870e26-3cc5-4cd2-ba46-ca0a9a70ed04},3": "OEMFormat",
}


def mask_str(m):
    return ("|".join(n for b, n in MASK.items() if m & b) or "-") + " (0x%X)" % m


def fmt(v):
    """Decode a stored 48-byte KSDATAFORMAT_WAVEFORMATEXTENSIBLE blob."""
    if not isinstance(v, bytes) or len(v) < 48:
        return None
    tag, ch, rate, _, _, bits = struct.unpack_from("<HHIIHH", v, 8)
    mask = struct.unpack_from("<I", v, 28)[0]
    return "tag=0x%X ch=%d %dHz %dbit mask=%s" % (tag, ch, rate, bits, mask_str(mask))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default=None)
    args = ap.parse_args()

    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, RENDER) as root:
        n = winreg.QueryInfoKey(root)[0]
        guids = [winreg.EnumKey(root, i) for i in range(n)]

    for guid in guids:
        base = RENDER + "\\" + guid
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                base + r"\Properties") as p:
                def get(name):
                    try:
                        return winreg.QueryValueEx(p, name)[0]
                    except OSError:
                        return None

                # "Динамики"/"Speakers" is the connector name; the model name
                # lives in DEVPKEY_Device_DeviceDesc. Both are worth printing,
                # and the devnode name is the one to filter on.
                desc = get("{a45c254e-df1c-4efd-8020-67d146a850e0},2")  # FriendlyName
                dev = get("{b3f8fa53-0004-438e-9003-51a46e139bfc},6")   # DeviceDesc
                if desc is None and dev is None:
                    continue
                desc = "" if desc is None else str(desc)
                dev = "" if dev is None else str(dev)
                if args.name and args.name.lower() not in (desc + " " + dev).lower():
                    continue
                print("=" * 78)
                print("%s   %s / %s" % (guid, dev or "?", desc or "?"))
                ps = get("{1da5d803-d492-4edd-8c23-e0c0ffee7f0e},3")
                if isinstance(ps, int):
                    print("   speakers : %s" % mask_str(ps))
                for k, label in (("{f19f064d-082c-4e27-bc73-6882a1bb8e4c},0", "device  "),
                                 ("{e4870e26-3cc5-4cd2-ba46-ca0a9a70ed04},3", "oem     ")):
                    d = fmt(get(k))
                    if d:
                        print("   %s : %s" % (label, d))
        except OSError:
            continue

        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                base + r"\FxProperties") as f:
                names = [winreg.EnumValue(f, i) for i in range(winreg.QueryInfoKey(f)[1])]
        except OSError:
            print("   FxProperties: (absent)")
            continue
        interesting = [(n, v) for n, v, _ in names if n in KEYS]
        if not interesting:
            print("   FxProperties: %d values, none of the APO slots" % len(names))
        for n, v in interesting:
            print("   %-16s %s = %s" % (KEYS[n], n.split(",")[-1], v))


if __name__ == "__main__":
    sys.exit(main())
