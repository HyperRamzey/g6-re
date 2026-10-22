#!/usr/bin/env python3
"""Feed identical arbitrary signals to the real DLL (Wine) and to the port; compare."""
import os, struct, subprocess, sys, math, random

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("G6CT_TMP", "/tmp/g6ct-sig")
os.makedirs(OUT, exist_ok=True)
N = 4096
# Windows path to the DLL inside the Wine prefix; override with G6CT_DLL.
DLL = os.environ.get("G6CT_DLL", "Z:" + os.path.abspath(os.path.join(HERE, "KSUSBAPO64.dll")).replace("/", "\\"))
ENV = dict(os.environ, WINEPREFIX=os.environ.get("WINEPREFIX", os.path.join(HERE, "prefix")), WINEDEBUG="-all")

def run_case(name, gen):
    random.seed(name)
    data = []
    for k in range(N):
        data.extend(gen(k))
    inp = f"{OUT}/{name}.raw"
    with open(inp, "wb") as f:
        f.write(struct.pack("<%df" % len(data), *data))

    subprocess.run(["wine", os.path.join(HERE, "harness.exe"), DLL, "run", inp,
                    f"{OUT}/{name}.dll.raw"],
                   check=True, env=ENV, cwd=HERE,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run([os.path.join(HERE, "..", "port", "g6ct_cli"), inp,
                    f"{OUT}/{name}.port.raw", str(0x63F)], check=True)

    def rd(p):
        with open(p, "rb") as f:
            b = f.read()
        return struct.unpack("<%df" % (len(b)//4), b)
    d, p = rd(f"{OUT}/{name}.dll.raw"), rd(f"{OUT}/{name}.port.raw")
    assert len(d) == len(p) == N*2
    bad = sum(1 for a,b in zip(d,p) if a != b)
    mx = max((abs(a-b) for a,b in zip(d,p)), default=0.0)
    rms = math.sqrt(sum(v*v for v in d)/len(d))
    print(f"{name:<12} {len(d):>6} samples  rms(dll)={rms:9.5f}  max|err|={mx:.3e}  bit-diffs={bad}")
    return bad, mx

cases = {}
cases["noise_full"] = lambda k: [random.uniform(-1,1) for _ in range(8)]
cases["noise_quiet"] = lambda k: [random.uniform(-1e-6,1e-6) for _ in range(8)]
cases["denormal"]    = lambda k: [random.uniform(-1e-38,1e-38) for _ in range(8)]
cases["dc_offset"]   = lambda k: [0.25,-0.25,0.1,0.5,-0.3,0.3,-0.9,0.9]
cases["sine_all"]    = lambda k: [0.5*math.sin(2*math.pi*f*k/48000.0 + ph)
                                  for f,ph in [(100,0),(440,1),(1000,2),(60,3),(300,4),(700,5),(5000,6),(15000,7)]]
cases["one_sided"]   = lambda k: [1.0,0,0,0,0,0,0,0] if k < 3 else [0]*8
cases["step"]        = lambda k: [0.4]*8

tb = 0; tw = 0.0
for n, g in cases.items():
    b, m = run_case(n, g)
    tb += b; tw = max(tw, m)
print()
print("TOTAL differing samples:", tb)
print("WORST abs error: %.6e" % tw)
print("RESULT:", "PASS - bit-identical" if tb == 0 else "FAIL")
sys.exit(0 if tb == 0 else 1)
