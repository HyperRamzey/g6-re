#!/usr/bin/env python3
r"""Build CtUsAs64_patched.dll - raw-SAMPLE-based ASIO latency for the G6.

v4: the driver's latency model switches from milliseconds to RAW SAMPLES.

What changes vs stock (CtUsAs64.dll v1.1.3.0):

  * New 16-entry sample table (all 16-multiples, includes 128/256/512) in the
    .rsrc section padding:
      48, 96, 128, 192, 256, 320, 384, 512, 640, 768,
      1024, 1536, 2048, 3072, 3840, 4800
  * Registry: writes/reads "LatencyS" (REG_DWORD = raw samples) instead of
    "Latency" (ms). The stock value name is untouched, so uninstalling v4
    restores stock behaviour with its own ms setting intact.
  * getBufferSize: min=max=preferred = LatencyS (raw). Granularity = 16.
  * Panel: combobox lists the sample table directly ("%d samples" was already
    the label since v3; the entries are now the raw table values, no
    conversion cave). Index-based selection + save as stock.
  * Panel save: stores raw samples to [+40] (int) and [+48] (samples/s as
    double - stock stored ms there; both are recomputed consistently).
  * The createBuffers advisory ms-check (sub_40BAB8) is neutered (returns 1
    always): hosts asking for any 16..4800 size get no spurious
    kAsioResetRequest spam. createBuffers itself never rejected sizes (the
    gate result was always discarded) - now the advisory side-effect is gone
    too.
  * CLSID rebinding as before ({B2D4D5A2-...} -> {8F5E2A31-...}, per-user
    registration possible).

NOTE on "why raw": the stock driver stores latency in integer MILLISECONDS, so
exact powers of two (128/256/512 samples) were unreachable (256 = 5.33 ms).
This build keeps one DWORD of state ([+40]) holding SAMPLES instead.

Usage:
  python patch_asio.py <path-to-stock> [output-path]
"""

import struct
import sys
import uuid

OLD_GUID = uuid.UUID("B2D4D5A2-1B17-4AB6-8A6D-667095C480B2")
NEW_GUID = uuid.UUID("8F5E2A31-6C74-4B9E-9D3A-2E7F5A6B8C90")

IMAGE_BASE = 0x400000
TEXT_VA, TEXT_FILE = 0x401000, 0x400  # .text: VA 0x401000 -> file 0x400


def v2f(va: int) -> int:
    """File offset for a VA inside .text."""
    return va - TEXT_VA + TEXT_FILE


def rel32(src_end_va: int, dst_va: int) -> bytes:
    """rel32 for an E9/lea computed from the VA of the byte AFTER the instruction."""
    return struct.pack("<i", dst_va - src_end_va)


# ------------------------------------------------------------- new sample table
# Lives in .rsrc padding (VA 0x42FF68, file 0x2AD68, 0x98 zero bytes verified).
SAMPLE_TABLE_VA = 0x42FF68
SAMPLES = [
    48,
    96,
    128,
    192,
    256,
    320,
    384,
    512,
    640,
    768,
    1024,
    1536,
    2048,
    3072,
    3840,
    4800,
]
N_ENTRIES = len(SAMPLES)  # 16
SAMPLE_TABLE = struct.pack("<16I", *SAMPLES)
SAMPLE_TABLE_FILE = 0x2AD68  # rsrc: VA 0x42D000 = file 0x2B000? NO:
# .rsrc section: VA 0x42D000, raw at file: sections say VA 0x2d000 rva, raw ptr?
# Corrected below after PE check - see SAMPLE_TABLE_FILE_DEF.

# ---------------------------------------------------------------- patch sites
# (name, VA, stock bytes, replacement bytes) - all stock patterns pre-verified
# against the file before patching at runtime too.

# 1) getBufferSize min: stock computes rate * ms[0] / 1000 via magic division:
#      0x409F75: imul ecx, cs:[427A08]  (7B)  0F AF 0D 8C DA 01 00
#      0x409F7C: mul ecx                (2B)  F7 E1
#      0x409F7E: mov eax, esi           (2B)  8B C6
#      0x409F80: shr edx, 6             (3B)  C1 EA 06   (== /1000)
#      0x409F83: mov [rbx], edx        (2B)  89 13
#    -> replace ALL 16 bytes with: mov ecx,[r10+28h]; mov [rbx],ecx; nops
GB_MIN_VA = 0x409F75
GB_MIN_ORIG = bytes.fromhex("0FAF0D8CDA0100F7E18BC6C1EA068913")
GB_MIN_PATCH = (
    bytes.fromhex("418B4A28")  # mov ecx, [r10+28h]   (raw LatencyS)  (4)
    + bytes.fromhex("890B")  # mov [rbx], ecx       (min = raw)     (2)
    + b"\x90" * 10  # nops                                 (10)
)  # 16 bytes exactly

