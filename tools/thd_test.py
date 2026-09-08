"""DEFINITIVE analog THD test for G6 -2dBFS bug.

Chain: G6 headphone out -> analog cable -> RTK Line In (analog ADC).

Plays a tone at 0 dBFS and -2 dBFS through the G6 at endpoint volumes 100% and 79%,
records RTK Line In, computes THD+N. If the -2dBFS bug exists at 100% volume,
THD+N(0dBFS) >> THD+N(-2dBFS). If firmware fixed it, they'll be nearly equal.

RTK ADC adds its own (small) distortion; we measure its floor with a -20dBFS tone too.
Headphone gain mode on device is currently OFF (from HID probe). SBX/Direct state
per Direct Mode toggle - captured in labels.

Usage: python thd_test.py
"""

import subprocess
import sys
import time

import numpy as np
import sounddevice as sd

SR = 48000
DUR = 4.0
PLAY_DEV = 67  # Speakers (G6) @48k, 8ch (re-enumerated index after SPDIF toggle)
REC_DEV = 113  # Line In (Realtek HD Audio Line input) @44.1k default; force 48k
G6_VOL = "G:/projects/G6/re_analysis/G6Measure/g6_volume.py"


def set_g6_volume(pct):
    r = subprocess.run(
        [sys.executable, G6_VOL, "set", str(pct)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    out = (r.stdout + r.stderr).strip()
    # print only the final result line, not endpoint enumeration noise
    final = out.splitlines()[-1] if out.splitlines() else "(no output)"
    print(f"  volume -> {pct}%: {final}")


def gen_tone(freq, dbfs, dur=DUR, sr=SR):
    try:
        n = int(dur * sr)
        fade = int(0.05 * sr)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"bad tone params: {exc}") from exc
    t = np.arange(n) / sr
    amp = 10 ** (dbfs / 20.0)
    x = amp * np.sin(2 * np.pi * freq * t)
    env = np.ones(n)
    env[:fade] = np.linspace(0, 1, fade)
    env[-fade:] = np.linspace(1, 0, fade)
    return (x * env).astype(np.float32)


def play_and_record(tone):
    """Play 8ch buffer to G6, record 2ch from RTK Line In at 48k. Returns recording."""
    eight = np.column_stack([tone] * 8).astype(np.float32)
    try:
        frames_needed = int((DUR + 2.0) * SR)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"bad capture length params: {exc}") from exc
    recorded = np.zeros((frames_needed, 2), dtype=np.float32)
    state = {"write": 0, "played": 0, "done": False}

    def out_cb(outdata, frame_count, time_info, status):
        s, e = state["played"], state["played"] + frame_count
        if e <= len(eight):
            outdata[:] = eight[s:e]
        elif s < len(eight):
            k = len(eight) - s
            outdata[:k] = eight[s:]
            outdata[k:] = 0
        else:
            outdata[:] = 0
            state["done"] = True
        state["played"] = e

    def in_cb(indata, frame_count, time_info, status):
        end = state["write"] + frame_count
        if end <= frames_needed:
            recorded[state["write"] : end] = indata
        else:
            k = frames_needed - state["write"]
            if k > 0:
                recorded[state["write"] :] = indata[:k]
            state["done"] = True
        state["write"] = end

    ostream = sd.OutputStream(
        device=PLAY_DEV, channels=8, samplerate=SR, callback=out_cb, blocksize=512
    )
    istream = sd.InputStream(
        device=REC_DEV, channels=2, samplerate=SR, callback=in_cb, blocksize=512
    )
    istream.start()
    ostream.start()
    t0 = time.time()
    while not state["done"] and (time.time() - t0) < DUR + 6:
        time.sleep(0.05)
    ostream.stop()
    ostream.close()
    istream.stop()
    istream.close()
    time.sleep(0.2)  # let device settle between tones
    return recorded


