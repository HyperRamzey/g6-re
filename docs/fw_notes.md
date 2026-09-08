# G6 Firmware RE — analysis notebook v4 (running)

## Sessions

- fwA = v1.13 (190307) main @0x20000000 | fwA_loader2 = its loader bank @0x10008000
- fwB = v2.1.250903.1324 main @0x20000000 | fwB_loader = its loader @0x10008000
- IDBs saved for fwA/fwB mains.

## Host-message table DECODED (both fw versions, structurally identical)

Main dispatcher: fwB `sub_20006360` / fwA `sub_200053F8` — msg byte0=90 ('Z') switch on byte1:

- **90/1 = SETDEVICECONTROL Msg 1 = SetStereoDirectMode** → fwB `sub_2000620E` / fwA `sub_200053A8`
  - Both read on/off byte at msg+3, build ACK reply:
    - v1.13 reply → `sub_1000BF62`: payload word @+4 = **129 (0x81)**
    - 2025 fw reply → `sub_20005A20` via 0x1000C8AA→0x20006796: payload word @+4 = **131 (0x83)**
  - ⇒ StereoDirect protocol unchanged; capability-notify value changed 0x81→0x83 (extra bit set in 2025 fw).
- 90/2, 90/3 = other SETDEVICECONTROL msgs (master vol etc.)
- 90/39('9') = feature-bit SET handler (fwB sub_20005B70 vs fwA sub_20005014) — the feature-mask gate
- 90/22(0x16) case in fwA sub_20004F38 vs fwB sub_20004E38-family = audio-path state machines
- 90/0xE0(224)/sub-1..9 = GET variants (versions, serial, feature mask...)
- 90/0xEE(238) = vendor-specific group

## Cross-version function map (v1.13 → 2025)

| purpose | v1.13 | 2025 fw |
| --- | --- | --- |
| main dispatcher | sub_200053F8 | sub_20006360 |
| SetStereoDirectMode(90/1) | sub_200053A8 → reply(129) via 0x1000BF62 | sub_2000620E → reply(131) via 0x1000C8AA→sub_20005A20 |
| feature-bit SET (90/9='9') | sub_20005014 | sub_20005B70 (mask dword_20005D40) |
| reg READ (ops 149/150/151) | sub_20000D8C (ext idx 112-114 @+480/484/488) | (same structure in fwB) |
| reg WRITE (op 149/150 tables) | sub_2000A8CC-area | sub_2000B4A4 (tables @ flash 0x2000CDA0/0x2000CEE4, runtime 0x10014CD4+228) |
| SPDIF passthru setter | loader 0x100096B4 (regs 0x1900B0/0x1900B4, consts 0x1F141±127/+130, flag@0x10014010) | main sub_20001B38 (same regs/consts, flag@0x100141C0? target dword_20001B98) |
| boot param init | sub_2000A40C (params 41,6/5,2/3,39,49,1,51,8,9,11,50,12,18/19/21,57/58/59,7,23/24/26,13/14/16,33/34/36,**52→SPDIF passthru**,38) | sub_2000AF88 (same params + 52→MalSPDIFPassthru) |
| output-profile apply | sub_20009760 (SCP 37 ladder: x+30/x+4/x+10, vol tables, mode via sub_2000072A) | sub_2000B870 (profiles 0-3, cmds 10/11/12 via I2C pairs) |
| sample-rate clock ladder | sub_20003DFC (÷256/512/768 thresholds, ±2304) | similar in fwB |
| coeff download ('Z' cmd 11) | sub_20001234 (a1=1: EQ? a1=2: matrix? per-config 112B structs, tables at cfg+120/+128, 14 dwords/frame) | same pattern |
| float-int converter | sub_200001A2 (IEEE754 tricks, exp 0x7F..150, ±106 shifts) | — |

## DSP register tables (op149: 57 floats, op150: 66 floats)