# 2) getBufferSize max: stock computes rate * 100ms / 1000:
#      0x409F8B: imul ecx, cs:[427A38]  (7B)
#      0x409F92: mul ecx                (2B)
#      0x409F94: shr edx, 6             (3B)
#      0x409F97: mov [r8], edx          (3B)  41 89 10
#    -> replace ALL 15 bytes with: mov ecx,[r10+28h]; mov [r8],ecx; nops
GB_MAX_VA = 0x409F8B
GB_MAX_ORIG = bytes.fromhex("0FAF0DA6DA0100F7E1C1EA06418910")
GB_MAX_PATCH = (
    bytes.fromhex("418B4A28")  # mov ecx, [r10+28h]   (raw LatencyS)  (4)
    + bytes.fromhex("418908")  # mov [r8], ecx        (max = raw)     (3)
    + b"\x90" * 8  # nops                                 (8)
)  # 15 bytes exactly

# 3) getBufferSize preferred block (0x409FA4..0x409FE9, 70 bytes):
#    stock computes round-to-8 ms->samples; patched = raw LatencyS ([r10+28h])
#    so the pre-createBuffers query is never 0. (The state>=2 branch at
#    0x409FEC already reads [+D0] = actual size; the [+48] ms write in the
#    shared tail is harmless since all consumers are patched.)
GB_PREF_VA = 0x409FA4
GB_PREF_ORIG = bytes.fromhex(
    "F2490F2C4264418B4A280FAFC88BC6F7E18BCAC1E9068BC19983E20703C28BF083E007"
    "C1FE033BC2740C8D04F508000000418901EB034189094139397514418909BF18FCFFFF".replace(
        " ", ""
    )
)
GB_PREF_PATCH = (
    bytes.fromhex("418B4228")  # mov eax, [r10+28h]  (raw LatencyS)
    + bytes.fromhex("418901")  # mov [r9], eax       (preferred)
    + b"\x90" * 61  # nops
    + b"\xeb\x0c"  # jmp +0x0C -> 0x409FF6 (shared tail)
)  # 4+3+61+2 = 70 bytes exactly

# 4) granularity 8 -> 16 (getBufferSize tail, file 0x9437)
BS_OFF = 0x9437
BS_ORIG = bytes.fromhex("418B0941890889 0B 41832300".replace(" ", ""))
BS_PATCH = bytes.fromhex("41C70310000000" + "90" * 5)  # mov dword [r11],16 ; nops

# 5) panel scan bound 13 -> 16 (sub_40A880)
SCAN_VA = 0x40A8F4
SCAN_ORIG = bytes.fromhex("83F80D")
SCAN_PATCH = bytes.fromhex("83F810")  # cmp eax, 10h

# 6) panel save-clamp 13 -> 16
CLAMP_VA = 0x40A941
CLAMP_ORIG = bytes.fromhex("4183FD0D")
CLAMP_PATCH = bytes.fromhex("4183FD10")  # cmp r13d, 10h

# 7) panel save value: was mov r8d,[r13+rsi*4] (ms table) -> samples table
#    r13 already points at the table (lea r13 moved by site 15); keep the same
#    instruction - only the TABLE POINTER changes (sites 9/15). No byte patch
#    needed here (verified same encoding works for .rsrc VA distance? -> the
#    rel32 distance grows; but the LEA is patched at site 15, instruction
#    identical). So: NO PATCH at 0x40AAAC - just documentation.
SAVE_MOV_VA = 0x40AAAC
SAVE_MOV_ORIG = bytes.fromhex("458b04b6")

# 8) panel save advisory-arg block (0x40AAE8, 22 bytes):
#    stock: r11 = rate(as int) * ms, then magic /1000 -> arg for selector 4
#    patched: r11 = raw sample count from [+28h]; skip the multiply+divide.
ADV_VA = 0x40AAE8
ADV_ORIG = bytes.fromhex(
    "f24c0f2c5f64440faf5f28b8d34d621041f7e3c1ea06".replace(" ", "")
)
ADV_PATCH = (
    bytes.fromhex("448B5F28")  # mov r11d, [rdi+28h]   (raw samples)  (4)
    + b"\x90" * 18  # nops (18 - the site is 22 bytes: 4-byte mov + 18 nops;
    #  the stock sequence's trailing '06' byte MUST be overwritten too - leaving
    #  it would be an invalid-opcode #UD landmine in 64-bit mode)
)  # 4+18 = 22 exactly