def thd_n(rec, freq, sr=SR):
    """THD+N of steady segment, ch0, excluding fundamental +/-6 bins, DC excluded."""
    ch = rec[:, 0].astype(np.float64)
    seg = ch[len(ch) * 2 // 5 :]  # last 60%
    seg = seg - np.mean(seg)
    peak = np.max(np.abs(seg))
    if peak < 1e-6:
        return -np.inf, -np.inf, None
    win = np.blackman(len(seg))
    spec = np.abs(np.fft.rfft(seg * win))
    freqs = np.fft.rfftfreq(len(seg), 1 / sr)
    f0 = np.argmin(np.abs(freqs - freq))
    p_sig = np.sum(spec[max(0, f0 - 4) : f0 + 5] ** 2)
    mask = np.ones(len(spec), dtype=bool)
    mask[max(0, f0 - 6) : f0 + 7] = False
    mask[:3] = False
    p_noise = np.sum(spec[mask] ** 2)
    thdn = np.sqrt(p_noise / p_sig) if p_sig > 0 else np.inf
    thdn_db = 20 * np.log10(thdn) if thdn > 0 else -np.inf
    # list top distortion peaks for diagnosis
    peaks = []
    if p_noise > 0:
        smask = spec.copy()
        smask[: max(0, f0 - 6) : f0 + 7] = 0
        order = np.argsort(smask)[::-1]
        for i in order[:6]:
            if smask[i] / np.sqrt(p_sig) < 1e-4:
                break
            peaks.append((freqs[i], 20 * np.log10(smask[i] / np.sqrt(p_sig))))
    return thdn_db, 20 * np.log10(peak), peaks


def run(freq, dbfs, vol_pct, label):
    set_g6_volume(vol_pct)
    time.sleep(0.4)
    tone = gen_tone(freq, dbfs)
    rec = play_and_record(tone)
    np.save(f"G:/projects/G6/re_analysis/G6Measure/thd_{label}.npy", rec)
    thdn_db, peak_db, peaks = thd_n(rec, freq)
    print(
        f"[{label}] {freq}Hz {dbfs:+.1f}dBFS vol={vol_pct}% -> "
        f"peak {peak_db:7.2f} dBFS | THD+N {thdn_db:7.1f} dB"
    )
    if peaks:
        for f, lvl in peaks[:4]:
            print(f"     spur {f:8.1f} Hz @ {lvl:6.1f} dB")
    return thdn_db


if __name__ == "__main__":
    print("G6 HP out -> RTK Line In analog loopback THD test")
    print(f"Play dev {PLAY_DEV} (8ch), Rec dev {REC_DEV} @ {SR}\n")
    results = {}
    tests = [
        # RTK ADC floor reference (low level, both harmonic + noise)
        (1000, -20.0, 100, "Z0_1k_m20dB_v100"),
        # The core question: 0 dBFS vs -2 dBFS at 100% volume
        (997, 0.0, 100, "A1_997_0dB_v100"),
        (997, -2.0, 100, "A2_997_m2dB_v100"),
        (997, -1.0, 100, "A3_997_m1dB_v100"),
        # Low-frequency tests (amir's low-freq distortion finding)
        (60, 0.0, 100, "B1_60_0dB_v100"),
        (60, -2.0, 100, "B2_60_m2dB_v100"),
        (20, 0.0, 100, "B3_20_0dB_v100"),
        (20, -2.0, 100, "B4_20_m2dB_v100"),
        # 79% volume comparison (community workaround level)
        (997, 0.0, 79, "C1_997_0dB_v79"),
        (997, -2.0, 79, "C2_997_m2dB_v79"),
        (60, 0.0, 79, "C3_60_0dB_v79"),
        (20, 0.0, 79, "C4_20_0dB_v79"),
        # 50% volume sanity
        (997, 0.0, 50, "D1_997_0dB_v50"),
    ]
    for freq, dbfs, vol, label in tests:
        try:
            results[label] = run(freq, dbfs, vol, label)
        except Exception as e:
            print(f"[{label}] FAILED: {e}")
    # restore volume
    set_g6_volume(64)
    print("\n=== SUMMARY (higher THD+N dB = better) ===")
    for k, v in sorted(results.items()):
        print(f"{k:20s}: {v:8.1f} dB")
