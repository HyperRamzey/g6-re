"""Wrap raw G6 firmware banks as ELF files loadable by IDA (ARM Cortex-M).

Fixed ELF writer: explicit 52-byte header, program header at 52, section
table after data. p_vaddr = absolute bank base so IDA maps at real
addresses (0x10000000 loader / 0x10010000 cfg / 0x20000000 main).
"""

import struct
from pathlib import Path

OUT = Path("G:/projects/G6/re_analysis/fw_extract/out")
ELFDIR = Path("G:/projects/G6/re_analysis/fw_extract/elf")

EM_ARM = 40
ET_EXEC = 2


def hdr(entry: int, phoff: int, shoff: int, phnum: int, shnum: int) -> bytes:
    ident = b"\x7fELF" + bytes([1, 1, 1, 0]) + b"\x00" * 8
    # e_type,e_machine,e_version,e_entry,e_phoff,e_shoff,e_flags,
    # e_ehsize,e_phentsize,e_phnum,e_shentsize,e_shnum,e_shstrndx
    return struct.pack(
        "<16sHHIIIIIHHHHHH",
        ident,
        ET_EXEC,
        EM_ARM,
        1,
        entry,
        phoff,
        shoff,
        0x05000000,
        52,
        32,
        phnum,
        40,
        shnum,
        1,
    )


def make_elf(name: str, base: int, data: bytes, entry: int) -> Path:
    phentsize, shentsize, n_ph = 32, 40, 1
    text_off = 52 + phentsize  # header + 1 program header
    shstr = b"\x00.text\x00.shstrtab\x00"
    shstr_off = text_off + len(data)
    shoff = (shstr_off + len(shstr) + 15) & ~15
    n_sh = 3
    total = shoff + shentsize * n_sh
    buf = bytearray(total)

    buf[0:52] = hdr(entry, 52, shoff, n_ph, n_sh)
    # program header: type, offset, vaddr, paddr, filesz, memsz, flags, align
    struct.pack_into(
        "<8I", buf, 52, 1, text_off, base, base, len(data), len(data), 7, 4
    )
    buf[text_off : text_off + len(data)] = data
    buf[shstr_off : shstr_off + len(shstr)] = shstr
    # sh0 null
    struct.pack_into("<10I", buf, shoff, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    # sh1 .text: name, type, flags, addr, offset, size, link, info, align, entsz
    struct.pack_into(
        "<10I", buf, shoff + 40, 1, 1, 6, base, text_off, len(data), 0, 0, 4, 0
    )
    # sh2 .shstrtab
    struct.pack_into(
        "<10I", buf, shoff + 80, 7, 3, 0, 0, shstr_off, len(shstr), 0, 0, 1, 0
    )

    out = ELFDIR / name
    out.write_bytes(buf)
    return out


def main() -> int:
    for p in sorted(OUT.glob("*.bin")):
        if "_base0x" not in p.stem:
            continue
        img = p.read_bytes()
        base = int(p.stem.split("_base0x")[1], 16)
        short = (
            p.stem.replace("SB1770_V1_13_190307_1520", "v1_13")
            .replace("G6_Firmware_V1_16", "v1_16")
            .replace("G6_Firmware_V2.0", "v2_0")
            .replace("SB1770_V2_1_20201208", "v2_1")
            .replace("SB1770_fw_2.1.0903", "v2_1_0903")
            .replace(".", "_")
        )
        entry = base
        if base == 0x20000000 and len(img) >= 8:
            entry = struct.unpack_from("<I", img, 4)[0] & ~1
        if base == 0x10000000:
            # loader records begin at offset 0x8000 inside the bank -> map
            # the image there so thunks (0x10008000+) resolve correctly.
            base = 0x10008000
            entry = 0x10008001
        out = make_elf(f"{short}.elf", base, img, entry)
        print(f"{p.name} -> {out.name} (base 0x{base:X}, entry 0x{entry:X})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
