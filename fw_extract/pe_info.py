"""Dump PE sections + strings of G6 firmware installers to identify the packer.

Read-only: prints section table, imported DLLs, and printable strings that look
like installer/packer identifiers. Never executes anything.
"""

import re
import struct
from pathlib import Path


def u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def main() -> int:
    root = Path("G:/projects/G6")
    for f in sorted(root.glob("*.exe")):
        data = f.read_bytes()
        pe = u32(data, 0x3C)
        machine = u16(data, pe + 4)
        nsec = u16(data, pe + 6)
        opt_size = u16(data, pe + 20)
        chars = u16(data, pe + 22)
        bits = 64 if (chars & 0x20) else 32
        print(f"=== {f.name}  machine=0x{machine:X} {bits}-bit sections={nsec} ===")
        sec0 = pe + 24 + opt_size
        for i in range(nsec):
            so = sec0 + i * 40
            name = data[so : so + 8].rstrip(b"\0").decode("latin1")
            vsize = u32(data, so + 8)
            vaddr = u32(data, so + 12)
            rsize = u32(data, so + 16)
            rptr = u32(data, so + 20)
            print(
                f"  {name:8s} VA=0x{vaddr:08X} VS=0x{vsize:08X} "
                f"raw=0x{rptr:08X}..0x{rptr + rsize:08X} (0x{rsize:X})"
            )
        # strings in whole file, filter interesting
        strs = re.findall(rb"[\x20-\x7e]{6,}", data)
        keys = (
            b"setup",
            b"Setup",
            b"install",
            b"Install",
            b"cab",
            b"CAB",
            b"IScr",
            b"engine",
            b"7-Zip",
            b"WiX",
            b"burn",
            b"wix",
            b"msi",
            b".msi",
            b"firmware",
            b"Firmware",
            b"SB1770",
            b"Malcolm",
            b"VT1728",
            b".bin",
            b"scp",
            b"SCP",
        )
        seen = set()
        for s in strs:
            if any(k in s for k in keys) and s not in seen:
                seen.add(s)
                t = s.decode("latin1")
                if len(t) > 120:
                    t = t[:120] + "..."
                print(f"    STR: {t}")
                if len(seen) > 60:
                    break
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
