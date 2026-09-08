"""Optical tap test for G6 -2dBFS bug (Phase A/B).

Setup: G6 SPDIF Out -> (optical) -> G6 SPDIF In  [self-loopback]
       or                              -> Realtek optical-in (RTK)

Phase A: Direct Mode ON  -> expect bit-perfect passthrough of source PCM.
Phase B: Direct Mode OFF -> observe what digital stream the DAC/amp path receives:
        - 0 dBFS in  -> 0 dBFS out?  (bug: DAC driven to full scale)
        - 0 dBFS in  -> -2 dBFS out? ("fixed": firmware trims headroom)
        - volume 100% vs 79% vs 50% Windows volume effect on digital stream.

Analysis: sample-exactness (correlation with expected tone), peak level, THD+N.
"""

import time

import numpy as np
import sounddevice as sd

SR = 48000
DUR = 4.0
REC_DEV = 79  # SPDIF In (Sound BlasterX G6) @48k


def find_g6_playback():
    for i, d in enumerate(sd.query_devices()):
        if "G6" in d["name"] and d["max_output_channels"] > 0:
            return i
    return None


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


def analyze(rec, freq, sr=SR):
    """Return (peak_dbfs, thd_n_db, correlation_shift, max_sample_err)."""
    ch = rec[:, 0].astype(np.float64)
    # find steady segment: last 60% of capture
    seg = ch[len(ch) * 2 // 5 :]
    peak = np.max(np.abs(seg))
    seg = seg - np.mean(seg)
    win = np.blackman(len(seg))
    spec = np.abs(np.fft.rfft(seg * win))
    freqs = np.fft.rfftfreq(len(seg), 1 / sr)
    f0 = np.argmin(np.abs(freqs - freq))
    p_sig = np.sum(spec[max(0, f0 - 4) : f0 + 5] ** 2)
    mask = np.ones(len(spec), dtype=bool)
    mask[max(0, f0 - 6) : f0 + 7] = False
    mask[:3] = False
    p_noise = np.sum(spec[mask] ** 2)
    thdn = np.sqrt(p_noise / p_sig)
    thdn_db = 20 * np.log10(thdn) if thdn > 0 else -np.inf

    # sample-exactness: correlate against expected steady tone, search phase
    n = len(seg)
    t = np.arange(n) / sr
    expected = np.sin(2 * np.pi * freq * t)  # unit amplitude
    # normalized correlation via FFT
    a = seg / (peak if peak > 0 else 1)
    corr = np.fft.irfft(np.fft.rfft(a) * np.conj(np.fft.rfft(expected)), n)
    shift = np.argmax(np.abs(corr))
    # reconstruct aligned expected and compute residual
    exp_aligned = np.roll(expected, shift)
    if corr[shift] < 0:
        exp_aligned = -exp_aligned
    resid = a - exp_aligned * (
        np.dot(a, exp_aligned) / max(np.dot(exp_aligned, exp_aligned), 1e-12)
    )
    resid_db = 20 * np.log10(np.sqrt(np.mean(resid**2)) + 1e-12)
    return peak, thdn_db, shift, resid_db


def run_test(freq, dbfs, label, play_dev, verbose=True):
    tone = gen_tone(freq, dbfs)
    stereo = np.column_stack([tone, tone]).astype(np.float32)
    try:
        frames_needed = int((DUR + 2.0) * SR)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"bad capture length params: {exc}") from exc
    recorded = np.zeros((frames_needed, 2), dtype=np.float32)
    write_pos = 0
    played = {"n": 0}
    done = {"flag": False}

    def out_cb(outdata, frame_count, time_info, status):
        s, e = played["n"], played["n"] + frame_count
        if e <= len(stereo):
            outdata[:] = stereo[s:e]
        elif s < len(stereo):
            k = len(stereo) - s
            outdata[:k] = stereo[s:]
            outdata[k:] = 0
        else:
            outdata[:] = 0
            done["flag"] = True
        played["n"] = e

    def in_cb(indata, frame_count, time_info, status):
        nonlocal write_pos
        e = write_pos + frame_count
        if e <= frames_needed:
            recorded[write_pos:e] = indata
        else:
            k = frames_needed - write_pos
            if k > 0:
                recorded[write_pos:] = indata[:k]
            done["flag"] = True
        write_pos = e

    ostream = sd.OutputStream(
        device=play_dev, channels=2, samplerate=SR, callback=out_cb, blocksize=512
    )
    istream = sd.InputStream(
        device=REC_DEV, channels=2, samplerate=SR, callback=in_cb, blocksize=512
    )
    istream.start()
    ostream.start()
    t0 = time.time()
    while not done["flag"] and (time.time() - t0) < DUR + 5:
        time.sleep(0.05)
    ostream.stop()
    ostream.close()
    istream.stop()
    istream.close()
    time.sleep(0.2)

    np.save(f"G:/projects/G6/re_analysis/G6Measure/tap_{label}.npy", recorded)
    peak, thdn_db, shift, resid_db = analyze(recorded, freq)
    if verbose:
        print(
            f"[{label}] {freq:5.0f}Hz {dbfs:+4.1f}dBFS -> rec peak {20 * np.log10(peak):7.2f} dBFS | "
            f"THD+N {thdn_db:7.1f} dB | resid-after-fit {resid_db:6.1f} dB"
        )
    return peak, thdn_db


if __name__ == "__main__":
    play_dev = find_g6_playback()
    if play_dev is None:
        print("No G6 playback endpoint found")
        raise SystemExit(1)
    print(
        f"Play -> G6 device {play_dev} (SPDIF Out active) | Rec <- SPDIF In device {REC_DEV} @ {SR}"
    )
    print("PHASE A test: whatever Direct/volume state is CURRENT right now.\n")
    results = {}
    for freq, dbfs, label in [
        (997, 0.0, "A1_997_0dB"),
        (997, -2.0, "A2_997_m2dB"),
        (997, -6.0, "A3_997_m6dB"),
        (1000, 0.0, "A4_1k_0dB"),
        (60, 0.0, "A5_60_0dB"),
        (20, 0.0, "A6_20_0dB"),
        (7000, 0.0, "A7_7k_0dB"),
    ]:
        try:
            results[label] = run_test(freq, dbfs, label, play_dev)
        except Exception as e:
            print(f"[{label}] FAILED: {e}")
    print("\n=== SUMMARY (Phase A: current state) ===")
    print(f"{'label':14s} {'peak dBFS':>10s} {'THD+N dB':>9s}")
    for k, (peak, thd) in sorted(results.items()):
        print(f"{k:14s} {20 * np.log10(peak):10.2f} {thd:9.1f}")