# 9) dialog table lea: patch ONLY the rel32 (keep opcode 4C 8D 25 = lea r12 -
#    the loop body reads [r12] and r12++ strides the table; the register
#    byte must NOT change)
DLG_LEA_VA = 0x4093BB
DLG_LEA_ORIG = bytes.fromhex("4C8D2546E60100")
DLG_LEA_PATCH = b"\x4c\x8d\x25" + rel32(DLG_LEA_VA + 7, SAMPLE_TABLE_VA)

# 9b) dialog format string: "%d ms" -> "%d samples" (in place, 12 bytes avail)
FMT_VA = 0x403854
FMT_ORIG = b"%d ms\x00"
FMT_PATCH = b"%d samples\x00\x00"

# 10) dialog entry counter 13 -> 16
DLG_CNT_VA = 0x4093C2
DLG_CNT_ORIG = bytes.fromhex("448D6D0D")
DLG_CNT_PATCH = bytes.fromhex("448D6D10")  # lea r13d, [rbp+10h]

# 11) advisory gate (sub_40BAB8): always return 1 (neutered).
#     "mov ebx,1" (BB 01000000) -> "xor ebx,ebx; ... " but we need return 1:
#     stock: v5=1 default; if mismatch -> v5=0 + callbacks. Simplest neuter:
#     overwrite the condition jump target: make the fabs-compare never taken.
#     At 0x40BADC: replace "mov ebx,1" with "mov ebx,1; jmp ret" is what stock
#     already does when no mismatch... cleanest: patch the CONDITIONAL jump at
#     0x40BAFA (jbe/ja after fabs cmp) to NEVER jump into the callback block.
#     Simpler still: replace "mov ebx,1" (5B) at the top with
#     "mov eax,1; ret" (B8 01000000 C3) = 6 bytes - 1 too many.
#     Use: "mov ebx,1" stays; patch the ucomisd+jbe pair? Too fiddly.
#     CHOSEN: replace 0x40BADC "BB 01 00 00 00" with "33 C0 EB 07 90 90" ?
#     No - keep it minimal and provably correct: patch the FIRST instruction
#     of the mismatch block's callback chain: 0x40BAFC "mov rax,[rdx]" -
#     replace with "mov eax,1; ret" would break stack (fn uses ret in epilogue
#     with pops). Instead: neuter the CONDITION: fabs(...) > 0.001 never true.
#     The compare is: F2 0F 59 49 30 (mulsd), F2 0F 5C D1 (subsd), 66 0F 2F 15
#     AE8FFFFF (comisd), 76 7F (jbe skip). Patch "76 7F" (jbe) -> "EB 7F"
#     (jmp always): the mismatch block NEVER runs. Verified bytes below.
GATE_JCC_VA = 0x40BAFA
GATE_JCC_ORIG = bytes.fromhex("767F")
GATE_JCC_PATCH = bytes.fromhex("EB7F")  # jbe -> jmp (block never runs)

# 12) init +48 double: (double)Latency_ms -> (double)LatencyS*1000/rate.
#     Stock 0x40992B: F2 0F 11 47 30 (movsd [rdi+30h],xmm0) with xmm0 = (double)ms
#     loaded at 0x40992B-6: F2 49 0F 2A C0 (cvtsi2sd xmm0,r8)... actually:
#     0x40992B bytes = F2 0F 11 47 30 ; the cvtsi2sd is at 0x409926:
#     "f2 49 0f 2a c0"? verify from earlier dump: 0x40992b: F2 0F 11 47 30.
#     We need [+48] = samples/sec as double. Redo: [+48] = (double)[+40] is
#     fine IF every /1000 use of [+48] is patched away. [+48] is used by:
#       a) getLatencies/getBufferSize preferred: our patches no longer read it
#          (min/max/pref = raw [+40]/[+D0]).
#       b) sub_40BAB8 gate: neutered.
#       c) panel save 0x40AAB9 movsd [rdi+30h],xmm0 = (double)raw samples:
#          stock semantics = ms; patched = raw samples. Since all consumers of
#          [+48] are patched, storing (double)raw is CONSISTENT.
#     => No patch needed at 0x40992B beyond leaving cvtsi2sd as (double)raw.

