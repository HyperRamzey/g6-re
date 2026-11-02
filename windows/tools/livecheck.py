"""livecheck.py - end-to-end null test of the *installed* EqualizerAPO config.

Plays a float32 stimulus through the G733 render endpoint with WASAPI shared
mode, records the endpoint's loopback, and compares the result against the
g6ct CLI reference.

Two device shapes are supported, because the endpoint can be either:

  * 8-channel endpoint (vendor driver): render 8ch, capture 8ch, and the extra
    six channels must be exactly zero.
  * 2-channel endpoint (modded INF): the engine still accepts a 7.1 *stream*
    (verified: IAudioClient::IsFormatSupported(shared, 7.1) -> S_OK), so the
    stimulus is 8ch while the capture is 2ch. EqualizerAPO's SFX slot runs on
    the stream format, so the matrix still sees all eight channels; the audio
    engine then converts 8->2 for the device. Only the front pair exists to
    compare against, and the 8->2 conversion may contribute a flat gain, which
    is reported separately.

  python livecheck.py --stim work/stim8.f32 --ref work/ref_f32.raw \
                      --out work/live.f32 [--render-ch 8] [--gain 1.0]

Exit code is 0 only if the front pair reaches 90 dB against the reference.
"""
import argparse
import threading
import time

import numpy as np
import pyaudiowpatch as pa


def find_devices(p, name_substr="Logitech G733"):
    """Return (render_info, loopback_info) for the matching endpoint."""
    render = loopback = None
    wasapi = p.get_host_api_info_by_type(pa.paWASAPI)["index"]
    for d in p.get_device_info_generator():
        if d.get("hostApi") != wasapi or name_substr not in d["name"]:
            continue
        if d["maxOutputChannels"] >= 2 and d.get("isLoopbackDevice") is not True:
            render = d
    for d in p.get_loopback_device_info_generator():
        if name_substr in d["name"]:
            loopback = d
    if render is None or loopback is None:
        raise SystemExit("cannot find both render and loopback for %r" % name_substr)
    return render, loopback


def best_lag(ref, cap, max_lag=None):
    """Sample offset of `cap` relative to `ref`, via FFT correlation."""
    n = len(ref) + len(cap)
    size = 1 << int(np.ceil(np.log2(n)))
    corr = np.fft.irfft(np.fft.rfft(cap, size) * np.conj(np.fft.rfft(ref, size)), size)
    if max_lag is not None:
        lo, hi = 0, min(size, max_lag)
        tail = slice(max(0, size - max_lag), size)
        peak_fwd = int(np.argmax(corr[lo:hi]))
        peak_back = int(np.argmax(corr[tail])) - max_lag
        fwd_val = float(corr[peak_fwd])
        back_val = float(corr[size - max_lag + int(np.argmax(corr[tail]))])
        return peak_fwd if fwd_val >= back_val else peak_back
    k = int(np.argmax(corr))
    return k - size if k > size // 2 else k


def record(render_dev, loop_dev, stim, rate, out_ch, in_ch,
           preroll=0.25, tail=0.6, chunk=480):
    """Play `stim` (frames x out_ch) and capture the loopback at in_ch."""
    p = pa.PyAudio()
    try:
        rin = p.open(format=pa.paFloat32, channels=in_ch, rate=rate, input=True,
                     input_device_index=loop_dev["index"],
                     frames_per_buffer=chunk)
        rout = p.open(format=pa.paFloat32, channels=out_ch, rate=rate, output=True,
                      output_device_index=render_dev["index"],
                      frames_per_buffer=chunk)
    except Exception:
        p.terminate()
        raise

    zero_out = np.zeros((chunk, out_ch), dtype=np.float32)
    blocks = [zero_out] * int(round(preroll * rate / chunk))
    for i in range(0, len(stim), chunk):
        blk = stim[i:i + chunk]
        if len(blk) < chunk:
            blk = np.vstack([blk, np.zeros((chunk - len(blk), out_ch), np.float32)])
        blocks.append(np.ascontiguousarray(blk, dtype=np.float32))
    blocks += [zero_out] * int(round(tail * rate / chunk))

    captured = []
    error = []

    def pump():
        try:
            for blk in blocks:
                rout.write(blk.tobytes(), exception_on_underflow=False)
        except Exception as e:  # noqa: BLE001 - surfaced below
            error.append(e)

    try:
        rin.start_stream()
        rout.start_stream()
        time.sleep(0.05)
        t = threading.Thread(target=pump, daemon=True)
        t.start()
        while t.is_alive():
            captured.append(rin.read(chunk, exception_on_overflow=False))
        time.sleep(0.25)
        while True:
            got = rin.read(chunk, exception_on_overflow=False)
            if not got:
                break
            captured.append(got)
            if sum(len(x) for x in captured) > (len(blocks) + 200) * chunk * 4 // in_ch:
                break
    finally:
        rout.stop_stream()
        rin.stop_stream()
        rout.close()
        rin.close()
        p.terminate()

    if error:
        raise error[0]
    raw = b"".join(captured)
    return np.frombuffer(raw, dtype=np.float32).reshape(-1, in_ch).copy()


