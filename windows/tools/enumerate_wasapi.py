"""enumerate_wasapi.py - list WASAPI render + loopback devices with formats."""
import json

import pyaudiowpatch as pa

p = pa.PyAudio()
try:
    ha = p.get_host_api_info_by_type(pa.paWASAPI)
    print("WASAPI host api index %d: %s" % (ha["index"], ha["name"]))

    print("\n=== WASAPI devices ===")
    for d in p.get_device_info_generator():
        if d.get("hostApi") != ha["index"]:
            continue
        print("  idx %-3d in=%-2d out=%-2d rate=%-6.0f  %s"
              % (d["index"], d["maxInputChannels"], d["maxOutputChannels"],
                 d["defaultSampleRate"], d["name"]))

    print("\n=== loopback devices ===")
    for d in p.get_loopback_device_info_generator():
        print("  idx %-3d in=%-2d rate=%-6.0f  %s"
              % (d["index"], d["maxInputChannels"], d["defaultSampleRate"], d["name"]))
        print("      " + json.dumps({k: v for k, v in d.items()
                                     if k not in ("name",)}, default=str))

    try:
        d = p.get_default_wasapi_loopback()
        print("\ndefault loopback: idx %d in=%d rate=%.0f %s"
              % (d["index"], d["maxInputChannels"], d["defaultSampleRate"], d["name"]))
    except Exception as e:
        print("\ndefault loopback: %s" % e)
finally:
    p.terminate()
