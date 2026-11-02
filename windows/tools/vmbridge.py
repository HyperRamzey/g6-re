"""vmbridge.py - run the Creative MatrixEncoder inside VoiceMeeter's insert.

Why this exists: the Insert ASIO driver always exposes 22 channels and the
7.1 virtual input ("Voicemeeter Input") is group IN#4, i.e. ASIO channels 6..13.
A generic VST host that hands a plugin "the first N inputs" therefore gets
IN#1..IN#4 L/R - the wrong six channels. This host addresses the group
directly.

Signal path:

    app -> Voicemeeter Input (7.1, 8ch/48k)
        -> insert send, ASIO channels 6..13
        -> g6ct (f64) -> binaural
        -> insert return, ASIO channels 6,7 ; channels 8..13 forced to zero
        -> VoiceMeeter strip -> bus A1 -> G733 (2.0, exclusive)

Every other insert channel is passed straight through, so the rest of the
mixer is untouched.

    python vmbridge.py                 # DSP on
    python vmbridge.py --dsp off       # passthrough (A/B)
    python vmbridge.py --seconds 5     # run for a bounded time
"""
import argparse
import ctypes
import os
import sys
import time

import numpy as np

from asiocapture import (ASIOBufferInfo, ASIOCallbacks, BUFFERSWITCH,
                         SRCHANGED, ASIOMESSAGE, BUFFERSWITCHTIME, Host)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DSP = os.path.join(ROOT, "plugin", "g6ct_dsp.dll")

BLOCK = 512
GROUP_OFFSET = 6          # IN#4 Left
GROUP_CH = 8
# VST/ASIO group position -> g6ct channel-bit slot (FL FR FC LFE BL BR SL SR).
# Measured on this machine: group positions 4..7 carry Windows BL BR SL SR,
# even though VoiceMeeter labels them SL SR BL BR.
SLOT = (0, 1, 2, 3, 4, 5, 9, 10)


class Dsp:
    def __init__(self, path):
        lib = ctypes.WinDLL(path)
        lib.g6ct_init.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        lib.g6ct_init.restype = None
        lib.g6ct_reset.argtypes = [ctypes.c_void_p]
        lib.g6ct_process.argtypes = [ctypes.c_void_p,
                                     ctypes.POINTER(ctypes.c_void_p),
                                     ctypes.c_void_p, ctypes.c_void_p,
                                     ctypes.c_size_t]
        lib.g6ct_process.restype = None
        lib.g6ct_precision.restype = ctypes.c_char_p
        self.lib = lib
        # sizeof(g6ct_state) is 8 * sizeof(g6ct_ap2) + mask; 1 KiB is ample.
        self.state = ctypes.create_string_buffer(1024)
        lib.g6ct_init(self.state, 0x63F)
        self.precision = lib.g6ct_precision().decode()

    def reset(self):
        self.lib.g6ct_reset(self.state)


