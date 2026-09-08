"""Scan G6 firmware installer executables for embedded archive payloads.

Looks for known container magic bytes (7z, zip, cab, RAR5, TAR, gzip) at any
offset, plus InstallShield/NSIS/Inno signatures, and printable strings near
high-entropy regions. Read-only analysis: never executes the installers.
"""

import struct
import sys
from pathlib import Path

MAGICS = [
    (b"7z\xbc\xaf\x27\x1c", "7z archive"),
    (b"PK\x03\x04", "zip local header"),
    (b"MSCF", "MS cabinet"),
    (b"Rar!\x1a\x07\x01\x00", "RAR5"),
    (b"Rar!\x1a\x07\x00", "RAR4"),
    (b"\x1f\x8b\x08", "gzip"),
    (b"ustar", "tar"),
    (b"\xfd7zXZ\x00", "xz"),
    (b"\x28\xb5\x2f\xfd", "zstd"),
    (b"\x04\x22\x4d\x18", "lz4"),
    (b"\x89\x4c\x5a\x4f", "lzo"),
    (b"BZh", "bzip2"),
    (b"ISc(", "InstallShield cab"),
    (b"\xed\xab\xee\xdb", "RPM"),
]


def find_all(data: bytes, pat: bytes, limit: int = 40):
    offs, start = [], 0
    while len(offs) < limit:
        i = data.find(pat, start)
        if i < 0:
            break
        offs.append(i)
        start = i + 1
    return offs


def entropies(data: bytes, win: int = 4096) -> list:
    """Shannon entropy per window, returns list of (offset, entropy)."""
    import math

    out = []
    for off in range(0, len(data) - win, win):
        chunk = data[off : off + win]
        freq = [0] * 256
        for c in chunk:
            freq[c] += 1
        ent = 0.0
        for f in freq:
            if f:
                p = f / win
                ent -= p * math.log2(p)
        out.append((off, ent))
    return out


def main() -> int:
    root = Path("G:/projects/G6")
    files = sorted(root.glob("*.exe"))
    if not files:
        print("no .exe files found", file=sys.stderr)
        return 1

    for f in files:
        data = f.read_bytes()
        print(f"=== {f.name} ({len(data)} bytes) ===")
        for pat, name in MAGICS:
            offs = find_all(data, pat)
            if offs:
                print(
                    f"  {name}: {len(offs)} hit(s) at "
                    + ", ".join(hex(o) for o in offs[:8])
                )
        # high-entropy regions (likely compressed/encrypted fw payload)
        ents = entropies(data)
        hi = [o for o, e in ents if e > 7.2]
        if hi:
            # merge contiguous windows
            runs, cur = [], [hi[0]]
            for o in hi[1:]:
                if o - cur[-1] <= 4096:
                    cur.append(o)
                else:
                    runs.append(cur)
                    cur = [o]
            runs.append(cur)
            for r in runs:
                if len(r) >= 3:
                    print(
                        f"  high-entropy run: 0x{r[0]:X} .. 0x{r[-1] + 4096:X} "
                        f"({(r[-1] + 4096 - r[0]) // 1024} KB)"
                    )
        # PE overlay check: end of last section
        pe_off = struct.unpack_from("<I", data, 0x3C)[0]
        nsec = struct.unpack_from("<H", data, pe_off + 6)[0]
        opt_size = struct.unpack_from("<H", data, pe_off + 20)[0]
        sec0 = pe_off + 24 + opt_size
        max_end = 0
        for i in range(nsec):
            so = sec0 + i * 40
            raw_sz = struct.unpack_from("<I", data, so + 16)[0]
            raw_ptr = struct.unpack_from("<I", data, so + 20)[0]
            end = raw_ptr + raw_sz
            if end > max_end:
                max_end = end
        overlay = len(data) - max_end
        if overlay > 1024:
            print(
                f"  PE overlay after last section: {overlay} bytes "
                f"starting 0x{max_end:X}"
            )
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
