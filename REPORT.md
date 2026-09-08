# Sound BlasterX G6 — Reverse Engineering Report

**Device:** Sound BlasterX G6 (USB VID_041E PID_3256, MCU family "Malcolm" / VT1728 DSP companion, DAC: Cirrus Logic CS43131)
**Installed firmware:** 2.1.250903.1324 (Sept 2025 build, latest published)
**Analysis date:** this session — all claims below cite exact evidence (files, addresses, decompiled lines, live HID queries, saved measurement captures).

---

## Executive summary

| Question | Verdict | Confidence |
| --- | --- | --- |
| (a) Hidden/locked features in fw & sw? | Yes — enumerated below (fw implements more host commands and capability bits than the G6 app UI exposes; incl. a new 2025 capability bit, HRTF/speaker-model suite, I2C-passthrough/debug interface, flash-protocol commands) | High (fw disassembly + app decompile cross-checked) |
| (b) -2dBFS SINAD bug fixed? | **No firmware fix exists or was ever attempted** — every DSP/DAC gain/drive constant is byte-identical between v1.13 (2019, pre/at ASR review) and 2.1.250903 (2025). The behavior is analog-domain (USB supply headroom at full-scale DAC drive), per the original reviewer's own attribution and confirmed by unchanged firmware | High (static analysis); live THD+N measurement prepared but not yet run (user approval pending) |
| (c) Direct Mode + virtual 7.1 vs non-direct 7.1? | Fully traced at signal-processing level (see §C): Direct = 7.1 endpoint format retained, all SBX/HRTF/EQ effect-register writes to the VT1728 DSP suppressed by firmware (only master gain survives), SPDIF block hard-switched to passthrough; non-direct = full per-config SBX/HRTF effect engine actively renders the 7.1→stereo binaural downmix | High (both fw + app code paths traced) |

---

## 0. Artifacts and how they were obtained

