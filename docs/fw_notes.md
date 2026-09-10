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
| --- | --- | --- | --- | --- |
| SpeakersHRTFMode | 30 ON | **hr=0x00000000, persisted** | YES — any host app, no SBCommand needed | **Real hidden feature**: HRTF on speaker/line-out path independent of the app's HP-virtualization framing |
| HeadphoneHighGainMode | 23 OFF | hr=0x80004005 E_FAIL | No — fw-gated | G6 gain stays front-panel-button only |
| 96kHzSPDIFInPassthrough | 26 OFF | hr=0x80004005 E_FAIL | No — fw-gated | Would pass 96k SPDIF-in without 48k downsample; personality-locked |
| MalcolmParamCustomization | 16 ON | GET ok (live-changing struct: counter CC-45-xx-5D + F8-46-xx-02) | Readable; write side = SetVT1728I2CPassthroughSCPCommandParam (untested) | Engineering/debug window |

⇒ Two-tier lock model CONFIRMED: (1) mask-ON features = controllable by any host software via CTHIDRpA COM (documented method signatures in G6HidExplore); (2) mask-OFF features = rejected by firmware itself (E_FAIL) — cannot be enabled without firmware modification.

## VT1728 SCP parameter namespace (159 named DSP params, decompiled CTHIDRpALibrary.cs:55-214)

The SCP debug/query interface names every DSP parameter: AEC (enable/delays), NoiseReduction, VoiceFocus (mic distance/wedge/source angle), VoiceFX (formants/pitch/envelope/quiver/contour), MicEQ (8 bands gain/freq/bandwidth), MicSVM, MicReverb (full room model: level/pan/size/decay/diffusion/reflect/reverb/detune/echo...), DualMicEndFiring, CMSS3D (immersion), DialogPlus, SVM, Crystalizer, GraphicEQ (preamp + bands)… These map onto the op-149/op-150 register engine decoded in fw. The CTHIDRpA vtable exposes query+range+passthrough-write methods — an engineering control surface the G6 app never uses (bit 0 SCPPassthrough is OFF in mask, but MalcolmParameterCustomization bit 16 is ON and the I2C-passthrough SET vtable method exists).

## HOST APO vs DEVICE DSP — final architecture refinement (todo #1 closed)

Deeper dig into KSUSBAPO64.dll + SndCrUSB.dll + ksusba64.sys (IDA sessions apo2/snd/ksdrv) found the full picture — TWO effect paths exist:

**Path 1 (primary, device-side)** — SBX playback effects under Sound Blaster Command:
App → CTSoundCore (SndCrUSB.DLL, x86, CSoundCoreMgr with per-device param tables at +74/+881, cached feature slots ≤0x3E, GetVT1728MalcolmSCPQuery API) → CTHIDRpA → HID 'Z' frames → Malcolm MCU (op-149/150/151 registers → VT1728 DSP). Proven by fw gate: Direct suppresses DEVICE writes; Linux tools driving only these frames get full SBX on hardware.

**Path 2 (host-side APO)** — KSUSBAPO64.dll (SysFx SFX/MFX/EFX CLSIDs {E9B73398…}/{41528545…}/{FE078F0E…}, all registered to this DLL — verified in registry CLSID\…\InprocServer32) loads into audiodg for the G6 endpoint (endpoint property store lists cfSB1770.ini 3×: keys {872572B3…}, {872572B4…}, {BB282A80…} — read live via MMDeviceEnumerator). Contains 50+ host EfxMod engines: CFixedSr, CPassthru, CSwap, CCrystalizer, CMultiBandEQ, CReverb, CCMSS/CCMSS3D (full upmix/surround family: CCMSSUpmix/CCMSSSurround/CCMSSRealUpmix/CMSS1Upmix/CMSS3UpmixNew/CMSS3UpmixComponent), CDTSNeoPC, CTestmix, CSimpleMix, CBassManagement, CSVMEfxMod, CVoiceFX, CPitchShift, CLimiter, CMatrixEncoder, CSpeakerEQ, CAEC/CAECRef, CMicBeam(Plus), CTHXSVM, CSTFT/CISTFT, CMonoToStereo/CInterleave/CMono2Stereo, CStereoSurround3 (×2 generations), C5D1Side↔Rear swaps, CDCOffsetRemoval, CEncoder, CAsrc, CSilenceOnFailure, CDataDump, DataInject (stub, hardcoded E_FAIL), CAudioPosition.

