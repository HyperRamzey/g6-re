"""Minimal WAV reader/writer (PCM + IEEE float, plain or EXTENSIBLE)."""
import struct


class Wav:
    def __init__(self, ch, rate, bits, mask, frames):
        self.ch = ch
        self.rate = rate
        self.bits = bits          # 's16' | 's24' | 's32' | 'f32' | 'f64'
        self.mask = mask
        self.frames = frames      # list of lists of float


def read(path):
    with open(path, "rb") as f:
        raw = f.read()
    if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise ValueError("%s: not a RIFF/WAVE file" % path)
    pos = 12
    fmt = data = None
    while pos + 8 <= len(raw):
        cid = raw[pos:pos + 4]
        size = struct.unpack("<I", raw[pos + 4:pos + 8])[0]
        body = raw[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            fmt = body
        elif cid == b"data":
            data = body
        pos += 8 + size + (size & 1)
    if fmt is None or data is None:
        raise ValueError("%s: missing fmt/data" % path)

    tag, ch, rate, _, block, bits = struct.unpack("<HHIIHH", fmt[:16])
    mask = 0
    sub = tag
    if tag == 0xFFFE and len(fmt) >= 40:
        valid, mask = struct.unpack("<HI", fmt[18:24])
        sub = fmt[24]
    width = block // ch

    if sub == 3 and width == 4:
        kind, scale = "f32", 1.0
        unpack = lambda b: struct.unpack("<f", b)[0]
    elif sub == 3 and width == 8:
        kind, scale = "f64", 1.0
        unpack = lambda b: struct.unpack("<d", b)[0]
    elif width == 2:
        kind, scale = "s16", 1.0 / 32768.0
        unpack = lambda b: struct.unpack("<h", b)[0]
    elif width == 3:
        kind, scale = "s24", 1.0 / 8388608.0
        def unpack(b):
            v = b[0] | (b[1] << 8) | (b[2] << 16)
            return v - 0x1000000 if v & 0x800000 else v
    elif width == 4:
        kind, scale = "s32", 1.0 / 2147483648.0
        unpack = lambda b: struct.unpack("<i", b)[0]
    else:
        raise ValueError("%s: unsupported width %d (sub %d)" % (path, width, sub))

    n = len(data) // block
    frames = []
    for i in range(n):
        base = i * block
        frames.append([unpack(data[base + c * width: base + c * width + width]) * scale
                       for c in range(ch)])
    return Wav(ch, rate, kind, mask, frames)


def rms(frames, ch, start=0, stop=None):
    stop = len(frames) if stop is None else stop
    if stop <= start:
        return 0.0
    acc = 0.0
    for i in range(start, stop):
        v = frames[i][ch]
        acc += v * v
    return (acc / (stop - start)) ** 0.5


def peak(frames, ch):
    return max((abs(f[c]) for f in frames for c in [ch]), default=0.0)


def goertzel(frames, ch, freq, rate, start=0, stop=None):
    """Magnitude of one DFT bin, normalised per sample."""
    stop = len(frames) if stop is None else stop
    n = stop - start
    if n <= 0:
        return 0.0
    import math
    w = 2.0 * math.pi * freq / rate
    coeff = 2.0 * math.cos(w)
    s0 = s1 = s2 = 0.0
    for i in range(start, stop):
        s0 = frames[i][ch] + coeff * s1 - s2
        s2, s1 = s1, s0
    real = s1 - s2 * math.cos(w)
    imag = s2 * math.sin(w)
    return math.hypot(real, imag) / n