def stats(ref, test, label, quiet=False):
    err = test - ref
    rms_ref = float(np.sqrt(np.mean(ref.astype(np.float64) ** 2)))
    rms_err = float(np.sqrt(np.mean(err.astype(np.float64) ** 2)))
    peak_err = float(np.max(np.abs(err))) if len(err) else 0.0
    snr = 20.0 * np.log10(rms_ref / rms_err) if rms_err > 0 else float("inf")
    ident = int(np.sum(test.view(np.uint32) == ref.view(np.uint32)))
    if not quiet:
        print("    %-6s peak_ref %8.6f  rms_err %.3e  SNR %8.2f dB  "
              "max_err %.3e (%7.4f LSB16)  bit-identical %d/%d"
              % (label, float(np.max(np.abs(ref))), rms_err, snr, peak_err,
                 peak_err * 32768.0, ident, len(ref)))
    return dict(snr=snr, rms_err=rms_err, peak_err=peak_err, ident=ident, n=len(ref))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stim", required=True, help="raw f32 stimulus, interleaved")
    ap.add_argument("--ref", required=True, help="raw f32 g6ct_cli reference, 2ch")
    ap.add_argument("--out", required=True, help="capture destination, raw f32")
    ap.add_argument("--name", default="Logitech G733")
    ap.add_argument("--render-ch", type=int, default=None,
                    help="stream channels to request (default: device channels)")
    ap.add_argument("--preroll", type=float, default=0.25)
    ap.add_argument("--tail", type=float, default=0.60)
    ap.add_argument("--dry-run", action="store_true",
                    help="capture without playing, to measure the noise floor")
    args = ap.parse_args()

    ref2 = np.fromfile(args.ref, dtype=np.float32)
    if ref2.size % 2:
        raise SystemExit("reference must be interleaved 2ch float32")
    ref2 = ref2.reshape(-1, 2)

    p = pa.PyAudio()
    try:
        render_dev, loop_dev = find_devices(p, args.name)
    finally:
        p.terminate()

    dev_ch = int(render_dev["maxOutputChannels"])
    out_ch = args.render_ch or dev_ch
    in_ch = int(loop_dev["maxInputChannels"])
    rate = int(render_dev["defaultSampleRate"])
    print("render  : idx %-3d %dch device, requesting %dch  %dHz  %s"
          % (render_dev["index"], dev_ch, out_ch, rate, render_dev["name"]))
    print("loopback: idx %-3d %dch  %s"
          % (loop_dev["index"], in_ch, loop_dev["name"]))

    stim = np.fromfile(args.stim, dtype=np.float32)
    if stim.size % out_ch:
        raise SystemExit("stimulus is not a whole number of %dch frames" % out_ch)
    stim = stim.reshape(-1, out_ch)
    print("stimulus: %d frames (%.3f s), peak %.6f"
          % (len(stim), len(stim) / rate, float(np.max(np.abs(stim)))))

    if args.dry_run:
        stim = np.zeros_like(stim)

    cap = record(render_dev, loop_dev, stim, rate, out_ch, in_ch,
                 preroll=args.preroll, tail=args.tail)
    cap.astype(np.float32).tofile(args.out)
    print("captured: %d frames (%.3f s) -> %s" % (len(cap), len(cap) / rate, args.out))

    lag = best_lag(ref2[:, 0], cap[:, 0], max_lag=rate // 2)
    print("\nalignment: capture starts %+d samples after the reference" % lag)

    n = min(len(ref2), max(0, len(cap) - lag))
    if n <= 0:
        raise SystemExit("capture too short after alignment")
    print("comparing %d frames\n" % n)
    aligned = cap[lag:lag + n]

    front = []
    for c in range(min(in_ch, 2)):
        front.append(stats(ref2[:n, c], aligned[:, c], "ch%d" % (c + 1)))
    rest = []
    for c in range(2, in_ch):
        rest.append(stats(np.zeros(n, np.float32), aligned[:, c], "ch%d" % (c + 1)))

    print()
    if rest:
        print("extra channels: worst residual %.3e (%.4f LSB16)"
              % (max(r["rms_err"] for r in rest),
                 max(r["peak_err"] for r in rest) * 32768.0))

    # A flat gain between the reference and the capture is the engine's own
    # 8->2 conversion; report it rather than hiding it inside the SNR.
    print("=== gain between reference and capture ===")
    gains = []
    for c in range(len(front)):
        a = ref2[:n, c].astype(np.float64)
        b = aligned[:, c].astype(np.float64)
        g = float(np.dot(a, b) / np.dot(a, a))
        e = b - g * a
        q = float(np.sqrt(np.mean(e ** 2)))
        r = float(np.sqrt(np.mean(a ** 2)))
        snr = 20 * np.log10(r * abs(g) / q) if q > 0 else float("inf")
        gains.append(g)
        print("  ch%d  gain %.9f  SNR after gain %8.2f dB  max_err %.3e"
              % (c + 1, g, snr, float(np.max(np.abs(e)))))
    print("  spread between channels: %.3e" % (max(gains) - min(gains)))

    print()
    worst = min(r["snr"] for r in front)
    print("front pair: worst SNR %.2f dB, worst max_err %.4f LSB16"
          % (worst, max(r["peak_err"] for r in front) * 32768.0))
    if rest:
        print("ch3..ch%d  : worst residual %.3e (%.4f LSB16)"
              % (in_ch, max(r["rms_err"] for r in rest),
                 max(r["peak_err"] for r in rest) * 32768.0))
        ok = worst >= 90.0 and max(r["peak_err"] for r in rest) <= 1e-5
    else:
        ok = worst >= 90.0
    print("\n%s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
