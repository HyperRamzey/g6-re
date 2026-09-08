"""Line-based Intel-HEX parser for ALL G6 installers -> per-bank .bin files.

Replaces the earlier regex-based extract (which mis-parsed checksums) and the
first 64KB-only extraction (which dropped extended-address banks). Writes
out/<installer>_base0x<hex>.bin for every bank found. Read-only vs device.
"""

import re
from pathlib import Path

ROOT = Path("G:/projects/G6")
OUT = Path("G:/projects/G6/re_analysis/fw_extract/out")


def parse(data: bytes):
    lines = re.findall(rb":[0-9A-F]+", data)
    banks = {}
    base = 0
    bad = 0
    for ln in lines:
        body = ln[1:].decode()
        if len(body) < 8:
            bad += 1
            continue
        try:
            cnt = int(body[0:2], 16)
            addr = int(body[2:6], 16)
            rt = int(body[6:8], 16)
        except ValueError:
            bad += 1
            continue
        rest = body[8:]
        if len(rest) != cnt * 2 + 2:
            bad += 1
            continue
        d = bytes.fromhex(rest[: cnt * 2])
        ck = int(rest[cnt * 2 :], 16)
        tot = cnt + (addr >> 8) + (addr & 0xFF) + rt + sum(d) + ck
        if tot & 0xFF:
            bad += 1
            continue
        if rt == 0:
            banks.setdefault(base, {}).setdefault(addr, b"")
            banks[base][addr] = d
        elif rt == 4:
            base = int.from_bytes(d, "big") << 16
    return banks, bad


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    # old installers + extracted 2025 inner flasher
    srcs = sorted(ROOT.glob("*.exe")) + [
        Path("G:/projects/G6/re_analysis/fw_extract/SB1770_fw_2.1.0903.exe")
    ]
    for f in srcs:
        data = f.read_bytes()
        banks, bad = parse(data)
        if not banks:
            print(f"{f.name}: no banks")
            continue
        print(f"=== {f.name} (bad records: {bad}) ===")
        for b, mem in banks.items():
            lo, hi = min(mem), max(mem)
            size = hi + 16 - lo
            img = bytearray(size)
            filled = 0
            for a, ch in mem.items():
                img[a - lo : a - lo + len(ch)] = ch
                filled += len(ch)
            tag = f.name.replace(".exe", "").replace("SBG6FWInstaller_", "SBG6_")
            out = OUT / f"{tag}_base0x{b:X}.bin"
            k = 1
            while out.exists() and out.stat().st_size != len(img):
                out = OUT / f"{tag}_base0x{b:X}_{k}.bin"
                k += 1
            out.write_bytes(img)
            print(
                f"  base 0x{b:X}: 0x{lo:X}..0x{hi:X} size={size} "
                f"filled={filled} -> {out.name}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
