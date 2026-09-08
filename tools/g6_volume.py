"""G6-specific endpoint volume control (find the Sound BlasterX G6 render endpoint, not default).

Usage:
  python g6_volume.py            -> list all render endpoints w/ volume
  python g6_volume.py get       -> G6 Speakers endpoint volume %
  python g6_volume.py set 100   -> set G6 endpoint volume to 100%
"""

import sys

from pycaw.pycaw import AudioUtilities


def find_g6_endpoints():
    """Return list of (name, device) for all render endpoints."""
    out = []
    for dev in AudioUtilities.GetAllDevices():
        try:
            vol = dev.EndpointVolume
            name = dev.FriendlyName
        except Exception as exc:  # endpoint without volume iface / access denied
            print(f"skip endpoint: {exc}", file=sys.stderr)
            continue
        if "G6" in name and vol is not None:
            out.append((name, vol))
    return out


def main() -> int:
    args = sys.argv[1:]

    g6s = find_g6_endpoints()
    if not g6s:
        print("error: no G6 render endpoint with volume control found", file=sys.stderr)
        return 1

    if not args or args[0] == "list":
        for name, vol in g6s:
            try:
                scalar = vol.GetMasterVolumeLevelScalar()
            except Exception as exc:
                print(f"{name}: query failed {exc}")
                continue
            print(f"{name}: {scalar * 100.0:.1f}%")
        return 0

    # use the first G6 endpoint (Speakers)
    name, vol = g6s[0]

    if args[0] == "get":
        try:
            scalar = vol.GetMasterVolumeLevelScalar()
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"{name}: {scalar * 100.0:.1f}%")
        return 0

    if args[0] == "set" and len(args) >= 2:
        try:
            pct = float(args[1])
            if not 0.0 <= pct <= 100.0:
                raise ValueError("out of range")
        except (ValueError, TypeError) as exc:
            print(f"error: set expects 0..100 ({exc})", file=sys.stderr)
            return 1
        try:
            vol.SetMasterVolumeLevelScalar(pct / 100.0, None)
            scalar = vol.GetMasterVolumeLevelScalar()
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"set {name} -> {scalar * 100.0:.1f}%")
        return 0

    print("usage: g6_volume.py [list|get|set <0..100>]", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
