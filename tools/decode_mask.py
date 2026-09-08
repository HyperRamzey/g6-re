"""Decode G6 feature-mask query results from G6HidExplore output."""

# All FeatureBitwiseMask1/2 bit names from decompiled CTHIDRpALibrary.cs (lines 2773-2871+)
MASK1 = {
    0: "SCPPassthrough",
    1: "MasterVolumeHigh",
    2: "USBOverdrive",
    3: "CommitSettings",
    4: "MalcolmMicrophoneBoost",
    5: "BluetoothControl",
    6: "HostBasedFixedFormatSCPButtonProfileConfiguration",
    7: "BluetoothAutoConnect",
    8: "DeviceBasedUserProfile",
    9: "HostBasedUserProfile",
    10: "ControlPermission",
    11: "SoftButtonControl",
    12: "JackControl",
    13: "BatteryControl",
    14: "ANC",
    15: "LEDControl",
    16: "MalcolmParameterCustomization",
    17: "SirenControl",
    18: "ComboWUHCustomization",
    19: "DirectMonitorCustomization",
    20: "MicTypeConfiguration",
    21: "MicReverbPresetID",
    22: "StereoDirectMode",
    23: "HeadphoneHighGainMode",
    24: "RestoreDefault",
    25: "DataStore",
    26: "96kHzSPDIFInPassthroughMode",
    27: "SpeakersConfiguration",
    28: "SPDIFOutDirectMode",
    29: "PowerAdapterWattageMode",
    30: "SpeakersHRTFMode",
    31: "AutoSleepMode",
}

MASK2 = {
    0: "THXTruStudioProSurround3D",
    1: "THXTruStudioProCrystalizer",
    2: "THXTruStudioProBass",
    3: "THXTruStudioProSmartVolume",
    4: "THXTruStudioProDialogPlus",
    5: "THXPlaybackGraphicEqualizer",
    6: "VoiceReverb",
    7: "KeyChangePitchShifter",
    8: "MicSmartVolume",
    9: "MicEqualizer",
    10: "NoiseReduction",
    11: "VoiceFocusMicBeamPlus",
    12: "VoiceFX",
    13: "AcousticEchoCancelation",
    14: "SpeakerEnhancementSpeakerEQ",
    15: "SpeakerCalibration",
    16: "BassManagement",
    17: "DolbyDigitalLiveEnocding",
}


def main() -> int:
    raw1 = input("FeatureBitwiseMask1 hex (e.g. 5041B810): ").strip()
    m1 = int(raw1, 16)
    print(f"Mask1 = 0x{m1:08X}")
    for i in range(32):
        if (m1 >> i) & 1:
            print(f"  bit {i:2d}  0x{1 << i:08X}  {MASK1.get(i, '?')}")
    raw2 = input("FeatureBitwiseMask2 hex (blank to skip): ").strip()
    if raw2:
        m2 = int(raw2, 16)
        print(f"Mask2 = 0x{m2:08X}")
        for i in range(32):
            if (m2 >> i) & 1:
                print(f"  bit {i:2d}  0x{1 << i:08X}  {MASK2.get(i, '?')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