Config files: `C:\ProgramData\Creative\APOINI\cfSB1770.ini` (G6) + `C:\Windows\System32\ksUSBaud.ini` are **obfuscated** (not single-byte XOR — brute-forced 0..255, no printable run; same scheme both files). ksusba64.sys reads only registry (no ZwCreateFile/ZwReadFile imports) — the ini files are consumed by user-mode (co-installer KsUSBDvIn64.dll!CtDevCoInstProc / APOContainer side) which pushes topology into the registry/driver. GH0390.cfg/MF0470.cfg are PLAIN-TEXT per-model speaker-EQ configs for OTHER products (H8/SBX Megatron) — not G6.

SndCrUSB also embeds `<HostEffectProfiles>` XML (profile banks: Music/Movie/Gaming/SBX Default/Warm Sound/Smart Volume/Dynamic Boost/Night Mode/Clear Dialog/Stadium Surround/Clear Comms/Cinematic Action, with surround/crystalizer/xbass/svm/dlgplus/graphic_eq params; versions 1.37/1.43) — host-side profile definitions pushed down the device path; special packed feature IDs 0x10000010/0x10004080/0x1000002 (StereoDirect-family state cached at engine+25..28 via sub_42F71C).

**Verdict for the Linux question (updates docs/LINUX.md):** the APO is a Windows-audio-engine integration + fallback layer; the G6's actual virtual-7.1/SBX render lives on the device DSP. Linux tools sending only the HID frames reproduce the SBX experience because path 1 is authoritative. The APO path explains why some Windows-only conveniences (per-app volumes, Windows spatial integration, host profile switching when device is busy) don't map 1:1 to Linux — but none of them are required for Direct/7.1/SBX.

- fwA = v1.13 main IDB; fwB = 2025 main IDB; fwA_loader2 / fwB_loader2 = loader banks (thunk targets live here).
- All ELF/bank images: re_analysis/fw_extract/{elf,out}/; scripts: scan_installer/pe_info/parse_all/make_elf/verify_banks.
- Live probe tools: re_analysis/G6HidProbe (query), G6HidSet (toggle spdifdirect/stereodirect).
- Measurement scripts ready: re_analysis/G6Measure/{thd_test.py,optical_tap.py,wuh_check.py,g6_volume.py}.
- All findings: re_analysis/fw_notes.md (this file).

## DAC FILTERS — full decode (live + firmware + datasheet + Linux ecosystem), 2026-09-09

**Live enumeration (G6SoundCoreProbe, via SndCrUSB ISoundCore CLSID {495E4C24-85ED-4f19-885E-C2D01D7EA26C}, reg-free via CTIntrfu + BindHardware endpoint {0.0.0.00000000}.{b14c16b8-7fd2-492f-abbe-63ad5e3634e7}):**

- Feature 0x01000001 (System_MalcolmDeviceControl), param 21 'DACFilterTypeSelect' (type 2 dword), param 22 'EnumDACFilterTypeSelect' (type 5, item size 8 = {uint idx; ushort code}), current value raw 0x06.
- Device advertises 5 filters: idx0=code3 FastRolloffMinimumPhase, idx1=code4 SlowRolloffMinimumPhase, **idx2=code5 NonOverSampling**, idx3=code6 FastRolloffLinearPhase, idx4=code7 SlowRolloffLinearPhase. Iteration ends hr=0x80004005 at idx5.
- GUI shows only 4 — app hardcodes skip of "NonOverSampling" by name in BaseFiltersPageViewModel.InitializeSetupDACFilter (UIFramework .../CMDViewModels/Audio/BaseFiltersPageViewModel.cs:110-130, the `if (!(text == "NonOverSampling"))` exclusion).