- **BYTE-IDENTICAL v1.13 ↔ 2025** (fwA@0x2000BBE0/0x2000BD28 vs fwB@0x2000CDA0/0x2000CEE4).
- Notables: [0]=1.0, [1]=0.2238 (0x3E6B851F), [5]=0.6, [7]=0.05, [9/10]=30.0, [11]=400, [12]=1400, [13]=2000, [14/15/16]=1.0 (×3), [28..34]=20/30/50/60/70/80/90, [35]=100, [36..41]=22.45/35.19/44.14/90.0/96.5/106.7 (speaker crossovers!), [42]=0.0471 (0x3F3D70A4), op150: [1]=1.0,[3]=0.5,[4]=0.3,[7]=0.65,[11]=20,[12]=20,[13]=0.5,[15]=20,[16]=20,[17]=0.5,[62]=1.0,[63]=0.25,[65]=0x40?...
- ⇒ NO change to any DSP/DAC drive constants 2019→2025 (Question B: no headroom trim added; behavior identical).

## Question B synthesis (pending final)

1. ASR measured v1.x-era unit (Mar 2019): -2dBFS → SINAD 112dB (from ~107-108 at full scale); LF THD ~1% @20Hz 0dBFS, fixed by -2dB digital.
2. amirm attribution: USB power capacitance (analog).
3. Firmware evidence: DAC/drive/gain constants unchanged v1.13→2.1.250903; no headroom-scaling code added (no 0.794/0.796-style multipliers in new code paths; the only 1.0f special-case = unity reset + cmd62).
4. ⇒ The -2dBFS behavior is NOT "fixed" in current fw — it's inherent to full-scale DAC drive; using Windows volume <100% (digital attenuation BEFORE DAC) reproduces the -2dB condition identically.
5. Live measurement deferred (user using device); thd_test.py ready when approved.

## Question C synthesis (firmware side mapped)

- StereoDirect arrives as host msg 90/1 (on/off). ACK reply built immediately; capability word 0x81 (2019) vs 0x83 (2025).
- The audio-effect DSP path: feature-bit SET (90/39) gated by fw feature mask; op150/op149 register table writes (the SBX effects) flow through sub_2000B4A4-equiv whose op-150 writes are SUPPRESSED when RAM flag @0x1001422C (2025) is set — flag set by audio-path state machine (sub_20004E38 / sub_20007D54 / sub_20009DB4 / boot-param-41).
- ⇒ Direct mode = MCU stops issuing DSP effect-register writes (incl. re-downloading effect banks) + output profile ladder reapplies clean path; the VT1728 "Malcolm" DSP is commanded into bypass/passthru (SPDIF passthru variant via 0x1900B0/B4 regs with 0x1F141-family values).
- Remaining: dump what 0x1001422C-flag toggling does to the op-150 flow (verify "suppress" reading), and tie output-profile (sub_2000B870 cmds 10/11/12) to speaker-config values 0/1/2/3 (host SpeakerConfig values) → completes Direct+7.1 vs non-direct+7.1 picture.

## DIRECT-MODE GATE VERIFIED (both fw versions) — decoded after above

- fwB `sub_2000B4A4` @loc_2000B524: `if (flag@0x1001422C != 0 && op==150) RETURN` — op-150 (SBX effect/param) DSP writes are SKIPPED entirely while the Direct flag is set.
- v1.13 equivalent `sub_200070E4` (full per-(config,feature) effect-register APPLY ENGINE): same gate via flag at off_200074F4+12 (struct @0x10080068) — op150 regs 0/2/4 suppressed when set; op-149 band-frequency regs (remap idx 0/4/10/19/44 → slots 4/2/8/16/32 = EQ band freq ladder) still flow.
- Engine layout: RAM blocks at 0x10014980, 384 B per (speakerConfig × feature), shadows at +224 (op149) / +116 (op150), master-gain float @+128, dirty flag @+2.0x80, +100/+4 path toggles.

## GAIN/VOLUME LADDER (identical 2019 → 2025) — Q-B hard evidence