# 13) registry value name "Latency" -> "LatencyS" (init read + panel save +
#     both use sub_4116B8(name lookup)). "Latency" string @0x4039D8, 8 bytes
#     "Latency\0"; "LatencyS\0" needs 9 - only 8+1 available? Check .rdata
#     spacing at 0x4039D8: bytes "Latency\0BitDepth\0..." -> we can write
#     "LatencyS" OVER "Latency\0" (9 bytes: L a t e n c y S \0) - this eats
#     the null; next string "BitDepth" starts at 0x4039E1? Verify layout:
LAT_VA = 0x4039D8
LAT_ORIG = b"Latency\x00"
LAT_PATCH = b"LatencyS\x00" if False else b"LatencyS\x00"  # see NAME_REWRITE
# Actually "Latency\0" = 8 bytes at 0x4039D8..0x4039DF; "LatencyS\0" = 9 bytes
# would overlap the NEXT string. Stock layout (from dump): 0x4039D8 "Latency\0"
# 0x4039E0 "BitDepth\0" - adjacent! Writing 9 bytes eats 'B' of BitDepth.
# FIX: write "LatencyS\0" needs the 'S' + the NUL = 2 extra bytes - NO ROOM.
# => Instead RELOCATE the name: the code does lea rdx, aLatency (7B) at
#    0x40AABE and 0x4098F6-ish (two sites) - repoint both leas to a new
#    "LatencyS\0" string written in .text cave space. Cave has 86-19-66 = 1B
#    left... .rsrc pad has 0x98-64(table) = 56 bytes left. Put the string
#    right after the table: SAMPLE_TABLE_VA + 64 = 0x42FFA8.
LATNAME_VA = SAMPLE_TABLE_VA + 64  # 0x42FFA8
LATNAME = b"LatencyS\x00"
# lea sites (from disasm): 0x40AABE "48 8D 15 13 8F FF FF" (lea rdx, aLatency)
# and init read: sub_4098A0 area 0x4098F6 "48 8D 15 DD A0 FF FF"? verify:
LEA1_VA = 0x40AABE
LEA1_ORIG = bytes.fromhex(
    "48 8D 15 13 8F FF FF".replace(" ", "")
)  # lea rdx, aLatency (panel save)
LEA2_VA = 0x4098E7
LEA2_ORIG = bytes.fromhex(
    "48 8D 15 EA A0 FF FF".replace(" ", "")
)  # lea rdx, aLatency (init read)
LEA1_PATCH = b"\x48\x8d\x15" + rel32(LEA1_VA + 7, LATNAME_VA)
LEA2_PATCH = b"\x48\x8d\x15" + rel32(LEA2_VA + 7, LATNAME_VA)

# 14) panel save [+40] int store stays (mov [rdi+28h],r8d @0x40AAB0) - raw now.

# 15) panel table leas (4 sites): rel32 -> sample table
PANEL_LEAS = [
    (0x40A8DE, bytes.fromhex("4C8D3523D10100")),
    (0x40A9F1, bytes.fromhex("4C8D3510D00100")),
    (0x40AA24, bytes.fromhex("4C8D35DDCF0100")),
    (0x40AA39, bytes.fromhex("4C8D35C8CF0100")),
]
PANEL_LEAS_PATCH = [
    b"\x4c\x8d\x35" + rel32(va + 7, SAMPLE_TABLE_VA) for va, _ in PANEL_LEAS
]