**Transport chain (fully mapped):**
App(.NET SoundCoreRepository) → ISoundCore::SetParamValue({feature 0x01000001, param 21}, dword code) → SndCrUSB.dll (the COM server, x86; G6 branch sets isMalcolm when VID 0x041E & PID in {0x6005,0x323C,0x3243,0x3256(G6),0x323A,0x3125,0x3247,0x30E3,0x3255}, SndCrUSB sub_42EBE4 @0x42ED8D) → CoCreate(CmdRtr, CLSID {32CD1956-569B-432F-BA27-F0BFEA458D1B} = CommandRouter.EndpointEnumeration, InprocServer32 CmdRtr64.DLL / SysWOW64\CmdRtr.DLL for x86) → KSUSBSPI (SPI provider CLSID {CAABAA19-4206-41B1-9A99-2B8917C79631} → System32\KSUSBSPI64.dll / SysWOW64\KSUSBSPI32.dll, has KsCreatePin+DeviceIoControl+HidD_SetOutputReport+SetupAPI) → ksusba64.sys + G6 HID interface. Registry: HKLM\SOFTWARE\Creative Tech\Command Router\{APO,SPI} map IID {920449A1-FFE8-434C-A2BC-C0CC1582BBD9} = "IMalcEndpoint::RebindHardware" (string found in SndCrUSB @0x41EF2C area). CTHIDRpA.dll is NOT in this chain (it's the direct-HID app path, CRT-only strings, no Malcolm names).

- Note: SndCrUSB static init table at 0x401280-0x401380 holds 46 per-product param-table ctors (0x50C-byte MalcolmDeviceControl tables, first @0x63B190; feature tag 0x01000001, per-param desc {idx, 0x01000001 tag, flags, type, size, name}); 46 × 0x91B ctors (first sub_46116C @0x63B4A8) = ProcessingControl tables. 46 products share the schema; G6 personality selects via VID/PID.

**Wire format (cross-verified with nils-skowasch/soundblaster-x-g6-cli Wireshark captures, doc/usb-spec.md + payloads/raw/g6_playback.txt):**

- Filter SET = `5A 6C 03 00 <code-2>` + commit `5A 6C 01 01 00`, zero-padded to 64B, HID interface 4 (SET_REPORT).
- Payload = SoundCore code − 2: 01→code3 FastMinPhase, 02→code4 SlowMinPhase, **03→code5 NOS**, 04→code6 FastLinPhase, 05→code7 SlowLinPhase. Their captures record exactly 01,02,04,05 (NOS 03 skipped — mirroring Creative's GUI exclusion); their enum `PlaybackFilter` (src/g6_cli/g6_spec/**init**.py) has only the 4 GUI values.

**Why NOS on the CS43131 (Cirrus Logic DS1155F2, downloaded to re_analysis/CS43131_DS1155F2.pdf):**

- The chip's PCM Filter Option register 0x90000 has FILTER_SLOW_FASTB (roll-off speed), PHCOMP_LOWLATB (phase-comp/low-latency), and the **NOS bit ("NOS emulation mode")** — datasheet §5.9 'Enabling and Disabling NOS Filter' gives pop-free enable/disable sequences (soft-ramp mute → OR 0x20 into 0x90000 → unmute; disable = AND 0xDF).
- So all 5 enumerated modes are real silicon register states: 4 = the 2×2 matrix (fast/slow × min/linear phase) of the oversampled interpolation filter (§9.1 plots show the impulse/step responses), 5th = interpolation filter bypass.
- Engineering meaning of NOS on a delta-sigma DAC: bypasses the FIR interpolation filter; output becomes a zero-order-hold of the native samples. Effects: (a) sinc/sin(x)/x passband droop, about −3.2 dB at 20 kHz for 44.1 kHz content (classic ZOH Nyquist roll-off, grows with fs); (b) imaging artifacts above Nyquist are NOT removed (alias images fold down in any downstream resampling/processing — analog stage must absorb them); (c) minimum processing delay and no pre-ringing (the reason NOS fans prefer it: transient response with zero digital filtering artifacts); (d) on a TRUE 1-bit NOS DAC this is the "classic NOS sound", but the CS43131 is a multibit delta-sigma running an 'emulation mode' — Cirrus keeps the modulator but skips interpolation.
- Practical G6 verdict: NOS is a legitimate listening-taste feature (softest treble, no digital filter ringing), objectively worse on measurements (droop + images), which matches Creative hiding it from the mass-market GUI while keeping it in firmware, the SoundCore param namespace, and the chip itself. Any host can set it with one frame: `5A 6C 03 00 03` + `5A 6C 01 01`.

**Linux status after this finding:** soundblaster-x-g6-cli already ships `--playback-filter` with the 4 GUI filters (works on our fw 2.1.250903.1324). NOS is one missing enum value: add `NON_OVERSAMPLING = bytes.fromhex('0003')` to their PlaybackFilter — no new protocol discovery needed. No GitHub discussion/issues found about G6 DAC filters or NOS in the ecosystem repos (checked nils-skowasch issues list, searched github topics/soundblaster).

## ASIO DRIVER (CtUsAsio) — complete decode + sample-based-latency patch, 2026-09-10

**Driver:** Creative USB Native ASIO v1.1.3.0 (2016 build, both x86/x64), registered as
`HKLM\SOFTWARE\ASIO\Creative Sound Blaster ASIO Device`, CLSID `{B2D4D5A2-1B17-4AB6-8A6D-667095C480B2}`,
`C:\Program Files (x86)\Creative\Creative USB Native ASIO\CtUsAsio\{amd64\CtUsAs64.dll,i386\CtUsAsio.dll}`.
It is a KS-streaming ASIO driver (no USB/HID of its own): CKsFilter/CKsPin wrappers talk to **ksusba64.sys**
(the same KSUSB filter we decoded) via SetupDi + KsCreatePin. Strings confirm the Malcolm family:
`IDD_ASIOCP_MALCOLM` control panel, PDB `c:\cbs\build\...\ctusasio\Binfre_wlh_amd64\amd64\CtUsAs64.pdb`.

**Config (HKCU\Software\Creative Tech\CtUsAsio, written by panel/driver):**
- `Latency` REG_DWORD = **milliseconds**, one of 13 values (table @0x427A08): 1,2,4,5,6,8,10,20,40,50,60,80,100
- `BitDepth` REG_DWORD = 16 or 24 (table @0x427B30); KS-pin WFX uses 16-bit int or 24-in-32 (sub_40E11C);
  host always sees Float32LSB either way (getChannelInfo 0x40A2A4 maps 32→ASIOSampleType 19)
- `SampleRate` REG_QWORD = **double** Hz persisted by setSampleRate (0x40A134)
- Found live: stale SampleRate=384000.0 + Latency=50 → getBufferSize reported min=max=pref=**19200**, gran=0
  (a full 100ms at 384k — the root cause of absurd reported latencies in hosts).

**Vtable (CAsio @0x403A60, slot = ASIO ABI order):** 3 init(0x4098A0, reads Latency/BitDepth/SampleRate),
9 getChannels(0x409EA4 → this+216/+220), 10 getLatencies(0x409ED0 → delegates to getBufferSize, in=out),
11 getBufferSize(0x409F28), 14 setSampleRate(0x40A134), 15 getClockSources(0x40A204 "Internal Clock"),
18 getChannelInfo(0x40A2A4), 19 createBuffers(0x40A404), 20 disposeBuffers(0x40A63C), 21 controlPanel(0x40A880).

**Multichannel — WORKS (no fix needed, config-dependent):** live probe showed **8 output channels**
(Front/Rear/Center-Sub/Side L/R, names auto-assigned by pin channel count in sub_40B2B0:
≤2 stereo / ≤6 adds Rear+C-Sub / >6 adds Side) + 2 input (Audio-In L/R). Channel count comes from the
KS render pin's dataranges, which the KSUSB driver exposes per the **speaker config**:
`HKLM\SYSTEM\...\USB\VID_041E&PID_3256&MI_00\...\Device Parameters\KSAud_Device\SPeakerConfig = 0x63F` (7.1 mask)
⇒ with the G6 in 7.1 mode the ASIO layer exposes all 8 channels; stereo mode exposes 2.
createBuffers(10ch @ Float32LSB) verified OK + 2s silent 8ch start/stop OK on the real device.
If a host shows only stereo: switch the G6 to 7.1 in Sound Blaster Command first (device state, not ASIO).

**Latency model (ms-quantized by design):** bufferSamples = rate × Latency_ms / 1000 exactly
(live-verified 48/96/192/288/480 @48k for 1/2/4/6/10ms). getBufferSize hard-reports
**min=max=preferred=that value, granularity 0** (tail @0x40A037: `mov [r9]→[r8]→[rbx]; and [r11],0`),
so DAWs never offer a sample-count dropdown and display latency in ms.
**But createBuffers accepts ANY size**: the ms-check (sub_40BAB8 @0x40A480, result discarded — verified
in disassembly, no test/branch after `call`) only fires advisory callbacks
(sampleRateDidChange → kAsioOverload → kAsioBufferSizeChange(ms) → kAsioResetRequest) and proceeds.

**Patch (sample-based latency, reversible, per-user):** copy `CtUsAs64.dll` → rebind CLSID
`{B2D4D5A2...}` → `{8F5E2A31-6C74-4B9E-9D3A-2E7F5A6B8C90}` (6 occurrences incl. ATL object map),
patch 12 bytes at file 0x9437 (VA 0x40A037) in getBufferSize tail:
`41 8B 09 41 89 08 89 0B 41 83 23 00` → `41 C7 03 08 00 00 00 90 90 90 90 90`
(mov dword [r11],8 ; nops — skips the min=max=pref overwrite, sets granularity=8).
Result (live-verified): **min=48, max=4800, preferred=2400, granularity=8** @48k/50ms —
hosts now get a proper sample-quantized dropdown. Verified createBuffers at 128, 33 (odd!) and 4800 samples OK.
Registered per-user: `HKCU\Software\ASIO\G6 ASIO (sample-based patch)` + `HKCU\Software\Classes\CLSID\{8F5E2A31-...}`
(removal = delete those two keys; zero system files touched). The patched DLL is
`re_analysis/ida_targets/CtUsAs64_patched.dll` + patch script `re_analysis/G6AsioProbe/patch_asio.py`.
**Note:** getLatencies still reports the preferred-ms size (single-buffer model, in=out); hosts computing
"ms" divide by the real rate — with the stale 384k cleared this is now consistent.

**Tool:** `G6AsioProbe` (tools/G6AsioProbe) — minimal ASIO host (raw vtable COM, STA thread — the
Apartment-threaded driver proxies on MTA). Modes: default dump, `--buffers` (create/dispose all ch),
`--stream <ms>` (brief silent start/stop), `--clsid <guid>` (probe alternate build), `--set-rate <hz>`
(driver's own setSampleRate persist), `--size <n>` (host-chosen block size).

## ASIO — Nuendo/Cubase detection of the patched driver (root cause), 2026-09-10

Symptom: per-user registered patched ASIO driver (HKCU\Software\ASIO + HKCU\Software\Classes\CLSID\{8F5E2A31-...})
showed in REAPER-style hosts but NOT in Nuendo 15. Root cause (disassembly of Nuendo's baios.dll, x64,
C:\Program Files\Steinberg\Nuendo 15\Components\baios.dll): its ASIO discovery enumerates ONLY
HKLM\SOFTWARE\ASIO (sub_1800079A0: RegOpenKeyW(HKEY_LOCAL_MACHINE,"SOFTWARE\ASIO"); sub_180006FC0 adds only
a C:\Program Files\Common Files\ASIO3\*.dll folder scan). No HKCU\Software\ASIO enumeration exists anywhere
in the component. Per-entry parsing (sub_180008030): required CLSID value, optional Description (falls back
to key name). CLSID validation (sub_180007CC0) resolves HKCR\CLSID\<clsid>\InprocServer32 (merged view -
per-user classes ARE visible) and checks the DLL file exists (sub_180007C30 CreateFileW OPEN_EXISTING,
System32-relative fallback). Therefore: COM class can stay per-user; ONLY the enumeration entry must be in
HKLM. Fix (applied): HKLM\SOFTWARE\ASIO\G6 ASIO (sample-based patch) {CLSID={8F5E2A31-...}, Description=...}
via register_hklm.cmd (admin, one time; unregister_hklm.cmd reverses). Verified with new tool
G6AsioEnum (reproduces baios.dll discovery): 7 entries before, 8 after with the patched driver LISTED;
probe on patched CLSID still reports 8ch, min=48 max=4800 pref=2400 gran=8 @48k; stock entry unchanged;
user DLL copy SHA256-identical to tested build. Pitfall found: reg-script DLL-path extraction must match
the value line (findstr /c:"REG_SZ"), not the key header (findstr "InprocServer32" matched the header and
left the path empty - the first register script exited early; fixed).