class Bridge:
    def __init__(self, driver, dsp=None, group_offset=GROUP_OFFSET, log=None):
        self.h = Host(driver)
        self.h.init()
        self.n_in, self.n_out = self.h.channels()
        _, _, pref, _ = self.h.buffer_size()
        self.block = pref or BLOCK
        self.off = group_offset
        self.log = log

        if self.n_in < self.off + GROUP_CH or self.n_out < self.off + GROUP_CH:
            raise SystemExit("driver has %d/%d channels, need %d..%d"
                             % (self.n_in, self.n_out, self.off,
                                self.off + GROUP_CH - 1))

        self.dsp = Dsp(dsp) if dsp else None

        self.cin = [(ctypes.c_double * self.block)() for _ in range(GROUP_CH)]
        self.ptrs = (ctypes.c_void_p * 12)()
        if self.dsp:
            for k in range(GROUP_CH):
                self.ptrs[SLOT[k]] = ctypes.cast(self.cin[k], ctypes.c_void_p)
        self.col = (ctypes.c_double * self.block)()
        self.cor = (ctypes.c_double * self.block)()
        self.outf = (ctypes.c_float * self.block)()

        self.blocks = 0
        self.worst = 0.0
        self.overruns = 0

    def _callback(self, index, direct):
        t0 = time.perf_counter()
        n = self.block
        off = self.off

        # 1. straight passthrough for every channel we do not own
        for c in range(self.n_in):
            if off <= c < off + GROUP_CH:
                continue
            src = self.infos[c].buffers[index]
            dst = self.infos[self.n_in + c].buffers[index]
            if src and dst:
                ctypes.memmove(dst, src, n * 4)

        if not self.dsp:
            for c in range(off, off + GROUP_CH):
                src = self.infos[c].buffers[index]
                dst = self.infos[self.n_in + c].buffers[index]
                if src and dst:
                    ctypes.memmove(dst, src, n * 4)
        else:
            # 2. gather the group, convert float32 -> f64
            for k in range(GROUP_CH):
                src = self.infos[off + k].buffers[index]
                view = np.ctypeslib.as_array(self.cin[k])
                if src:
                    np.copyto(view, np.frombuffer(ctypes.string_at(src, n * 4),
                                                  dtype=np.float32))
                else:
                    view.fill(0.0)

            # 3. the matrix, in f64
            self.dsp.lib.g6ct_process(
                self.dsp.state, self.ptrs,
                ctypes.cast(self.col, ctypes.c_void_p),
                ctypes.cast(self.cor, ctypes.c_void_p), n)

            # 4. binaural on the group's L/R, silence on the other six
            for k, buf in ((0, self.col), (1, self.cor)):
                dst = self.infos[self.n_in + off + k].buffers[index]
                if dst:
                    np.copyto(np.ctypeslib.as_array(self.outf),
                              np.ctypeslib.as_array(buf).astype(np.float32))
                    ctypes.memmove(dst, self.outf, n * 4)
            for k in range(2, GROUP_CH):
                dst = self.infos[self.n_in + off + k].buffers[index]
                if dst:
                    ctypes.memset(dst, 0, n * 4)

        dt = time.perf_counter() - t0
        if dt > self.worst:
            self.worst = dt
        budget = n / 48000.0
        if dt > budget:
            self.overruns += 1
        self.blocks += 1

    def run(self, seconds=None, stop_event=None):
        state = {"done": False}

        def on_buffer(index, direct):
            if not state["done"]:
                self._callback(index, direct)

        def on_sr(rate):
            pass

        def on_msg(sel, val, msg, opt):
            return 2 if sel == 2 else 0

        def on_time(params, index, direct):
            return None

        cbs = [BUFFERSWITCH(on_buffer), SRCHANGED(on_sr), ASIOMESSAGE(on_msg),
               BUFFERSWITCHTIME(on_time)]
        cb = ASIOCallbacks(*cbs)
        self.infos = self.h.create(self.n_in, self.n_out, self.block, cb)

        self.h.start()
        t0 = time.time()
        try:
            while True:
                time.sleep(0.1)
                if stop_event is not None and stop_event.is_set():
                    break
                if seconds and time.time() - t0 >= seconds:
                    break
        except KeyboardInterrupt:
            pass
        finally:
            state["done"] = True
            time.sleep(0.05)
            self.h.stop()
            self.h.dispose()
            self.h.release()

    def report(self):
        secs = self.blocks * self.block / 48000.0
        print("blocks   : %d  (%.2f s)" % (self.blocks, secs))
        print("callback : worst %.2f ms of a %.2f ms budget  (%d overruns)"
              % (self.worst * 1000.0, self.block / 48.0, self.overruns))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--driver", default="Voicemeeter Insert Virtual ASIO")
    ap.add_argument("--dsp", default="on", choices=["on", "off"])
    ap.add_argument("--group-offset", type=int, default=GROUP_OFFSET)
    ap.add_argument("--seconds", type=float)
    args = ap.parse_args()

    dsp = DSP if args.dsp == "on" else None
    if dsp and not os.path.exists(dsp):
        raise SystemExit("missing %s - build it with plugin\\build.ps1 --dsp"
                         % dsp)

    b = Bridge(args.driver, dsp, args.group_offset)
    print("driver   : %s  (%d in / %d out, block %d)"
          % (args.driver, b.n_in, b.n_out, b.block))
    if b.dsp:
        print("dsp      : %s  precision %s" % (os.path.basename(DSP), b.dsp.precision))
        print("group    : ASIO %d..%d -> binaural on %d,%d"
              % (b.off, b.off + GROUP_CH - 1, b.off, b.off + 1))
    else:
        print("dsp      : off (passthrough)")
    print("running  : Ctrl-C to stop")
    b.run(args.seconds)
    b.report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