- op150 reg3 = MASTER GAIN (float); thresholds 0.25 / 0.5 / 1.0 / 2.0 / 3.0 (0x3E800000 / 0x3F400000 / 0x3F800000 / 0x40000000 / 0x40400000).
- Gain-patch tables (≈10 × 8B {op,reg,val}): v1.13 @0x2000BE98/0x2000BF28 == 2025 @0x2000D050: reg5=0.9, reg9=1.0, regA=0, regB=2.0, regC=3.0, regD=3.0, regE=-2.0, regF=-2.0, reg10=0, reg11=3.0.
- Profile tables @v1.13:0x2000BFF8 / @2025:0x2000D1B8+0x2000D208 (op 0x87): regB=-9.0, regC=8.0, regD=0, regF=0.5, reg12/13=0x471C4000; profile2: regB=-12.06, regC=15.13, regD=16.13, reg12=98.2, reg13=500.0.
- ⇒ op150 reg5=0.9 multiplier existed in v1.13 (pre-ASR-review) — not a post-review trim; ALL gain constants byte-identical across 6 years. Confirms Q-B verdict.

## Question A leads (hidden/locked)

- Reply capability bits 0x81→0x83 (new capability bit in 2025 StereoDirect family).
- fwB dispatcher supports host cmds never issued by SBCommand app (e.g., 90/0xEE group, 90/155 AA/55 handshake (fw flash protocol!), 90/165, op151 idx2→sub_2000258C, ext reg indices 112-114).
- SCP cmd 39 sub 12/13 = SPDIF passthru manual trigger (app only exposes via Direct toggle).
- APO INI/registry: SysFx chain reg (oem22.inf) + 4 SysFx CLSIDs.
- To enumerate: diff host CTHIDRpA GETDEVICECONTROL/SETDEVICECONTROL enums vs fw msg-90 sub-handlers actually implemented.

## HOST-ENUM vs FW-IMPLEMENTED (Q-A, partial decode)

- Host library (CTHIDRpALibrary.cs): 78 GET + 55 SET msgs — generic across Creative devices, incl. Bluetooth RFCOMM (43-46), Relay (47-50), Addon install (26/27), LED patterns (37-53), VoiceFX (16-18/28-29), Speaker models/HRTF/OutputTarget (19-20/38-42/52-54), AutoSleep, CustomEQ (33-36/56-59), Passthrough (54/77).
- G6 fw dispatcher (msg 90 'Z'): implements subs 0..0x3C + 0xE0(224 GET-group: subs 1-9 = per-enum GETs) + 0xEE(238 vendor) + 0xF0(240).
- 0xE0 sub-8 handler (sub_1000CCFC): SpeakerModel/Preset logic with HRTF mode idx 15/16 → checks state block bits 0x8000 / 0x100 (+64/+65 dwords) = **G6 fw implements SpeakersHRTFMode (GET 52/SET 30)** — host app G6 product DLL may not expose it.
- Confirmed both StereoDirect (SET 1) and SPDIFOutDirect (SET 9) implemented + Set96kHzSPDIFInPassthroughMode (SET 6), SetSpeakersConfig (SET 7), SetLocalStore (8), SetDriverPresentMode (11), JackState (12), RestoreProfile (13) etc.

## DIRECT-MODE ↔ SPEAKER-CONFIG INTERACTION (Q-C FINAL mechanism, fwB loader sub_1000FCD8)

Full-effect-state dump routine `sub_1000FCD8(a1, a2=2, a3=0, a4)`:

- `a4 & 7 >> 1` = speaker-config index v6 ∈ {0, 1} (>=2 rejected UNLESS ==7 → falls back to stored default at off_1000FF9C+3).
- `a4 & 1` selects dump mode:
  - 1 → 268-byte-per-config blocks (dword_1000FF90): dumps reg 0x96(150) for 0x1B entries (from tbl dword_1000FF94) reading +108..111, PLUS reg 0x95(149) for 0x27 entries reading +108..111, PLUS final reg 0x97(151)/2 with +264..267 (master gain!) — i.e. the CURRENT ACTIVE per-config DSP state.
  - 0 → 384-byte blocks (dword_1000FFA0 = engine RAM): dumps reg 0x96(150) shadows at +116..119 (0x1B regs) + reg 0x95(149) shadows at +224..227 (0x27 regs).