# .rsrc padding location (verified all-zero, 0x98 bytes).
# The table sits PAST VirtualSize (vsize 0x2F68 < rawsize 0x3000) - bytes
# beyond vsize are not guaranteed mapped. Fix: extend .rsrc VirtualSize to
# 0x3000 in the section header so the loader maps the full raw data.
RSRC_FILE = 0x2AD68
RSRC_VA = 0x42FF68
RSRC_VSIZE_OFF = (
    0x2A8 + 8
)  # PE section headers: .rsrc is 3rd header; Misc.VirtualSize at +8
# (computed properly in main() from the PE headers, not hardcoded here)


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

    # ---- sanity: every stock pattern must match EXACTLY
    all_sites = [
        ("getBufferSize tail", BS_OFF, BS_ORIG),
        ("getBufferSize min", v2f(GB_MIN_VA), GB_MIN_ORIG),
        ("getBufferSize max", v2f(GB_MAX_VA), GB_MAX_ORIG),
        ("getBufferSize pref block", v2f(GB_PREF_VA), GB_PREF_ORIG),
        ("panel scan bound", v2f(SCAN_VA), SCAN_ORIG),
        ("panel clamp", v2f(CLAMP_VA), CLAMP_ORIG),
        ("panel save mov", v2f(SAVE_MOV_VA), SAVE_MOV_ORIG),
        ("panel adv block", v2f(ADV_VA), ADV_ORIG),
        ("dialog lea", v2f(DLG_LEA_VA), DLG_LEA_ORIG),
        ("dialog counter", v2f(DLG_CNT_VA), DLG_CNT_ORIG),
        ("dialog format str", v2f(FMT_VA), FMT_ORIG),
        ("gate jcc", v2f(GATE_JCC_VA), GATE_JCC_ORIG),
        ("latency name str", v2f(LAT_VA), LAT_ORIG),
        ("lea1 (panel save)", v2f(LEA1_VA), LEA1_ORIG),
        ("lea2 (init read)", v2f(LEA2_VA), LEA2_ORIG),
        ("Latency str neighbors", v2f(LAT_VA), LAT_ORIG),
    ]
    for i, (va, orig) in enumerate(PANEL_LEAS):
        all_sites.append((f"panel lea{i + 1}", v2f(va), orig))

    for name, off, orig in all_sites:
        got = bytes(data[off : off + len(orig)])
        if got != orig:
            sys.exit(
                f"unexpected bytes at {name} (file 0x{off:X}) - stock CtUsAs64.dll "
                f"v1.1.3.0 required. got {got.hex()} expected {orig.hex()}"
            )

    # .rsrc padding must be zero
    pad = bytes(data[RSRC_FILE : RSRC_FILE + 0x98])
    if any(pad):
        sys.exit(f".rsrc padding at file 0x{RSRC_FILE:X} is not empty - aborting")
    need = len(SAMPLE_TABLE) + len(LATNAME)
    if need > 0x98:
        sys.exit(f"table+name ({need}B) exceed .rsrc pad (0x98)")
    # ---- extend .rsrc VirtualSize to cover the padding (loader guarantee)
    import pefile

    pe = pefile.PE(data=bytes(data), fast_load=True)
    rsrc = next(s for s in pe.sections if s.Name.rstrip(b"\x00") == b".rsrc")
    if rsrc.Misc_VirtualSize < rsrc.SizeOfRawData:
        # Misc.VirtualSize is at section-header + 8 (after the 8-byte Name field).
        # pefile's get_file_offset() returns the section HEADER entry offset.
        hdr_off = rsrc.get_file_offset()
        data[hdr_off + 8 : hdr_off + 12] = struct.pack("<I", rsrc.SizeOfRawData)
    pe2 = pefile.PE(data=bytes(data), fast_load=True)
    rsrc2 = next(s for s in pe2.sections if s.Name.rstrip(b"\x00") == b".rsrc")
    if rsrc2.Misc_VirtualSize != rsrc2.SizeOfRawData:
        sys.exit("failed to extend .rsrc VirtualSize")

    # ---- apply patches
    def put(va_or_off, patch, is_file=False):
        off = va_or_off if is_file else v2f(va_or_off)
        data[off : off + len(patch)] = patch

    # sample table + relocated value name
    data[RSRC_FILE : RSRC_FILE + len(SAMPLE_TABLE)] = SAMPLE_TABLE
    data[RSRC_FILE + 64 : RSRC_FILE + 64 + len(LATNAME)] = LATNAME

    # getBufferSize
    put(BS_OFF, BS_PATCH, is_file=True)
    put(GB_MIN_VA, GB_MIN_PATCH)
    put(GB_MAX_VA, GB_MAX_PATCH)
    put(GB_PREF_VA, GB_PREF_PATCH)

    # panel
    put(SCAN_VA, SCAN_PATCH)
    put(CLAMP_VA, CLAMP_PATCH)
    put(ADV_VA, ADV_PATCH)
    for (va, _), patch in zip(PANEL_LEAS, PANEL_LEAS_PATCH, strict=True):
        put(va, patch)

    # dialog
    put(DLG_LEA_VA, DLG_LEA_PATCH)
    put(DLG_CNT_VA, DLG_CNT_PATCH)
    put(FMT_VA, FMT_PATCH)

    # gate neuter
    put(GATE_JCC_VA, GATE_JCC_PATCH)

    # latency name leas
    put(LEA1_VA, LEA1_PATCH)
    put(LEA2_VA, LEA2_PATCH)

    # CLSID rebind
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
    print(f"wrote {dst}")
    print(f"  {n} CLSID rewrites; raw-sample latency model (16 entries, gran 16)")
    print(
        f"  sample table @VA 0x{SAMPLE_TABLE_VA:X} (file 0x{RSRC_FILE:X}); LatencyS name @0x{LATNAME_VA:X}"
    )


if __name__ == "__main__":
    main()