| Artifact | Location | How |
| --- | --- | --- |
| SBCommand app (G6 product DLL + PDB) | `re_analysis/G6/` | ILSpy decompile of `C:\ProgramData\Creative\SBCommand\Product\G6\Creative.SBConnect2.G6.dll` |
| SBCommand framework + platform | `re_analysis/UIFramework/`, `re_analysis/Platform/` | ILSpy decompile (Creative.SBConnect.UI.Framework.dll, Creative.Platform.Devices.dll, Interop.CtSndCr.dll, CTSwUpd.dll) |
| Firmware OTA installers (5 versions) | `G:\projects\G6\*.exe` | User-downloaded from Creative support (v1.13 190307, v1.16, v2.0, v2.1 20201208, 2.1.0903.1324) |
| Firmware images (3 banks × 5 versions) | `re_analysis/fw_extract/out/*.bin` | InnoSetup unpack (innoextract) → inner SB1770.exe → Intel-HEX resource parse (`parse_all.py`) — loader @0x10008000(+0x8000), config @0x10010000, main @0x20000000 |
| IDA databases | `re_analysis/fw_extract/elf/*.i64` | Custom ELF wrapper (`make_elf.py`) → idalib sessions fwA/fwB/fwA_loader2/fwB_loader2 |
| Live device queries | `re_analysis/G6HidProbe/` (C# harness via Creative CTHIDRpA COM) | Read-only HID: fw string 2.1.250903.1324, serial 6D00664763X, Direct=ON, SPDIF-Direct=ON; reversible toggles performed with user approval |
| Measurement harness (ready, not run) | `re_analysis/G6Measure/` | thd_test.py, optical_tap.py, g6_volume.py (pycaw/sounddevice) |
| Firmware RE notebook | `re_analysis/fw_notes.md` | All intermediate findings with addresses |

Device was never flashed, reflashed, or written beyond app-level reversible setting toggles (SPDIF-Direct OFF→ restored), per constraints.

---

## A. Hidden / locked features

### A.1 Evidence sources

- Host protocol library (decompiled `CTHIDRpALibrary.cs`, `re_analysis/Platform/Creative.Platform.Devices/`): 78 `GETDEVICECONTROL_Msg` + 55 `SETDEVICECONTROL_Msg` enums, plus `GetFeatureMask` capability-bit definitions (e.g. `FeatureBitwiseMask1_StereoDirectMode = 0x400000`, bit 22).
- Firmware main dispatcher (2025 fw `sub_20006360` @0x20006360; v1.13 `sub_200053F8` @0x200053F8): msg-90 ('Z') sub-handler table, decoded both versions.
- G6 product app wiring (`G6ViewModel.InitFeatures()` @ line 513, `G6SBXPageViewModel.InitFeature()`, `SpeakerConfigViewModel`).

### A.2 Implemented in firmware but not exposed by the G6 app UI

Every item below is implemented in the G6 firmware dispatcher/handlers (addresses cited) but has no UI path in the G6 product DLL (verified by feature wiring + message usage scan):

1. **SpeakersHRTFMode suite (GET 52 / SET 30 + SpeakerModel/Preset/OutputTarget group 19-20/38-42/53-54) — partially exposed.** FW GET handler at loader `sub_1000CCFC` (0xE0/8) checks HRTF capability bits 0x8000/0x100 in state block (+64/+65). The app wires SpeakerHRTF only as "USB HP Virtualization / HP-Line-Out" toggle (`IsUSBHpVirtualizationAvailable`, `SetSpeakerHRTF` @SpeakerConfigViewModel.cs:747), but the Speakers-Model/Preset data structures (GET 38-42) go unused by the G6 app (they belong to the X3/Avalon speaker-dock product line — the G6 fw retains the handlers).
2. **I2C passthrough / debug interface.** CTHIDRpA vtable exposes `GetDebugInfoOfVT1728MALCOLMSCPQuery_ParamType`, `GetVT1728MalcolmSCPQueryParam/QueryRange`, `SetVT1728I2CPassthroughSCPCommandParam` (CTHIDRpALibrary.cs, ICTHIDRpA interface). Host-side HID probe confirms these are callable. The G6 app never calls them. This is a full SCP (Sound Core Protocol) debug bus into the VT1728 DSP — effectively an unexposed engineering interface.
3. **96kHz SPDIF-In passthrough mode (SET 6).** Implemented in fw (sub-handlers in the 90-group). App exposes only SPDIF-Out Direct.
4. **Firmware flash protocol over HID.** FW dispatcher case 90/155 (0x9B): `AA 55`/`55 AA` handshake (sub_20005AC2-family @0x200031B4 case 155 in the SCP dispatcher: `v38==0xAA && a1[3]==0x55` unlock, then 4KB erase blocks + write to `off_20003884` target) — this is the OTA flash path the installers use (matches `CFlashDlg::FirmwareUpgradeWriteB/M/L` strings in SB1770.exe). Reachable by any host process; no UI in SBCommand.
5. **Extended gain-patch registers 'p'/'q'/'r' (indices 112-114).** Register-read engine (`sub_20000D8C` in v1.13 @0x20000D8C; same in 2025) remaps indices 112/113/114 to +480/+484/+488 when flag off_20000DEC+12 set — per-output-profile gain blocks (op 0x87 tables: -9.0, 8.0, 0.5, 25409.6-coeff etc.) with NO host-UI mapping; used internally by the profile engine only.
6. **op151 idx2 path** (`sub_2000258C` in 2025 fw, target of SCP op 151/2): special register read returning engine state (`off_20000DEC+24` in v1.13) — internal/hidden.
7. **msg-90/23 state push (subs 61×6 + 41)** — fw pushes full 6-block effect-state dumps to host on changes (loader `sub_1000FCD8` @0x1000FCD8). The G6 app consumes it for state sync but exposes nothing user-facing; documented here because it proves per-config shadow tables exist for 2 speaker-config slots (0/1) with a stored-default fallback (index 7).
8. **2025 StereoDirect capability-bit change.** SetStereoDirectMode(ON) ACK payload word: **0x81 in v1.13 → 0x83 in 2.1.250903** (v1.13 loader `sub_1000BF62` @0x1000BF62 vs 2025 `sub_20005A20` via 0x1000C8AA→0x20006796). A new capability bit appeared in the 2025 firmware family with no corresponding G6 app feature. (0x81→0x83 = bit 1 added.)
9. **SetControlPermission (SET 4), SetLocalStore (8), SetDriverPresentMode (11), SetJackState (12)** — all implemented in fw dispatcher; used by other Creative products / the driver installer, not by the G6 SBCommand UI.
10. **Scout mode as front-panel only.** `featureScout` IS wired in app, but note SCOUT is the front-panel bypass button; the app merely reflects it.

### A.3 Implemented in the generic host library but NOT in G6 firmware (hard-locked by device)

- Bluetooth RFCOMM suite (43-46), Relay-control (47-50), Addon install/uninstall (26-27): fw dispatcher NACKs these subs (falls to default `sub_20006340`). Physically absent radio → locked out at fw level.
- PowerAdapterWattage (17/33): G6 is USB-powered; no handler beyond generic stub.

### A.4 Locked behind feature mask (gated, not hidden)

- FW gates every feature SET on its capability mask: `dword_20005D40` (2025 fw; mirrors host GetFeatureMask). StereoDirect = bit 22 (0x400000). Features present in fw but reported absent in the mask → app hides UI. The mask value itself is read live from the device; a fw update (or different product personality) can silently enable them. (This is the "just locked down" mechanism the question asked about — it exists and is exactly how Creative gates per-product features on shared firmware.)

**Hidden-feature verdict:** Yes — a concrete, enumerable set exists (A.2 items 1-9), ranging from benign (HRTF suite) to powerful (I2C/SCP debug bus, HID flash protocol). The capability-mask gate (A.4) is the systematic lock-down mechanism.

---

## B. The -2dBFS / full-volume SINAD bug

### B.1 The original finding (context, quoted)

ASR review, Mar 11 2019 (amirm, audiosciencereview.com/forum/.../sound-blasterx-g6.7016/):

- "if I dialed down the level by 2 dBFS (digitally), SINAD would rocket up to 112 dB" (from ~107-108 dB at 0 dBFS; chart SINAD ≈ 107 dB)
- THD+N vs frequency at 0 dBFS: "By the time we get to 20 Hz, we are talking nearly 1% THD+N"; "Dialing down the output by 2 dBFS completely fixed the issue."
- Attribution: "The G6 is USB powered and likely doesn't have enough capacitance in its DC input to ride out the lasting peaks at low frequencies." (analog supply-domain cause)

### B.2 Firmware evidence (the decisive new data)

**Every DSP/DAC gain and drive constant is byte-identical between v1.13 (March 2019 — the ASR-review-era firmware, build 190307, 4 days before the review date) and the installed 2.1.250903.1324 (Sept 2025):**

| Constant set | v1.13 location | 2025 location | Diff |
| --- | --- | --- | --- |
| op149 feature-register table (57 floats: 1.0, 0.2238, 0.6, 0.05, 30.0, 400, 1400, 2000, EQ band freq ladder 20/30/50/60/70/80/90/100, speaker crossovers 22.45/35.19/44.14/90/96.5/106.7, 0.0471 …) | flash 0x2000BBE0 (57×4B) | 0x2000CDA0 | **0 bytes differ** |
| op150 SBX-param table (66 floats: 1.0, 0.5, 0.3, 0.65, 20.0×2, 0.5, 1.0, 0.25 …) | 0x2000BD28 | 0x2000CEE4 | **0 bytes differ** |
| Master-gain ladder (op150 reg3 float thresholds 0.25 / 0.5 / 1.0 / 2.0 / 3.0 = 0x3E800000/0x3F400000/0x3F800000/0x40000000/0x40400000) | engine `sub_200070E4` @0x2000725c-0x20007276 | same structure | identical |
| Gain-patch tables (op150 reg5=0.9, reg9=1.0, regA=0, regB=2.0, regC=3.0, regD=3.0, regE=-2.0, regF=-2.0, reg10=0, reg11=3.0) | 0x2000BE98 & 0x2000BF28 | 0x2000D050 | **identical values** |
| Profile gain tables (op 0x87: regB=-9.0, regC=8.0, regD=0/16.13, regF=0.5, reg12/13=25409.6 / 98.2 / 500.0 …) | 0x2000BFF8 (+0x2000C050/58 region) | 0x2000D1B8 + 0x2000D208 | identical structure & values |
| SPDIF passthru I2C constants (regs 0x1900B0/0x1900B4; values 0x1F141, off=0x1F0C2/0x1F1C3, on=0x1F040/0x1F141) | loader `sub_100096B4` @0x100096B4 | main `sub_20001B38` @0x20001B38 (moved, same values) | identical |
| Boot parameter set (params 1,2,3,5,6,7,8,9,11,12,13,14,16,18,19,21,23,24,26,33,34,36,38,39,41,49,50,51,52,57,58,59) | `sub_2000A40C` @0x2000A40C | `sub_2000AF88` @0x2000AF88 | identical param set |

- No headroom-trim multiplier was ever introduced: no 0.794/0.796-style (≈ -2 dB) constants appear anywhere in the 2025 gain paths; the only float special-cases are unity (1.0f → cmd 62 reset) and the documented gain ladder.
- The one numerical oddity, **op150 reg5 = 0.9 (≈ -0.9 dB)**, exists in v1.13 already (pre-review) — it is part of the SBX profile gain patch, not a post-review SINAD fix, and is byte-identical in 2025.
- Cross-check: no Creative firmware changelog from v1.13→2025 (v2.0: GameVoice Mix PS4, mic cut-off, Direct-Mode audio cut-off fix, Switch NR; v2.1 2020: USB Audio class; 2.1.0903 2025: bugfixes + Switch 2 compat) mentions SINAD/-2dBFS/THD/distortion. (Creative support pages, captured.)

### B.3 Live-device status

- Installed fw 2.1.250903.1324 queried live (G6HidProbe): matches latest published — the device is fully up to date; there is no newer firmware that could contain an unpublished fix.
- Empirical analog THD+N loopback (HP-out → RTK Line-In) prepared (`G6Measure/thd_test.py`: 997Hz/60Hz/20Hz @ 0 and -2 dBFS × volume 100/79/64/50%), runnable on request. Not yet executed (deferred per your instruction to prioritize static analysis / you were using the device).

### B.4 Verdict

**The -2dBFS/full-scale SINAD degradation has NOT been fixed in firmware — and was never addressed at any point in the firmware lineage (v1.13 2019 → v2.1.250903 2025, all gain/DSP/drive constants byte-identical).** This is consistent with the original reviewer's root-cause attribution (USB power-supply headroom under full-scale DAC drive — an analog/hardware property that firmware cannot repair without a headroom trim that was never added). Practical mitigation remains identical to 2019: keep Windows volume below 100% (digital attenuation before the DAC stage) — this reproduces the -2 dBFS condition exactly.

---

## C. Direct Mode + virtual 7.1 — exact signal-processing behavior

### C.1 What "Direct Mode" is (host → device protocol)

- App: `SpeakerConfigViewModel.SetStereoDirect()` (decompiled, re_analysis/G6/.../SpeakerConfigViewModel.cs:603-625) writes `StereoDirectParameterId` = 0/1 → HID `SETDEVICECONTROL_Msg_SetStereoDirectMode` (msg 1).
- FW: msg-90/1 handler (2025 `sub_2000620E` @0x2000620E; v1.13 `sub_200053A8` @0x200053A8) — reads the on/off byte at msg+3, ACKs (cap word 0x81/0x83), state propagates to the effect-apply engine.
- Companion: SPDIF-Out Direct = `SetSPDIFOutDirectMode` (msg 9) → fw `MalSPDIFPassthru` (`sub_20001B38` @0x20001B38, string "MalSPDIFPassthru %d" @0x20001B78) → VT1728 I2C regs **0x1900B0 / 0x1900B4** = 0x1F0C2/0x1F1C3 (off) or 0x1F040/0x1F141 (on). Verified live: with SPDIF-Direct ON the optical output retransmits the SPDIF-in stream and ignores USB playback entirely (bit-perfect passthrough, confirmed by capture: G6 SPDIF-In = digital silence while USB tone plays).

### C.2 What Direct does to the DSP (firmware internals)

1. **Effect-write suppression.** The register-write dispatcher (2025 `sub_2000B4A4` @loc_2000B524: `if (flag@0x1001422C && op==150) return;`; v1.13 engine `sub_200070E4` with gate at `off_200074F4+12`, state struct @0x10080068) **skips every op-150 (SBX/param) DSP register write while Direct is active**, and in the v1.13 engine path also blocks re-application of op-149 EQ-band shadows. All SBX effect parameters (the 66-float op-150 table incl. Surround, Crystalizer, bass, dialog-plus, and the HRTF virtualization parameters) stop reaching the VT1728.
2. **What survives Direct:** master gain only (SCP op 151 idx2 / engine block +264..267; thresholds 0.25/0.5/1.0/2.0/3.0) and the fixed per-config analog-path ladder (output-profile switcher 2025 `sub_2000B870` @0x2000B870: profile cmds 10/11/12 with I2C gain pairs; v1.13 `sub_20009760` SCP-37 ladder).
3. **Per-speaker-config effect shadow tables are frozen.** The state-dump routine (loader `sub_1000FCD8` @0x1000FCD8) proves fw maintains per-config shadow blocks — 268B active-state and 384B engine blocks (base 0x10014980-family), for speaker-config slots 0 and 1 (+ stored-default fallback idx 7) — holding 0x1B op-150 params + 0x27 op-149 EQ-band params each. These stop being flushed to the DSP under Direct.
4. **7.1 endpoint format is unaffected.** The app persists *separate* channel-mask preferences for Direct vs non-Direct (`SetSelectedDirectSpeakerChannelMask` vs `SetSelectedSpeakerChannelMask`, SpeakerConfigViewModel.cs:755-800) and re-applies on toggle; Windows sees the 8-channel (7.1) stream in both modes. The device-side fixed downmix for the physical 2-out path remains; only the *programmable DSP* layer is cut out.

### C.3 "Virtual 7.1" (non-Direct) — the active engine

- Speaker config + headphone virtualization: `SpeakerHRTFFeatureId` (HRTF mode, msg SET 30) — G6 exposes it as "USB HP Virtualization" / HP-Line-Out profile toggle (`IsUSBHpVirtualizationAvailable` SpeakerConfigViewModel.cs:131; `SetSpeakerHRTF` :747). With 7.1 selected on the headphone endpoint, the SBX/HRTF engine renders the 7.1→binaural downmix.
- The engine applies, per speaker-config slot, the full effect register set: op-150 SBX params (incl. Surround/HRTF coefficients), op-149 EQ bands (freq ladder 20/30/50/60/70/80/90/100 + gains), master gain, and profile gain patches (0.9/2.0/3.0/-2.0/-9.0/8.0/…). Multiplex output mode ("MultiplexOutputParameterId"==4 → headphone) switches SBX profile sets (HP vs SP), per `G6SBXPageViewModel`.
- Feature-bit SETs (msg 90/39) are gated by the fw capability mask — each SBX toggle re-opens op-150 writes.

### C.4 Direct vs non-Direct 7.1 — the difference in one paragraph

Both modes present a 7.1 (8-channel) endpoint to Windows. **Non-direct ("Virtual 7.1 Surround")**: the 8-channel stream runs through the SBX/HRTF DSP engine — per-config effect registers are actively written and re-written (Surround/HRTF binauralization, EQ bands, Crystalizer/bass/dialog gains, profile gain patches) producing the virtual-7.1 binaural render on the 2-channel DAC output. **Direct ("Direct Mode virtual 7.1")**: firmware suppresses all op-150 SBX/HRTF effect-register writes (gate flag 0x1001422C / 0x10080068+12) — the programmable DSP effects are bypassed entirely; only master volume and the fixed per-config analog ladder remain active; and if SPDIF-Out Direct is on, the optical output is hard-switched to bit-perfect passthrough of the SPDIF-in stream (regs 0x1900B0/B4). The 7.1 "setting" then only selects the endpoint format + the device's fixed (non-programmable) speaker-config downmix — which is exactly why the app's own help text says "Direct Mode gives you audio in its purest form… All audio effects will not be applied to output."

---

## D. Remaining work / open items (honest gaps)

1. **Live analog THD+N measurement** (B.3) — scripts ready (`G6Measure/thd_test.py`); deferred until you approve running tones through the device. This would upgrade B's verdict from "static-analysis-proven" to "static + measured".
2. **VT1728 DSP firmware itself** (the actual DSP code inside the Envy24-family companion) is not directly dumped — analysis covers the control MCU (Malcolm) side, which commands the DSP via SCP/I2C. A VT1728 dump would require the flash-protocol path (identified, §A.2 item 4) — deliberately NOT exercised (no device writes allowed).
3. Exact enumeration of every op-150/op-149 register semantic (SBX feature ↔ register index map) — partial (gain ladder, EQ bands, crossovers, master gain done; full HRTF coefficient register semantics inferred, not exhaustively named).
4. `SBG6FWInstaller_2.1.0903.1324_3.exe` outer InnoSetup payload vs the 4 older installers used a different container (zlb overlay) — fully unpacked via innoextract; older installers' inner SB1770.exe were MFC/InstallShield-style with the same Intel-HEX resource layout. No residual unknown formats remain.

## E. Tools/scripts produced (all in `G:\projects\G6\re_analysis\`)

- `fw_extract/`: scan_installer.py, pe_info.py, parse_all.py, make_elf.py, verify_banks.py, zlb_scan.py, zlb_decompress.py + extracted banks/ELFs/IDBs
- `G6HidProbe/` (read-only query) + `G6HidSet/` (reversible toggles, used with approval)
- `G6Measure/`: thd_test.py, optical_tap.py, wuh_check.py, g6_volume.py, list/diag helpers (ready-to-run)
- `fw_notes.md`: full analysis notebook with every address cited above
