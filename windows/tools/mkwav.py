#!/usr/bin/env python
"""
mkwav.py - generate multichannel test stimuli for the g6ct null test.

Writes:
  <out>.wav   WAVE_FORMAT_EXTENSIBLE, IEEE float32 or int16, N channels
  <out>.f32   raw interleaved float32 (for g6ct_cli / Benchmark fallback)

Signals are chosen so every matrix coefficient is independently observable:
each channel gets a distinct frequency, plus a distinct impulse amplitude at
sample 0 so the all-pass cascade can be compared tap by tap.
"""
import argparse
import math
import struct


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True, help="output basename (no extension)")
    p.add_argument("--channels", type=int, default=8)
    p.add_argument("--rate", type=int, default=48000)
    p.add_argument("--seconds", type=float, default=3.0)
    p.add_argument("--bits", choices=("f32", "f64", "s16", "s24"), default="f32")
    p.add_argument("--mask", type=lambda s: int(s, 0), default=0x63F)
    p.add_argument("--mode", choices=("tones", "impulse", "impulsetrain", "noise"), default="tones")
    p.add_argument("--only", default="", help="comma-separated 1-based channels to keep; others are zeroed")
    return p.parse_args()


# channel order = WAVE channel-mask order for 7.1 (0x63F):
# 0 FL 1 FR 2 FC 3 LFE 4 BL 5 BR 6 SL 7 SR
# For 12 channels we keep the same first 8 and append FLC FRC BC TC,
# which matches g6ct's 12-slot index order.
TONES = [440.0, 660.0, 880.0, 60.0, 1000.0, 1300.0, 1700.0, 2100.0,
         2500.0, 2900.0, 3300.0, 3700.0]
AMP = [0.50, 0.45, 0.40, 0.35, 0.30, 0.25, 0.20, 0.15,
       0.12, 0.10, 0.08, 0.06]


def synth(mode, ch, n, rate):
    """Return list of float per frame, interleaved."""
    frames = []
    # deterministic pseudo-noise, identical on every run and platform
    lcg = [0x12345678] * 16

    def rnd(i):
        lcg[i] = (1103515245 * lcg[i] + 12345) & 0x7FFFFFFF
        return lcg[i] / 0x40000000 - 1.0

    for s in range(n):
        t = s / float(rate)
        row = []
        for c in range(ch):
            a = AMP[c % 12]
            f = TONES[c % 12]
            if mode == "tones":
                v = a * math.sin(2.0 * math.pi * f * t)
                v += 0.02 * a * rnd(c)          # decorrelate channels
            elif mode == "noise":
                v = 0.25 * rnd(c)
            elif mode == "impulse":
                v = 1.0 if s == 0 else 0.0
            else:  # impulsetrain
                v = 1.0 if s % 4800 == 0 else 0.0
            row.append(v)
        frames.append(row)
    return frames


def wav_bytes(frames, ch, rate, bits, mask):
    n = len(frames)
    if bits == "s16":
        fmt, sub, width = 1, b"\x01\x00\x00\x00\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71", 2
        enc = lambda v: struct.pack("<h", max(-32768, min(32767, int(round(v * 32767.0)))))
    elif bits == "s24":
        fmt, sub, width = 1, b"\x01\x00\x00\x00\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71", 3
        def enc(v):
            q = max(-8388608, min(8388607, int(round(v * 8388607.0))))
            return struct.pack("<i", q)[:3]
    elif bits == "f32":
        fmt, sub, width = 3, b"\x03\x00\x00\x00\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71", 4
        enc = lambda v: struct.pack("<f", v)
    else:
        fmt, sub, width = 3, b"\x03\x00\x00\x00\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71", 8
        enc = lambda v: struct.pack("<d", v)

    block = ch * width
    data = b"".join(b"".join(enc(v) for v in row) for row in frames)

    if ch <= 2 and bits == "s16":
        fmtchunk = struct.pack("<HHIIHH", 1, ch, rate, rate * block, block, 16)
        riff_fmt = 1
    else:
        fmtchunk = struct.pack("<HHIIHHHHI", 0xFFFE, ch, rate, rate * block, block, width * 8, 22, width * 8, mask) + sub
        riff_fmt = 0xFFFE

    chunks = b""
    chunks += b"fmt " + struct.pack("<I", len(fmtchunk)) + fmtchunk
    if len(fmtchunk) % 2:
        chunks += b"\x00"
    chunks += b"data" + struct.pack("<I", len(data)) + data
    if len(data) % 2:
        chunks += b"\x00"
    return b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks


def main():
    a = parse_args()
    n = int(round(a.seconds * a.rate))
    frames = synth(a.mode, a.channels, n, a.rate)

    if a.only:
        keep = set(int(x) for x in a.only.split(","))
        for row in frames:
            for c in range(len(row)):
                if (c + 1) not in keep:
                    row[c] = 0.0

    data_wav = wav_bytes(frames, a.channels, a.rate, a.bits, a.mask)
    with open(a.out + ".wav", "wb") as f:
        f.write(data_wav)

    if a.bits in ("f32", "s16", "s24"):
        scale = {"f32": 1.0, "s16": 1.0 / 32767.0, "s24": 1.0 / 8388607.0}[a.bits]
        with open(a.out + ".f32", "wb") as f:
            for row in frames:
                f.write(struct.pack("<%df" % a.channels, *[v * scale for v in row]))

    print("wrote %s.wav  %d ch  %d bit  %d Hz  %d frames  mask 0x%X  mode=%s"
          % (a.out, a.channels, {"f32": 32, "f64": 64, "s16": 16, "s24": 24}[a.bits],
             a.rate, n, a.mask, a.mode))


if __name__ == "__main__":
    main()
