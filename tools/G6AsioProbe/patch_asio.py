#!/usr/bin/env python3
r"""Build CtUsAs64_patched.dll - sample-based ASIO latency for the Sound BlasterX G6.

Patches Creative's USB ASIO driver (CtUsAs64.dll v1.1.3.0):

1. Rebinds the COM CLSID {B2D4D5A2-1B17-4AB6-8A6D-667095C480B2} to
   {8F5E2A31-6C74-4B9E-9D3A-2E7F5A6B8C90} so it can be registered per-user
   alongside the stock driver (no system file is modified).

2. ASIOgetBufferSize (sub_409F28 tail @ VA 0x40A037 / file 0x9437): stops
   overwriting min/max with the ms-derived preferred size and sets
   granularity=8:
     stock  : 41 8B 09 41 89 08 89 0B 41 83 23 00   (min=max=pref, gran=0)
     patched: 41 C7 03 08 00 00 00 90 90 90 90 90   (min=1ms, max=100ms, gran=8)

3. Control-panel GUI in samples instead of milliseconds (dialog IDD_ASIOCP_MALCOLM,
   combobox 1012). The dialog stores only the selected INDEX - the ms value is
   re-derived from the same table on save - so changing the displayed strings is
   semantically free. Three edits:
   a) 0x40A919: context alloc 0x20 -> 0x28 (new field +0x20 = CAsio pointer)
   b) 0x40A92F: redirect to cave1, which re-does the original two stores and
      additionally saves rdi (the CAsio object) into ctx+0x20
   c) 0x4093C6: redirect the combobox fill loop to cave2, which loads the live
      sample rate (double at CAsio+0x64), converts the ms table entry to
      samples with the driver's own magic division (x 0x10624DD3 >> 38 ==
      integer /1000, same formula as getBufferSize), and formats via the
      in-place rewritten string "%d ms" -> "%d samples" @ 0x403854.
   The two caves live in the 86 bytes of zero padding at the end of .text
   (VA 0x4253AA..0x425400 - beyond VirtualSize but inside raw data, so the
   loader maps and executes them; verified against the PE section table).

Result @48kHz/50ms: panel shows "2400 samples" instead of "50 ms";
getBufferSize reports min=48 max=4800 preferred=2400 granularity=8 - hosts get
a sample-quantized buffer dropdown and the panel speaks the same language.

Usage:
  python patch_asio.py <path-to-stock> [output-path]

Then register per-user (no admin needed):
  reg add "HKCU\Software\Classes\CLSID\{8F5E2A31-6C74-4B9E-9D3A-2E7F5A6B8C90}\InprocServer32" /ve /d "<abs path to patched dll>" /f
  reg add "HKCU\Software\Classes\CLSID\{8F5E2A31-6C74-4B9E-9D3A-2E7F5A6B8C90}\InprocServer32" /v ThreadingModel /d "Apartment" /f
  reg add "HKCU\Software\ASIO\G6 ASIO (sample-based patch)" /ve /d "G6 sample-based ASIO" /f
  reg add "HKCU\Software\ASIO\G6 ASIO (sample-based patch)" /v CLSID /d "{8F5E2A31-6C74-4B9E-9D3A-2E7F5A6B8C90}" /f
  reg add "HKCU\Software\ASIO\G6 ASIO (sample-based patch)" /v Description /d "Creative Sound Blaster ASIO (sample latency patch)" /f
For Nuendo/Cubase also run register_hklm.cmd (admin) - Steinberg hosts enumerate
HKLM\SOFTWARE\ASIO only.

Uninstall: delete the HKCU/HLM enumeration keys + the CLSID class (unregister_hklm.cmd
plus the reg deletes in docs/ASIO.md).
"""

import struct
import sys
import uuid

OLD_GUID = uuid.UUID("B2D4D5A2-1B17-4AB6-8A6D-667095C480B2")
NEW_GUID = uuid.UUID("8F5E2A31-6C74-4B9E-9D3A-2E7F5A6B8C90")

IMAGE_BASE = 0x400000
TEXT_VA, TEXT_FILE = 0x401000, 0x400  # .text: VA 0x401000 -> file offset 0x400


def va_to_file(va: int) -> int:
    """File offset for a VA inside .text (strings/caves/code all live there)."""
    return va - TEXT_VA + TEXT_FILE


def rel32(src_end_va: int, dst_va: int) -> bytes:
    """rel32 for an E9/lea computed from the VA of the byte AFTER the instruction."""
    return struct.pack("<i", dst_va - src_end_va)


# ---------------------------------------------------------------- patch sites
# 2) getBufferSize range (file 0x9437)
BS_OFF = 0x9437
BS_ORIG = bytes.fromhex("41 8B 09 41 89 08 89 0B 41 83 23 00".replace(" ", ""))
BS_PATCH = bytes.fromhex("41 C7 03 08 00 00 00 90 90 90 90 90".replace(" ", ""))

