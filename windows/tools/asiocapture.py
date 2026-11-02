"""asiocapture.py - be a minimal ASIO host and record an insert driver's inputs.

The VoiceMeeter insert driver is the only sanctioned tap into the mixer: the
VAIO endpoints have no loopback, the bus record devices stay silent, and the
Remote API's level meters return garbage. But the insert driver hands its
buffers to whoever creates them, so a throwaway ASIO host can read exactly what
VoiceMeeter is sending into an insert.

    python asiocapture.py --seconds 2 --out work\\ins5.f32
    python asiocapture.py --onepass        # passthrough input -> output

Prints per-channel peak/rms so a tone placed on one Windows channel shows up on
exactly one insert channel - which is how the channel order gets pinned down.
"""
import argparse
import ctypes
import os
import sys
import time
import wave

import numpy as np

from asioprobe import (GUID, ASIOChannelInfo, hidden_window, read_clsid,
                       vtable_call, CLSCTX_INPROC_SERVER)

BLOCK = 512

# ASIO sample type of the driver's buffers (see asio.h ASIOSampleType).
ASIOST_FLOAT32LSB = 3
ASIOST_INT32LSB = 2


class ASIOBufferInfo(ctypes.Structure):
    _fields_ = [("isInput", ctypes.c_long),
                ("channelNum", ctypes.c_long),
                ("buffers", ctypes.c_void_p * 2)]


class ASIOTime(ctypes.Structure):
    _fields_ = [("reserved", ctypes.c_long * 4),
                ("timeInfo", ctypes.c_byte * 48),
                ("timeCode", ctypes.c_void_p),
                ("future", ctypes.c_long * 4)]


BUFFERSWITCH = ctypes.WINFUNCTYPE(None, ctypes.c_long, ctypes.c_long)
SRCHANGED = ctypes.WINFUNCTYPE(None, ctypes.c_double)
ASIOMESSAGE = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_long, ctypes.c_long,
                                  ctypes.c_void_p, ctypes.c_void_p)
BUFFERSWITCHTIME = ctypes.WINFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p,
                                      ctypes.c_long, ctypes.c_long)


class ASIOCallbacks(ctypes.Structure):
    _fields_ = [("bufferSwitch", BUFFERSWITCH),
                ("sampleRateDidChange", SRCHANGED),
                ("asioMessage", ASIOMESSAGE),
                ("bufferSwitchTimeInfo", BUFFERSWITCHTIME)]


class Host:
    def __init__(self, name):
        clsid_str, _ = read_clsid(name)
        ole32 = ctypes.WinDLL("ole32")
        ole32.CoInitialize(None)
        guid = GUID()
        if ole32.CLSIDFromString(ctypes.c_wchar_p(clsid_str),
                                 ctypes.byref(guid)) < 0:
            raise SystemExit("bad CLSID")
        self.ptr = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(ctypes.byref(guid), None,
                                    CLSCTX_INPROC_SERVER, ctypes.byref(guid),
                                    ctypes.byref(self.ptr))
        if hr < 0 or not self.ptr:
            raise SystemExit("CoCreateInstance failed 0x%08X" % (hr & 0xFFFFFFFF))
        self.ok = False

    def call(self, index, restype, *argtypes):
        return vtable_call(self.ptr, index, restype, *argtypes)

    def init(self):
        rc = self.call(3, ctypes.c_long, ctypes.c_void_p)(
            self.ptr, ctypes.c_void_p(hidden_window()))
        if rc != 1:
            raise SystemExit("ASIO init failed (%d)" % rc)
        self.ok = True

    def channels(self):
        a, b = ctypes.c_long(), ctypes.c_long()
        self.call(9, ctypes.c_long,
                  ctypes.POINTER(ctypes.c_long),
                  ctypes.POINTER(ctypes.c_long))(self.ptr, ctypes.byref(a),
                                                 ctypes.byref(b))
        return a.value, b.value

    def buffer_size(self):
        mn, mx, pf, gr = (ctypes.c_long() for _ in range(4))
        self.call(11, ctypes.c_long, *(ctypes.POINTER(ctypes.c_long),) * 4)(
            self.ptr, ctypes.byref(mn), ctypes.byref(mx), ctypes.byref(pf),
            ctypes.byref(gr))
        return mn.value, mx.value, pf.value, gr.value

    def channel_info(self, index, is_input):
        info = ASIOChannelInfo()
        info.channel = index
        info.isInput = 1 if is_input else 0
        self.call(18, ctypes.c_long, ctypes.POINTER(ASIOChannelInfo))(
            self.ptr, ctypes.byref(info))
        return info

    def create(self, n_in, n_out, block, cb):
        infos = (ASIOBufferInfo * (n_in + n_out))()
        for i in range(n_in):
            infos[i].isInput = 1
            infos[i].channelNum = i
        for i in range(n_out):
            infos[n_in + i].isInput = 0
            infos[n_in + i].channelNum = i
        rc = self.call(19, ctypes.c_long, ctypes.POINTER(ASIOBufferInfo),
                       ctypes.c_long, ctypes.c_long,
                       ctypes.POINTER(ASIOCallbacks))(
            self.ptr, infos, n_in + n_out, block, ctypes.byref(cb))
        if rc != 0:
            raise SystemExit("createBuffers failed (%d)" % rc)
        return infos

    def start(self):
        self.call(7, ctypes.c_long)(self.ptr)

    def stop(self):
        self.call(8, ctypes.c_long)(self.ptr)

    def dispose(self):
        self.call(20, ctypes.c_long)(self.ptr)

    def release(self):
        self.call(2, ctypes.c_ulong)(self.ptr)


