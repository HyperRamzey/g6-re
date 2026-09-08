"""Dump every property on the G6's render endpoint via the MMDevice COM API.

Pure read: enumerates active render endpoints, opens each device's property
store (STGM_READ), and prints all readable string properties for any endpoint
whose friendly name contains "G6". APO CLSIDs / effect names appear in the FX
property keys — this tells us which host-side effects are actually
instantiated for the G6.
"""

from pycaw.constants import DEVICE_STATE, EDataFlow
from pycaw.pycaw import AudioUtilities


def main() -> int:
    enumerator = AudioUtilities.GetDeviceEnumerator()
    collection = enumerator.EnumAudioEndpoints(EDataFlow.eRender.value, DEVICE_STATE.ACTIVE.value)
    count = collection.GetCount()
    print(f"active render endpoints: {count}")
    for i in range(count):
        dev = collection.Item(i)
        did = str(dev.GetId())
        store = dev.OpenPropertyStore(0)  # STGM_READ
        n = store.GetCount()
        name = ""
        pairs = []
        for j in range(n):
            try:
                pk = store.GetAt(j)
                val = store.GetValue(pk)
            except Exception as exc:  # unreadable PROPVARIANT unions
                print(f"  <skip prop {j}: {type(exc).__name__}>")
                continue
            try:
                v = val.GetValue()
            except Exception as exc:  # some PROPVARIANT unions raise on read
                v = f"<{type(exc).__name__}>"
            key = f"{{{pk.fmtid}}},{pk.pid}"
            if isinstance(v, str):
                if key.endswith(",2"):
                    name = v
                pairs.append((key, v))
        if "G6" not in name:
            continue
        print(f"\n=== {name} ===\n  id: {did}")
        for k, v in sorted(pairs):
            print(f"  {k} = {v!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
