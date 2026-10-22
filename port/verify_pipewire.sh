#!/usr/bin/env bash
# verify_pipewire.sh - end-to-end check of the G6 MatrixEncoder port.
#
# Plays a known 8-channel signal into the filter-chain sink, records what the
# chain hands to the G6 (the ALSA sink monitor) and compares it sample by
# sample with the reference render of the same code.
#
#   ./verify_pipewire.sh f32    # plugin must be libg6ct_ladspa.so
#   ./verify_pipewire.sh f64    # plugin must be libg6ct_ladspa_f64.so
#
# The hardware sink is muted for the whole run and every sink volume/mute
# state is restored on exit, including on failure.
set -euo pipefail

DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
TMP=${TMP:-/tmp/g6ct-verify}
SINK=g6_ct_downmix
CONF=${CONF:-$HOME/.config/pipewire/pipewire.conf.d/99-g6-ct-downmix.conf}
# Precision under test: "f32" (bit-exact vs the DLL) or "f64".
PREC=${1:-f32}
if [ "$PREC" = f64 ]; then
    CLI="$DIR/g6ct_cli64"; PLUGIN="libg6ct_ladspa_f64.so"
else
    CLI="$DIR/g6ct_cli";   PLUGIN="libg6ct_ladspa.so"
fi
# Hardware sink the filter-chain feeds.  Override with HW=... if yours differs.
HW=${HW:-$(pactl list short sinks | awk '/Sound_BlasterX_G6/ && /pro-output/ {print $2; exit}')}
[ -n "$HW" ] || { echo "FAIL: no G6 sink found; set HW=<sink name>"; exit 1; }
pactl list short sinks | awk '{print $2}' | grep -qx "$SINK" \
    || { echo "FAIL: virtual sink $SINK is not loaded"; exit 1; }
# The hardware sink's monitor is the only tap that carries the chain's 2ch
# output (the virtual node's own monitor exposes its 8ch input).  The hardware
# sink is muted for the whole run, so nothing is audible.
MON=${HW}.monitor
SECS=4

mkdir -p "$TMP"

echo "== building ($PREC) =="
make -C "$DIR" "$(basename "$CLI")" "$PLUGIN" >/dev/null
grep -q "$PLUGIN" "$CONF" 2>/dev/null \
    || { echo "WARNING: $CONF does not load $PLUGIN"; }

echo "== generating stimulus =="
python3 - "$TMP/in8.raw" "$SECS" <<'PY'
import sys, numpy as np
path, secs = sys.argv[1], float(sys.argv[2])
n = int(48000 * secs)
rng = np.random.default_rng(0x6736)
x = rng.standard_normal((n, 8)).astype(np.float32) * 0.05
# a few clean tones so the result is also auditable by ear
t = np.arange(n) / 48000.0
for c, f in enumerate([100, 200, 400, 60, 800, 1200, 1600, 2400]):
    x[:, c] += 0.05 * np.sin(2 * np.pi * f * t).astype(np.float32)
x.tofile(path)
print("wrote", path, x.shape)
PY

echo "== reference render (same code, outside PipeWire) =="
"$CLI" "$TMP/in8.raw" "$TMP/ref2.raw" 0x63F
ls -l "$TMP/ref2.raw"

echo "== saving sink state, hardware output muted =="
HW_MUTE_SAVED=$(pactl get-sink-mute "$HW" 2>/dev/null | awk '{print $2}')
HW_VOL_SAVED=$(pactl get-sink-volume "$HW" 2>/dev/null | grep -o '[0-9]\+%' | tr '\n' ' ')
SINK_MUTE_SAVED=$(pactl get-sink-mute "$SINK" 2>/dev/null | awk '{print $2}')
SINK_VOL_SAVED=$(pactl get-sink-volume "$SINK" 2>/dev/null | grep -o '[0-9]\+%' | tr '\n' ' ')
restore() {
    if [ -n "${SINK_VOL_SAVED:-}" ]; then
        # word splitting is intentional: pactl accepts one volume per channel
        pactl set-sink-volume "$SINK" $SINK_VOL_SAVED 2>/dev/null || true
    fi
    [ -n "${SINK_MUTE_SAVED:-}" ] \
        && pactl set-sink-mute "$SINK" "$SINK_MUTE_SAVED" 2>/dev/null || true
    if [ -n "${HW_VOL_SAVED:-}" ]; then
        pactl set-sink-volume "$HW" $HW_VOL_SAVED 2>/dev/null || true
    fi
    [ -n "${HW_MUTE_SAVED:-}" ] \
        && pactl set-sink-mute "$HW" "$HW_MUTE_SAVED" 2>/dev/null || true
}
trap restore EXIT

pactl set-sink-mute "$HW" 1 || { echo "FAIL: cannot mute $HW"; exit 1; }
pactl set-sink-volume "$SINK" 100% || { echo "FAIL: cannot set $SINK volume"; exit 1; }
pactl set-sink-mute "$SINK" 0 || { echo "FAIL: cannot unmute $SINK"; exit 1; }

echo "== recording + playing =="
rm -f "$TMP/rec2.raw"
timeout --signal=INT $((SECS + 5)) parec -d "$MON" \
    --format=float32le --rate=48000 --channels=2 --raw > "$TMP/rec2.raw" &
REC=$!
sleep 1.5
pw-cat --playback --raw --target "$SINK" --format f32 --rate 48000 --channels 8 "$TMP/in8.raw"
sleep 1.5
wait $REC || true
ls -l "$TMP/rec2.raw"

echo "== compare (must be bit-exact) =="
python3 - "$TMP/rec2.raw" "$TMP/ref2.raw" <<'PY'
import sys, numpy as np
rec = np.fromfile(sys.argv[1], dtype=np.float32).reshape(-1, 2)
ref = np.fromfile(sys.argv[2], dtype=np.float32).reshape(-1, 2)
print("recorded frames", len(rec), "reference frames", len(ref))

# locate the reference inside the recording by cross-correlation on channel 0
a = rec[:, 0].astype(np.float64)
b = ref[:, 0].astype(np.float64)
n = 1 << int(np.ceil(np.log2(len(a) + len(b))))
corr = np.fft.irfft(np.fft.rfft(a, n) * np.conj(np.fft.rfft(b, n)), n)
lag = int(np.argmax(np.abs(corr[: len(a)])))
if lag > len(a) // 2:
    lag -= n
print("lag (frames)", lag)

start = lag
if start < 0:
    ref = ref[-start:]
    start = 0
seg = rec[start:start + len(ref)]
if len(seg) != len(ref):
    print("FAIL: recording too short")
    sys.exit(1)

# skip the first/last 200 ms where the stream ramps in and out
s, e = 9600, len(ref) - 9600
if e <= s:
    print("FAIL: reference too short")
    sys.exit(1)
err = np.abs(seg[s:e] - ref[s:e])
refmax = np.abs(ref[s:e]).max()
print("reference peak %.6f" % refmax)
print("max abs error %.3e   rms error %.3e" % (err.max(), np.sqrt((err ** 2).mean())))
ok = (err.max() == 0.0)
print("PASS (bit-exact)" if ok else "FAIL")
sys.exit(0 if ok else 1)
PY