def capture(name, seconds, passthrough, out_path):
    h = Host(name)
    h.init()
    n_in, n_out = h.channels()
    mn, mx, pf, gr = h.buffer_size()
    block = pf if pf else BLOCK
    print("driver  : %s" % name)
    print("channels: %d in / %d out   buffer %d (min %d max %d)" % (n_in, n_out, block, mn, mx))

    blocks = int(np.ceil(seconds * 48000.0 / block))
    buf = np.zeros((n_in, blocks * block), dtype=np.float32)
    state = {"i": 0, "done": False}

    def on_buffer(index, direct):
        if state["done"] or state["i"] >= blocks:
            return
        off = state["i"] * block
        for c in range(n_in):
            src = infos[c].buffers[index]
            if src:
                buf[c, off:off + block] = np.frombuffer(
                    ctypes.string_at(src, block * 4), dtype=np.float32)
        if passthrough:
            for c in range(n_out):
                dst = infos[n_in + c].buffers[index]
                if dst and c < n_in:
                    ctypes.memmove(dst, infos[c].buffers[index], block * 4)
                elif dst:
                    ctypes.memset(dst, 0, block * 4)
        state["i"] += 1
        if state["i"] >= blocks:
            state["done"] = True

    def on_sr(rate):
        pass

    def on_msg(sel, val, msg, opt):
        if sel == 2:      # kAsioEngineVersion
            return 2
        if sel == 1:      # kAsioSupportsTimeInfo
            return 0
        return 0

    def on_time(params, index, direct):
        return None

    cbs = [BUFFERSWITCH(on_buffer), SRCHANGED(on_sr), ASIOMESSAGE(on_msg),
           BUFFERSWITCHTIME(on_time)]
    cb = ASIOCallbacks(*cbs)
    infos = h.create(n_in, n_out, block, cb)

    names = [h.channel_info(c, True).name.decode("latin-1") for c in range(n_in)]

    h.start()
    t0 = time.time()
    while not state["done"] and time.time() - t0 < seconds + 5.0:
        time.sleep(0.02)
    got = state["i"]
    h.stop()
    h.dispose()
    h.release()

    print("captured: %d blocks (%.3f s)" % (got, got * block / 48000.0))
    if got == 0:
        print("no callbacks fired - driver is not running a buffer cycle")
        return None

    data = buf[:, :got * block]
    peaks = np.max(np.abs(data), axis=1)
    rms = np.sqrt(np.mean(data.astype(np.float64) ** 2, axis=1))

    print("\n %2s  %-14s %10s %10s" % ("ch", "name", "peak", "rms"))
    print("-" * 50)
    for c in range(n_in):
        mark = "  <== signal" if peaks[c] > 0.01 else ""
        print(" %2d  %-14s %10.6f %10.6f%s" % (c, names[c], peaks[c], rms[c], mark))

    loud = [c for c in range(n_in) if peaks[c] > 0.01]
    print("\nsignal on: %s" % (", ".join("%d (%s)" % (c, names[c]) for c in loud) or "none"))

    if out_path:
        data.T.astype(np.float32).tofile(out_path)
        print("wrote %s  (%d frames x %d ch)" % (out_path, data.shape[1], n_in))
    return data, names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--driver", default="Voicemeeter Insert Virtual ASIO")
    ap.add_argument("--seconds", type=float, default=2.0)
    ap.add_argument("--onepass", action="store_true", help="copy input to output")
    ap.add_argument("--out")
    args = ap.parse_args()

    r = capture(args.driver, args.seconds, args.onepass, args.out)
    return 0 if r else 1


if __name__ == "__main__":
    sys.exit(main())