# 3a) context alloc size (VA 0x40A919, 5 bytes)
ALLOC_VA = 0x40A919
ALLOC_ORIG = bytes.fromhex("B9 20 00 00 00".replace(" ", ""))
ALLOC_PATCH = bytes.fromhex("B9 28 00 00 00".replace(" ", ""))

# 3b) ctx-store redirect (VA 0x40A92F, 10 bytes) -> cave1
STORE_VA = 0x40A92F
STORE_ORIG = bytes.fromhex("48 89 05 92 E4 01 00 48 89 08".replace(" ", ""))
CAVE1_VA = 0x4253AA
STORE_PATCH = b"\xe9" + rel32(STORE_VA + 5, CAVE1_VA) + b"\x90" * 5

# cave1: original stores + save CAsio (rdi) at ctx+0x20, then back to 0x40A939.
# The global store's rel32 must be RECOMPUTED for the cave's own location
# (0x428DC8) - copying the original instruction's rel32 bytes verbatim would
# target a different address, since RIP-relative displacements are position-dependent.
CAVE1_BACK = 0x40A939
cave1 = (
    b"\x48\x89\x05"
    + rel32(CAVE1_VA + 7, 0x428DC8)  # mov cs:qword_428DC8, rax (rel32 for CAVE position)
    + bytes.fromhex("48 89 08".replace(" ", ""))  # mov [rax], rcx      (hwndOwner)
    + bytes.fromhex("48 89 78 20".replace(" ", ""))  # mov [rax+0x20], rdi (CAsio)
    + b"\xe9"
    + rel32(CAVE1_VA + 19, CAVE1_BACK)  # jmp 0x40A939
)

# 3c) combobox fill redirect (VA 0x4093C6, 11 bytes) -> cave2
COMBO_VA = 0x4093C6
COMBO_ORIG = bytes.fromhex("45 8B 0C 24 4C 8D 05 83 A4 FF FF".replace(" ", ""))
CAVE2_VA = CAVE1_VA + len(cave1)  # 0x4253BD
COMBO_PATCH = b"\xe9" + rel32(COMBO_VA + 5, CAVE2_VA) + b"\x90" * 6

FMT_VA = 0x403854  # "%d ms" (12 bytes of space; referenced only by the fill loop)
CAVE2_BACK = 0x4093D1

# cave2: r9d = ms -> samples at the live rate, r8 -> "%d samples"
# Layout (offsets from CAVE2_VA, all verified):
#   +0x00 mov r9d,[r12]          reload ms (same as displaced instruction)
#   +0x04 lea r8,[rip->"%d samples"]   (next = +0x0B)
#   +0x0B mov rax,[rbx+0x20]     ctx->casio (set by cave1; rbx = ctx, callee-saved)
#   +0x0F test rax,rax
#   +0x12 jnz +0x07              -> +0x1B (movsd, normal path)
#   +0x14 mov eax,48000          fallback if casio ptr is somehow null
#   +0x19 jmp +0x0D              -> +0x28 (skip movsd/cvttsd2si - rax would be 0!)
#   +0x1B movsd xmm0,[rax+0x64]  the live rate double
#   +0x23 cvttsd2si rax,xmm0
#   +0x28 mov ecx,r9d
#   +0x2B imul rcx,rax            ms * rate
#   +0x2F imul rcx,rcx,0x10624DD3
#   +0x36 shr rcx,38              == integer /1000 (driver's own magic)
#   +0x3A mov r9d,ecx
#   +0x3D jmp 0x4093D1            back into the fill loop (lea rcx,[rsp+20])
cave2_body = (
    bytes.fromhex("45 8B 0C 24".replace(" ", ""))  # mov r9d, [r12]        (ms)
    + b"\x4c\x8d\x05"
    + rel32(CAVE2_VA + 11, FMT_VA)  # lea r8, "%d samples"
    + bytes.fromhex(
        "48 8B 43 20".replace(" ", "")
    )  # mov rax, [rbx+0x20]   (ctx->casio)
    + bytes.fromhex("48 85 C0".replace(" ", ""))  # test rax, rax
    + b"\x75\x07"  # jnz +0x07 -> +0x1B (movsd)
    + bytes.fromhex(
        "B8 80 BB 00 00".replace(" ", "")
    )  # mov eax, 48000        (fallback rate)
    + b"\xeb\x0d"  # jmp +0x0D -> +0x28 (skip movsd!)
    + bytes.fromhex(
        "F2 0F 10 80 64 00 00 00".replace(" ", "")
    )  # movsd xmm0, [rax+0x64] (rate)
    + bytes.fromhex("F2 48 0F 2C C0".replace(" ", ""))  # cvttsd2si rax, xmm0
    + bytes.fromhex("44 89 C9".replace(" ", ""))  # mov ecx, r9d
    + bytes.fromhex("48 0F AF C8".replace(" ", ""))  # imul rcx, rax          (ms*rate)
    + bytes.fromhex(
        "48 69 C9 D3 4D 62 10".replace(" ", "")
    )  # imul rcx, rcx, 0x10624DD3
    + bytes.fromhex("48 C1 E9 26".replace(" ", ""))  # shr rcx, 38            (== /1000)
    + bytes.fromhex("44 8B C9".replace(" ", ""))  # mov r9d, ecx
)
cave2 = cave2_body + b"\xe9" + rel32(CAVE2_VA + len(cave2_body) + 5, CAVE2_BACK)

