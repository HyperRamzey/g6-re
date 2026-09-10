#!/usr/bin/env python3
r"""Build CtUsAs64_patched.dll - sample-based ASIO latency for the Sound BlasterX G6.

Patches Creative's USB ASIO driver (CtUsAs64.dll v1.1.3.0):
  1. Rebinds the COM CLSID {B2D4D5A2-1B17-4AB6-8A6D-667095C480B2} to
     {8F5E2A31-6C74-4B9E-9D3A-2E7F5A6B8C90} so it can be registered per-user
     alongside the stock driver (no system file is modified).
  2. In ASIOgetBufferSize (sub_409F28 tail @ VA 0x40A037 / file 0x9437), stops
     overwriting min/max with the ms-derived preferred size and sets granularity=8:
     stock  : 41 8B 09 41 89 08 89 0B 41 83 23 00   (min=max=pref, gran=0)
     patched: 41 C7 03 08 00 00 00 90 90 90 90 90   (min=1ms, max=100ms, gran=8)
Result @48kHz/50ms: min=48 max=4800 preferred=2400 granularity=8 - hosts get a
sample-quantized buffer dropdown. createBuffers accepts any size (the internal ms
check is advisory-only; verified by disassembly + live probe).

Usage:
  python patch_asio.py <path-to-stock> [output-path]
Then register per-user (no admin needed):
  reg add "HKCU\Software\Classes\CLSID\{8F5E2A31-6C74-4B9E-9D3A-2E7F5A6B8C90}\InprocServer32" /ve /d "<abs path to patched dll>" /f
  reg add "HKCU\Software\Classes\CLSID\{8F5E2A31-6C74-4B9E-9D3A-2E7F5A6B8C90}\InprocServer32" /v ThreadingModel /d "Apartment" /f
  reg add "HKCU\Software\ASIO\G6 ASIO (sample-based patch)" /ve /d "G6 sample-based ASIO" /f
  reg add "HKCU\Software\ASIO\G6 ASIO (sample-based patch)" /v CLSID /d "{8F5E2A31-6C74-4B9E-9D3A-2E7F5A6B8C90}" /f
  reg add "HKCU\Software\ASIO\G6 ASIO (sample-based patch)" /v Description /d "Creative Sound Blaster ASIO (sample latency patch)" /f
Uninstall: delete those two registry keys.
"""
import sys
import uuid

OLD_GUID = uuid.UUID('B2D4D5A2-1B17-4AB6-8A6D-667095C480B2')
NEW_GUID = uuid.UUID('8F5E2A31-6C74-4B9E-9D3A-2E7F5A6B8C90')
# sub_409F28 tail: bytes at VA 0x40A037 (.text RVA 0xA037 -> file 0x9437)
ORIG = bytes.fromhex('41 8B 09 41 89 08 89 0B 41 83 23 00'.replace(' ', ''))
PATCH = bytes.fromhex('41 C7 03 08 00 00 00 90 90 90 90 90'.replace(' ', ''))
FILE_OFF = 0x9437

def main():
    src = sys.argv[1] if len(sys.argv) > 1 else r'C:\Program Files (x86)\Creative\Creative USB Native ASIO\CtUsAsio\amd64\CtUsAs64.dll'
    dst = sys.argv[2] if len(sys.argv) > 2 else 'CtUsAs64_patched.dll'
    try:
        with open(src, 'rb') as f:
            data = bytearray(f.read())
    except OSError as e:
        sys.exit(f'cannot read stock driver {src}: {e}')
    # sanity: expected driver version bytes
    assert data[FILE_OFF:FILE_OFF + len(ORIG)] == ORIG, (
        f'unexpected bytes at 0x{FILE_OFF:X} - stock CtUsAs64.dll v1.1.3.0 required, '
        f'got {data[FILE_OFF:FILE_OFF + len(ORIG)].hex()}')
    data[FILE_OFF:FILE_OFF + len(ORIG)] = PATCH
    # rebind CLSID (binary LE form + registry-script ASCII forms)
    n = 0
    i = 0
    while True:
        i = data.find(OLD_GUID.bytes_le, i)
        if i < 0:
            break
        data[i:i + 16] = NEW_GUID.bytes_le
        n += 1
        i += 16
    for s_old, s_new in [
        (b'B2D4D5A2-1B17-4AB6-8A6D-667095C480B2', b'8F5E2A31-6C74-4B9E-9D3A-2E7F5A6B8C90'),
        (b'{B2D4D5A2-1B17-4AB6-8A6D-667095C480B2}', b'{8F5E2A31-6C74-4B9E-9D3A-2E7F5A6B8C90}'),
    ]:
        i = 0
        while True:
            i = data.find(s_old, i)
            if i < 0:
                break
            data[i:i + len(s_old)] = s_new
            n += 1
            i += len(s_old)
    try:
        with open(dst, 'wb') as f:
            f.write(bytes(data))
    except OSError as e:
        sys.exit(f'cannot write {dst}: {e}')
    print(f'wrote {dst} ({n} CLSID rewrites + buffer-range patch)')

if __name__ == '__main__':
    main()