- Builds SEVEN msg-90/23 notifications: six with sub 61 (0x3D) + one with sub 41 (0x29, m==6), each carrying payload {02,01,00,<a4>,0x66,01,0x80|m} — pushes effect state to host app in 6 blocks + master block.

Meaning: fw keeps per-speaker-config (0/1 = the two speaker-config "slots") effect shadow tables, and the state push uses msg 90/23/61 ×6 + 90/23/41. Config index only 0/1 valid → matches fw supporting 2 speaker-configs internally (stereo + 5.1/7.1 aggregate?), with host UI exposing more via channel-mask mapping.

For DIRECT+7.1: StereoDirect ON suppresses op-150 writes (fwB loc_2000B524 flag 0x1001422C / v1.13 off_200074F4+12) — the per-config SBX/HRTF effect shadows (0x1B op-150 regs + 0x27 op-149 EQ-band regs) STOP being applied to the DSP; only master gain (op 151/2 @+264) survives. Non-direct 7.1: full 384B/268B effect set per config drives the VT1728 DSP.

## Q-C HOST-SIDE (SBCommand decompile) — complete picture

- G6 app `SpeakerConfigViewModel` (decompiled, file re_analysis/G6/.../SpeakerConfigViewModel.cs):
  - `SetStereoDirect()` writes StereoDirectParameterId 0/1 via AggregatedFeature (→ HID SETDEVICECONTROL 1).
  - `SetSPDIFDirect()` → SPDIFOutDirectParameterId (→ SET 9).
  - `SetSpeakerHRTF()` → SpeakerHRTFParameterId (→ SET 30 SpeakersHRTFMode) — G6 exposes "USB HP Virtualization" (IsUSBHpVirtualizationAvailable = aggregatedSpeakerHRTFFeature != null; AE variant hard-false).
  - **Separate channel masks are PERSISTED per mode**: `SetSelectedDirectSpeakerChannelMask` / `SetSelectedHeadphoneChannelMask` (+Direct headphone variant) — the app restores your 7.1 choice independently for Direct ON vs OFF.
  - IsDirectMode change → SetStereoDirect + SetOutput (re-applies output profile to device).
- `G6SBXPageViewModel`: MultiplexOutputFeatureId "MultiplexOutputParameterId" == 4 → headphone mode; SpeakerHRTFFeatureId toggles isHPLineOut (X3-inherited 'IsX3HPLineOut' property) and switches SBX profile selection (HP profile vs SP profile).
- `G6ViewModel.InitFeatures()`: wires StereoDirect/MasterOnOff(SBX)/Scout/GraphicEq/VoiceFx + voice group (AEC/NR/SVM/MicEq) with FeatureReaction sets — enabling Direct marks SBX/EQ/Scout/VoiceClarity/VoiceFx StateAction=2 + Available=false in UI.

### Q-C verdict (Direct + 7.1 vs non-direct 7.1) — COMPLETE

Host (app) side:

1. Direct toggles StereoDirect parameter (HID msg 90/1) and remembers a separate 7.1 channel-mask preference for Direct vs non-Direct, re-applies it on switch.
2. UI disables all effect pages (SBX/EQ/Scout/Voice) via FeatureReaction when Direct on.

Firmware (VT1728 'Malcolm' DSP control MCU) side:
3. Msg 90/1 ACKs with capability word 0x81 (2019 fw) / 0x83 (2025 fw).
4. StereoDirect state feeds the effect-register apply engine: Direct flag (0x1001422C in 2025 / off_200074F4+12 @0x10080068 in v1.13) SUPPRESSES all op-150 (SBX/param) DSP register writes and (v1.13 engine path) also blocks re-application of op-149 EQ-band shadows; only master gain (op 151/2) survives.
5. Per-speaker-config effect shadow tables (268B active / 384B engine blocks, 2 config slots) stop being pushed to the DSP while Direct is active.
6. SPDIF-Out Direct additionally switches the VT1728 SPDIF block to passthrough (I2C regs 0x1900B0/0x1900B4 ← 0x1F0C2/0x1F1C3 off / 0x1F040/0x1F141 on) — verified live earlier: with Direct ON, optical out ignores USB playback entirely.