# 3d) label string in place: "%d ms\0..." -> "%d samples\0\0"
FMT_ORIG = b"%d ms\x00"
FMT_PATCH = b"%d samples\x00\x00"

CAVE_PAD = 0x56  # zero bytes available at CAVE1_VA (verified against raw .text tail)


def main():
    src = (
        sys.argv[1]
        if len(sys.argv) > 1
        else r"C:\Program Files (x86)\Creative\Creative USB Native ASIO\CtUsAsio\amd64\CtUsAs64.dll"
    )
    dst = sys.argv[2] if len(sys.argv) > 2 else "CtUsAs64_patched.dll"

    try:
        with open(src, "rb") as f:
            data = bytearray(f.read())
    except OSError as e:
        sys.exit(f"cannot read stock driver {src}: {e}")

    # sanity: expected driver bytes at every patch site
    for name, off, orig in (
        ("getBufferSize tail", BS_OFF, BS_ORIG),
        ("panel ctx alloc", va_to_file(ALLOC_VA), ALLOC_ORIG),
        ("panel ctx store", va_to_file(STORE_VA), STORE_ORIG),
        ("panel combo fill", va_to_file(COMBO_VA), COMBO_ORIG),
        ("panel format string", va_to_file(FMT_VA), FMT_ORIG),
    ):
        got = bytes(data[off : off + len(orig)])
        if got != orig:
            sys.exit(
                f"unexpected bytes at {name} (file 0x{off:X}) - stock CtUsAs64.dll "
                f"v1.1.3.0 required, got {got.hex()} expected {orig.hex()}"
            )
    cave_region = bytes(data[va_to_file(CAVE1_VA) : va_to_file(CAVE1_VA) + CAVE_PAD])
    if any(cave_region):
        sys.exit(
            f"code-cave padding at 0x{CAVE1_VA:X} is not empty - layout changed, aborting"
        )
    if len(cave1) + len(cave2) > CAVE_PAD:
        sys.exit(f"caves ({len(cave1) + len(cave2)}B) exceed padding ({CAVE_PAD}B)")

    # 1) buffer range
    data[BS_OFF : BS_OFF + len(BS_ORIG)] = BS_PATCH
    # 3a/3b/3c
    data[va_to_file(ALLOC_VA) : va_to_file(ALLOC_VA) + 5] = ALLOC_PATCH
    data[va_to_file(STORE_VA) : va_to_file(STORE_VA) + len(STORE_ORIG)] = STORE_PATCH
    data[va_to_file(COMBO_VA) : va_to_file(COMBO_VA) + len(COMBO_ORIG)] = COMBO_PATCH
    # caves
    data[va_to_file(CAVE1_VA) : va_to_file(CAVE1_VA) + len(cave1)] = cave1
    data[va_to_file(CAVE2_VA) : va_to_file(CAVE2_VA) + len(cave2)] = cave2
    # 3d) label
    data[va_to_file(FMT_VA) : va_to_file(FMT_VA) + len(FMT_PATCH)] = FMT_PATCH

    # rebind CLSID (binary LE form + registry-script ASCII forms)
    n = 0
    i = 0
    while True:
        i = data.find(OLD_GUID.bytes_le, i)
        if i < 0:
            break
        data[i : i + 16] = NEW_GUID.bytes_le
        n += 1
        i += 16
    for s_old, s_new in [
        (
            b"B2D4D5A2-1B17-4AB6-8A6D-667095C480B2",
            b"8F5E2A31-6C74-4B9E-9D3A-2E7F5A6B8C90",
        ),
        (
            b"{B2D4D5A2-1B17-4AB6-8A6D-667095C480B2}",
            b"{8F5E2A31-6C74-4B9E-9D3A-2E7F5A6B8C90}",
        ),
    ]:
        i = 0
        while True:
            i = data.find(s_old, i)
            if i < 0:
                break
            data[i : i + len(s_old)] = s_new
            n += 1
            i += len(s_old)

    try:
        with open(dst, "wb") as f:
            f.write(bytes(data))
    except OSError as e:
        sys.exit(f"cannot write {dst}: {e}")
    print(f"wrote {dst} ({n} CLSID rewrites + buffer-range + sample-GUI patches)")
    print(
        f"  cave1 {len(cave1)}B @VA 0x{CAVE1_VA:X}, cave2 {len(cave2)}B @VA 0x{CAVE2_VA:X} (pad {CAVE_PAD}B)"
    )


if __name__ == "__main__":
    main()
