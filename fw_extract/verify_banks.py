"""Verify extracted firmware bank images: Cortex-M vector sanity + listing."""

import struct
from pathlib import Path

OUT = Path("G:/projects/G6/re_analysis/fw_extract/out")


def main() -> int:
    for p in sorted(OUT.glob("*.bin")):
        img = p.read_bytes()
        if len(img) < 8:
            print(f"{p.name:58s} {len(img):6d}B  (too small)")
            continue
        w0, w1 = struct.unpack_from("<II", img, 0)
        valid_sp = (0x10000000 <= w0 <= 0x1001FFFF) or (0x20000000 <= w0 <= 0x2007FFFF)
        thumb = w1 & 1
        flag = "SP-OK " if valid_sp else ""
        flag += "THUMB" if thumb else ""
        print(f"{p.name:58s} {len(img):6d}B  SP=0x{w0:08X} Reset=0x{w1:08X} {flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