So "Direct Mode virtual 7.1" = 7.1 channel mask set as Windows endpoint format; USB audio streams 8 channels bit-unchanged; the device performs ONLY the fixed speaker-config downmix (analog path), with ALL SBX/HRTF/EQ DSP effect registers frozen out. "Non-direct virtual 7.1" = same 8-channel stream but the SBX/HRTF engine actively renders the 7.1→binaural downmix with the full per-config effect register set (0x1B op-150 params + 0x27 op-149 EQ-band params + master gain + profile gains 0.9/2.0/3.0 etc).

## Q-A HOST vs FW capability matrix (evidence)

- Generic CTHIDRpA library: 78 GET/55 SET enums (Bluetooth RFCOMM 43-46, Relay 47-50, Addon 26-27, LED suite 37-53, SpeakerModel/HRTF/OutputTarget 19-20/38-42/52-54, CustomEQ 33-36/56-59, VoiceFX 16-18/28-29, AutoSleep 32/55/75, Passthrough 54/77).
- G6 firmware dispatcher implements: msg-90 subs 0-0x3C + 0xE0 group (GETs incl. SpeakerModel/HRTF via 0xE0/8 with HRTF caps bits 0x8000/0x100) + 0xEE + 0xF0. Bluetooth/Relay/Addon = NOT implemented (NACK via default sub_20006340).
- G6 SBCommand product DLL actually wires: StereoDirect, SPDIFDirect, SpeakerHRTF (as USB HP Virtualization / HP-Line-Out profile), SpeakerConfig, SBX master (MasterOnOff), Scout, GraphicEq, VoiceFx, AEC/NR/SVM/MicEq, DolbyDigital decoder page, headphone gain, profiles, CustomEQ (partial wiring in framework), LED (lighting page in VM AvalonLightingViewModel), AutoSleep (settings pages), FactoryReset, Passthrough (profile data).
- Hidden/unexposed-but-implemented candidates found so far: Set96kHzSPDIFInPassthroughMode (SET 6 — app exposes only when fw reports feature bit), SetControlPermission (SET 4), SetDriverPresentMode (11), SetLocalStore (8), SetJackState (12), RestoreProfile (13), GetI2CAddressOverride/GetI2CMasterStatus (fw I2C passthrough! via GetVT1728I2CPassthroughSCPCommandParam in CTHIDRpA vtable), op151 idx2 (sub_2000258C target), ext reg indices 112-114 ('p'/'q'/'r' gain patch blocks), msg 90/23/61+41 effect-state push (app uses for state sync — present in both).
- LOCKED (implemented in fw but no UI path in G6 product): Bluetooth, Relay, Addon, LED pattern suite beyond basic (fw dispatcher handles subs 37-53 but G6 product exposes only basic lighting), PowerAdapterWattage (17/33 — G6 is USB powered; fw handler exists?).
- Capability bits: StereoDirectMode = 0x400000 (bit 22 FeatureBitwiseMask1); 2019→2025 StereoDirect reply cap word 0x81→0x83 = new capability bit added in 2025 fw family.

- fwA = v1.13 main IDB; fwB = 2025 main IDB; fwA_loader2 / fwB_loader2 = loader banks (thunk targets live here).
- All ELF/bank images: re_analysis/fw_extract/{elf,out}/; scripts: scan_installer/pe_info/parse_all/make_elf/verify_banks.
- Live probe tools: re_analysis/G6HidProbe (query), G6HidSet (toggle spdifdirect/stereodirect).
- Measurement scripts ready: re_analysis/G6Measure/{thd_test.py,optical_tap.py,wuh_check.py,g6_volume.py}.
- All findings: re_analysis/fw_notes.md (this file).

## LIVE CONTROL TESTS (G6HidExplore, feature-mask 0x5041B810)

G6 device personality reports (live GET FeatureMask):
- ENABLED: MicBoost(4), SoftButtonControl(11), JackControl(12), BatteryControl(13), LEDControl(15), **MalcolmParameterCustomization(16)**, StereoDirectMode(22), SPDIFOutDirectMode(28), **SpeakersHRTFMode(30)**
- DISABLED (fw rejects SET with E_FAIL): SCPPassthrough(0), MasterVolumeHigh, USBOverdrive, CommitSettings, Bluetooth(5,7), UserProfiles(8,9), ControlPermission(10), ANC, Siren, ComboWUH, DirectMonitor, MicTypeCfg, MicReverb, **HeadphoneHighGainMode(23)**, RestoreDefault, DataStore, **96kSPDIFInPassthrough(26)**, SpeakersConfig?? (27 — but app CAN set speaker config... mask may not gate all), Wattage, AutoSleep(31)

Live tests (all states restored after):
| Feature | Mask bit | SET result | Controllable? | Point? |
|---|---|---|---|---|
| SpeakersHRTFMode | 30 ON | **hr=0x00000000, persisted** | YES — any host app, no SBCommand needed | **Real hidden feature**: HRTF on speaker/line-out path independent of the app's HP-virtualization framing |
| HeadphoneHighGainMode | 23 OFF | hr=0x80004005 E_FAIL | No — fw-gated | G6 gain stays front-panel-button only |
| 96kHzSPDIFInPassthrough | 26 OFF | hr=0x80004005 E_FAIL | No — fw-gated | Would pass 96k SPDIF-in without 48k downsample; personality-locked |
| MalcolmParamCustomization | 16 ON | GET ok (live-changing struct: counter CC-45-xx-5D + F8-46-xx-02) | Readable; write side = SetVT1728I2CPassthroughSCPCommandParam (untested) | Engineering/debug window |

⇒ Two-tier lock model CONFIRMED: (1) mask-ON features = controllable by any host software via CTHIDRpA COM (documented method signatures in G6HidExplore); (2) mask-OFF features = rejected by firmware itself (E_FAIL) — cannot be enabled without firmware modification.

## VT1728 SCP parameter namespace (159 named DSP params, decompiled CTHIDRpALibrary.cs:55-214)

The SCP debug/query interface names every DSP parameter: AEC (enable/delays), NoiseReduction, VoiceFocus (mic distance/wedge/source angle), VoiceFX (formants/pitch/envelope/quiver/contour), MicEQ (8 bands gain/freq/bandwidth), MicSVM, MicReverb (full room model: level/pan/size/decay/diffusion/reflect/reverb/detune/echo...), DualMicEndFiring, CMSS3D (immersion), DialogPlus, SVM, Crystalizer, GraphicEQ (preamp + bands)… These map onto the op-149/op-150 register engine decoded in fw. The CTHIDRpA vtable exposes query+range+passthrough-write methods — an engineering control surface the G6 app never uses (bit 0 SCPPassthrough is OFF in mask, but MalcolmParameterCustomization bit 16 is ON and the I2C-passthrough SET vtable method exists).

- fwA = v1.13 main IDB; fwB = 2025 main IDB; fwA_loader2 / fwB_loader2 = loader banks (thunk targets live here).
- All ELF/bank images: re_analysis/fw_extract/{elf,out}/; scripts: scan_installer/pe_info/parse_all/make_elf/verify_banks.
- Live probe tools: re_analysis/G6HidProbe (query), G6HidSet (toggle spdifdirect/stereodirect).
- Measurement scripts ready: re_analysis/G6Measure/{thd_test.py,optical_tap.py,wuh_check.py,g6_volume.py}.
- All findings: re_analysis/fw_notes.md (this file).
