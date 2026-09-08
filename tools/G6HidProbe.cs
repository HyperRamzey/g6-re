// G6HidProbe - read-only query of the Sound BlasterX G6 via Creative's CTHIDRpA COM library.
// Mirrors HIDMonitorControl.GetFirmwareVersionStringEx / GetDeviceFeatureMask logic.
// This is a READ-ONLY diagnostic: it only calls Get* messages, never Set*.
using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

namespace G6HidProbe
{
    internal static class Program
    {
        // ==== COM activation (from HIDMonitorControl.CreateComObject) ====
        static Guid CLSID = new Guid("335871C5-0D55-4FF6-9CE9-F5A3479F1D1F");
        static Guid IID   = new Guid("66DE3850-3DBF-4FD7-956F-3B0E0A5AD56C");

        // ==== CTHIDRpALibrary definitions (from decompiled Creative.Platform.Devices) ====
        const uint HRes_S_OK = 0;
        const uint HRes_S_FALSE = 1;

        enum GETDEVICECONTROL_Msg : uint
        {
            GetNumFeatureMask = 2,
            GetFeatureMask = 3,
            GetStereoDirectMode = 10,
            GetHeadphoneHighGainMode = 11,
            Get96kHzSPDIFInPassthroughMode = 15,
            GetSpeakersConfigAvailable = 16,
            GetSpeakersConfig = 17,
            GetLocalStoreAvailable = 18,
            GetLocalStore = 19,
            GetSPDIFOutDirectMode = 20,
            GetBatteryLevel = 21,
            GetBatteryStatus = 22,
            GetJackAvailable = 23,
            GetJackState = 24,
            GetActiveProfile = 25,
            GetDefaultProfile = 26,
            GetAudioPromptControl = 27,
            GetSupportedVoiceFXType = 28,
            GetVoiceFXPresetID = 29,
            GetNumMCU = 30,
            GetMCUType = 31,
            GetMCUVersion = 32,
            GetPowerAdapterWattageMode = 33,
            GetDeviceDisplayTime = 34,
            GetFirmwareVersionString = 35,
            GetVoiceFXPreviewState = 36,
            GetFirmwareConfigurationString = 37,
            GetSupportedSpeakersModelID = 38,
            GetSupportedSpeakersModelInfo = 39,
            GetSupportedAudioPromptControl = 62,
            GetNumCreativeLedSlot = 68,
            GetProfileData = 51,
            GetSpeakersHRTFMode = 52,
            GetSupportedSpeakersOutputTargetBitwiseMask = 53,
            GetActiveSpeakersOutputTarget = 54,
            GetAutoSleepMode = 55,
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        struct GETDEVICECONTROLPARAM_GetFirmwareVersionString
        {
            [MarshalAs(UnmanagedType.ByValArray, SizeConst = 256)]
            public char[] szFirmwareVersionString;
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        struct GETDEVICECONTROLPARAM_GetFirmwareConfigurationString
        {
            [MarshalAs(UnmanagedType.ByValArray, SizeConst = 256)]
            public char[] szFirmwareConfigurationString;
        }

        [StructLayout(LayoutKind.Sequential)]
        struct GETDEVICECONTROLPARAM_GetNumFeatureMask
        {
            public uint dwNumFeatureMask;
        }

        [StructLayout(LayoutKind.Sequential)]
        struct SETFEATUREMASK
        {
            public uint dwSupportedFeatureBitwiseMask;
            public uint dwSetFeatureBitwiseMask;
            public uint dwCurrentlyUnavailableFeatureBitwiseMask;
        }

        [StructLayout(LayoutKind.Sequential)]
        struct GETDEVICECONTROLPARAM_GetFeatureMask
        {
            public byte bFeatureMaskID;
            public SETFEATUREMASK maskFeature;
        }

        [StructLayout(LayoutKind.Sequential)]
        struct GETDEVICECONTROLPARAM_GetStereoDirectMode { public byte bState; }
        [StructLayout(LayoutKind.Sequential)]
        struct GETDEVICECONTROLPARAM_GetHeadphoneHighGainMode { public byte bState; }
        [StructLayout(LayoutKind.Sequential)]
        struct GETDEVICECONTROLPARAM_Get96kHzSPDIFInPassthroughMode { public byte bState; }
        [StructLayout(LayoutKind.Sequential)]
        struct GETDEVICECONTROLPARAM_GetSPDIFOutDirectMode { public byte bState; }
        [StructLayout(LayoutKind.Sequential)]
        struct GETDEVICECONTROLPARAM_GetPowerAdapterWattageMode { public byte bState; }
        [StructLayout(LayoutKind.Sequential)]
        struct GETDEVICECONTROLPARAM_GetSpeakersHRTFMode { public byte bState; }
        [StructLayout(LayoutKind.Sequential)]
        struct GETDEVICECONTROLPARAM_GetAutoSleepMode { public byte bState; }
        [StructLayout(LayoutKind.Sequential)]
        struct GETDEVICECONTROLPARAM_GetSpeakersConfigAvailable { public byte bState; }
        [StructLayout(LayoutKind.Sequential)]
        struct GETDEVICECONTROLPARAM_GetSpeakersConfig { public uint dwSpeakersConfiguration; }
        [StructLayout(LayoutKind.Sequential)]
        struct GETDEVICECONTROLPARAM_GetJackAvailable { public byte bState; }
        [StructLayout(LayoutKind.Sequential)]
        struct GETDEVICECONTROLPARAM_GetJackState { public byte bState; }
        [StructLayout(LayoutKind.Sequential)]
        struct GETDEVICECONTROLPARAM_GetNumMCU { public uint dwNumMCU; }
        [StructLayout(LayoutKind.Sequential)]
        struct GETDEVICECONTROLPARAM_GetMCUType { public uint dwMCUType; }
        [StructLayout(LayoutKind.Sequential)]
        struct GETDEVICECONTROLPARAM_GetMCUVersion { public uint dwMCUVersion; }

        [ComImport, Guid("66DE3850-3DBF-4FD7-956F-3B0E0A5AD56C"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        interface ICTHIDRpA
        {
            [PreserveSig] uint Initialize(uint dwInterfaceVersion, uint dwFlag);
            [PreserveSig] uint Open(ushort usVendorID, ushort usProductID, [MarshalAs(UnmanagedType.BStr)] string lpcwszSerialNumber, ushort usUsagePage, ushort usUsageID, [MarshalAs(UnmanagedType.BStr)] string lpcszDeviceInstance, ref int pdwDetailErrorCode, uint dwFlag);
            [PreserveSig] uint GetProductString([Out][MarshalAs(UnmanagedType.LPWStr)] StringBuilder lpwszProductStringBuf, ulong ulBufLength, uint dwFlag);
            [PreserveSig] uint GetSupportedCommands(ref byte a, ref byte b, ref byte c, ref byte d, ref byte e, ref byte f, ref byte g, ref byte h, uint dwFlag);
            [PreserveSig] uint GetFirmwareVersion(byte bDataFirmwareID, ref byte major, ref byte minor, ref ushort build, uint dwFlag);
            [PreserveSig] uint GetLedOnOffStatus(ref byte status, uint dwFlag);
            [PreserveSig] uint SetLedOnOff(byte onOff, uint dwFlag);
            [PreserveSig] uint GetBatteryStatus(ref byte pct, ref byte charging, ref byte low, ref uint mv, ref uint raw, uint dwFlag);
            [PreserveSig] uint GetModuleMode(byte moduleId, ref byte mode, uint dwFlag);
            [PreserveSig] uint SetModuleMode(byte moduleId, byte mode, uint dwFlag);
            [PreserveSig] uint RegisterNotificationCallback(IntPtr proc, IntPtr userData, uint dwFlag, IntPtr buf, ref ushort len);
            [PreserveSig] uint UnregisterNotificationCallback(uint dwFlag);
            [PreserveSig] uint Close(uint dwFlag);
            [PreserveSig] uint Shutdown(uint dwFlag);
            [PreserveSig] uint GetAECOnOffStatus(ref byte status, uint dwFlag);
            [PreserveSig] uint SetAECOnOff(byte onOff, uint dwFlag);
            [PreserveSig] uint GetMicBoostLevel(ref byte level, uint dwFlag);
            [PreserveSig] uint SetMicBoostLevel(byte level, uint dwFlag);
            [PreserveSig] uint SetOutputReport(IntPtr buf, ulong size, uint dwFlag);
            [PreserveSig] uint GetInputReport(IntPtr buf, ulong size, uint dwFlag);
            [PreserveSig] uint GetSerialNumberString([Out][MarshalAs(UnmanagedType.LPWStr)] StringBuilder buf, ulong len, uint dwFlag);
            [PreserveSig] uint SetOutputReportThenGetInterruptTransferInputReport(IntPtr setBuf, ulong setBufSize, IntPtr getBuf, ulong getBufSize, uint timeoutMs, uint maxRetries, uint retryIntervalMs, uint dwFlag);
            [PreserveSig] uint GetHeadphoneMicrophoneJackDefaultState(ref byte state, uint dwFlag);
            [PreserveSig] uint GetHeadphoneMicrophoneJackState(ref byte state, uint dwFlag);
            [PreserveSig] uint SetHeadphoneMicrophoneJackState(byte state, uint dwFlag);
            [PreserveSig] uint GetDebugInfoOfVT1728MALCOLMSCPQuery_ParamType(IntPtr a, ref string b, ref byte c, ref byte d, ref byte e, ref byte f, uint dwFlag);
            [PreserveSig] uint GetVT1728MalcolmSCPQueryParam(ref byte a, uint dwFlag);
            [PreserveSig] uint GetVT1728MalcolmSCPQueryRange(ref byte a, uint dwFlag);
            [PreserveSig] uint GetDeviceControlParam(GETDEVICECONTROL_Msg msgGetDeviceControl, IntPtr lparam, uint dwFlag);
            [PreserveSig] uint GetProductAttributes(ulong ulDeviceIndex, ref string path, ref ushort vid, ref ushort pid, ref ushort ver, uint dwFlag);
            [PreserveSig] uint SetVT1728I2CPassthroughSCPCommandParam(ref byte a, uint dwFlag);
            [PreserveSig] uint SetDeviceControlParam(IntPtr a, IntPtr b, uint dwFlag);
        }

        // CTIntrfu (from CTIntrfuLibrary.cs)
        static class CTIntrfu
        {
            [DllImport("CTIntrfu.dll", CharSet = CharSet.Unicode)]
            public static extern int CTCreateInstanceEx(ref Guid rclsid, IntPtr pUnkOuter, uint dwClsContext, ref Guid riid, IntPtr pServerInfo, IntPtr pcn, [MarshalAs(UnmanagedType.LPWStr)] string lpcszLibFile, IntPtr pReserved, out IntPtr ppv);
        }

        static void Main(string[] args)
        {
            string libFile = args.Length > 0 ? args[0] : @"C:\Program Files (x86)\Creative\Sound Blaster Command\Platform\CTHIDRpA.dll";
            Console.WriteLine($"[G6HidProbe] libFile = {libFile}");
            IntPtr pItf = IntPtr.Zero;
            int hr = CTIntrfu.CTCreateInstanceEx(ref CLSID, IntPtr.Zero, 0, ref IID, IntPtr.Zero, IntPtr.Zero, libFile, IntPtr.Zero, out pItf);
            Console.WriteLine($"[G6HidProbe] CTCreateInstanceEx hr=0x{hr:X8} pItf=0x{pItf:X}");
            if (hr != 0 || pItf == IntPtr.Zero) { Console.WriteLine("[G6HidProbe] COM activation FAILED"); return; }
            var hid = (ICTHIDRpA)Marshal.GetObjectForIUnknown(pItf);
            uint initHr = hid.Initialize(65543u, 0u);
            Console.WriteLine($"[G6HidProbe] Initialize hr=0x{initHr:X8}");
            int detail = 0;
            uint openHr = hid.Open(0x041E, 0x3256, "", 0, 0, null, ref detail, 0u);
            Console.WriteLine($"[G6HidProbe] Open(041E,3256) hr=0x{openHr:X8} detail={detail}");
            if (openHr == 0 || openHr == 1)
            {
                try
                {
                    var sb = new StringBuilder(257);
                    if (hid.GetProductString(sb, 256, 0) == 0) Console.WriteLine($"ProductString : {sb}");
                    sb = new StringBuilder(257);
                    if (hid.GetSerialNumberString(sb, 256, 0) == 0) Console.WriteLine($"SerialNumber  : {sb}");

                    var fw = new GETDEVICECONTROLPARAM_GetFirmwareVersionString { szFirmwareVersionString = new char[256] };
                    IntPtr p = Marshal.AllocHGlobal(Marshal.SizeOf<GETDEVICECONTROLPARAM_GetFirmwareVersionString>());
                    Marshal.StructureToPtr(fw, p, false);
                    if (hid.GetDeviceControlParam(GETDEVICECONTROL_Msg.GetFirmwareVersionString, p, 0) == 0)
                    {
                        fw = Marshal.PtrToStructure<GETDEVICECONTROLPARAM_GetFirmwareVersionString>(p);
                        string s = new string(fw.szFirmwareVersionString);
                        int z = s.IndexOf('\0'); if (z > 0) s = s.Substring(0, z);
                        Console.WriteLine($"FirmwareVersionString : {s}");
                    }
                    Marshal.FreeHGlobal(p);

                    var fc = new GETDEVICECONTROLPARAM_GetFirmwareConfigurationString { szFirmwareConfigurationString = new char[256] };
                    p = Marshal.AllocHGlobal(Marshal.SizeOf<GETDEVICECONTROLPARAM_GetFirmwareConfigurationString>());
                    Marshal.StructureToPtr(fc, p, false);
                    if (hid.GetDeviceControlParam(GETDEVICECONTROL_Msg.GetFirmwareConfigurationString, p, 0) == 0)
                    {
                        fc = Marshal.PtrToStructure<GETDEVICECONTROLPARAM_GetFirmwareConfigurationString>(p);
                        string s = new string(fc.szFirmwareConfigurationString);
                        int z = s.IndexOf('\0'); if (z > 0) s = s.Substring(0, z);
                        Console.WriteLine($"FirmwareConfigurationString : {s}");
                    }
                    Marshal.FreeHGlobal(p);

                    // Feature masks (num + each)
                    var num = new GETDEVICECONTROLPARAM_GetNumFeatureMask();
                    p = Marshal.AllocHGlobal(Marshal.SizeOf<GETDEVICECONTROLPARAM_GetNumFeatureMask>());
                    Marshal.StructureToPtr(num, p, false);
                    if (hid.GetDeviceControlParam(GETDEVICECONTROL_Msg.GetNumFeatureMask, p, 0) == 0)
                    {
                        num = Marshal.PtrToStructure<GETDEVICECONTROLPARAM_GetNumFeatureMask>(p);
                        Console.WriteLine($"NumFeatureMask : {num.dwNumFeatureMask}");
                        for (byte id = 0; id < Math.Min(num.dwNumFeatureMask, 8); id++)
                        {
                            var fm = new GETDEVICECONTROLPARAM_GetFeatureMask { bFeatureMaskID = id, maskFeature = default };
                            IntPtr p2 = Marshal.AllocHGlobal(Marshal.SizeOf<GETDEVICECONTROLPARAM_GetFeatureMask>());
                            Marshal.StructureToPtr(fm, p2, false);
                            if (hid.GetDeviceControlParam(GETDEVICECONTROL_Msg.GetFeatureMask, p2, 0) == 0)
                            {
                                fm = Marshal.PtrToStructure<GETDEVICECONTROLPARAM_GetFeatureMask>(p2);
                                Console.WriteLine($"FeatureMask[{id}] supported=0x{fm.maskFeature.dwSupportedFeatureBitwiseMask:X8} set=0x{fm.maskFeature.dwSetFeatureBitwiseMask:X8} unavailable=0x{fm.maskFeature.dwCurrentlyUnavailableFeatureBitwiseMask:X8}");
                            }
                            Marshal.FreeHGlobal(p2);
                        }
                    }
                    Marshal.FreeHGlobal(p);

                    // Simple byte-state queries
                    QueryByte(hid, GETDEVICECONTROL_Msg.GetStereoDirectMode, "StereoDirectMode (Direct Mode)");
                    QueryByte(hid, GETDEVICECONTROL_Msg.GetHeadphoneHighGainMode, "HeadphoneHighGainMode");
                    QueryByte(hid, GETDEVICECONTROL_Msg.Get96kHzSPDIFInPassthroughMode, "96kHzSPDIFInPassthrough");
                    QueryByte(hid, GETDEVICECONTROL_Msg.GetSPDIFOutDirectMode, "SPDIFOutDirectMode");
                    QueryByte(hid, GETDEVICECONTROL_Msg.GetPowerAdapterWattageMode, "PowerAdapterWattageMode");
                    QueryByte(hid, GETDEVICECONTROL_Msg.GetSpeakersHRTFMode, "SpeakersHRTFMode");
                    QueryByte(hid, GETDEVICECONTROL_Msg.GetAutoSleepMode, "AutoSleepMode");
                    QueryByte(hid, GETDEVICECONTROL_Msg.GetSpeakersConfigAvailable, "SpeakersConfigAvailable");
                    QueryByte(hid, GETDEVICECONTROL_Msg.GetJackAvailable, "JackAvailable");
                    QueryByte(hid, GETDEVICECONTROL_Msg.GetJackState, "JackState");
                    QueryUint(hid, GETDEVICECONTROL_Msg.GetSpeakersConfig, "SpeakersConfig");
                    QueryUint(hid, GETDEVICECONTROL_Msg.GetNumMCU, "NumMCU");
                    QueryUint(hid, GETDEVICECONTROL_Msg.GetMCUType, "MCUType");
                    QueryUint(hid, GETDEVICECONTROL_Msg.GetMCUVersion, "MCUVersion");
                }
                finally
                {
                    hid.Close(0);
                }
            }
            hid.Shutdown(0);
            Marshal.Release(pItf);
            Console.WriteLine("[G6HidProbe] done");
        }

        static void QueryByte(ICTHIDRpA hid, GETDEVICECONTROL_Msg msg, string name)
        {
            try
            {
                IntPtr p = Marshal.AllocHGlobal(1);
                Marshal.WriteByte(p, 0xFF);
                if (hid.GetDeviceControlParam(msg, p, 0) == 0)
                    Console.WriteLine($"{name,-34} = {Marshal.ReadByte(p)}");
                else
                    Console.WriteLine($"{name,-34} = <query failed>");
                Marshal.FreeHGlobal(p);
            }
            catch (Exception ex) { Console.WriteLine($"{name,-34} = <exception {ex.Message}>"); }
        }

        static void QueryUint(ICTHIDRpA hid, GETDEVICECONTROL_Msg msg, string name)
        {
            try
            {
                IntPtr p = Marshal.AllocHGlobal(4);
                Marshal.WriteInt32(p, -1);
                if (hid.GetDeviceControlParam(msg, p, 0) == 0)
                    Console.WriteLine($"{name,-34} = 0x{Marshal.ReadInt32(p):X8} ({Marshal.ReadInt32(p)})");
                else
                    Console.WriteLine($"{name,-34} = <query failed>");
                Marshal.FreeHGlobal(p);
            }
            catch (Exception ex) { Console.WriteLine($"{name,-34} = <exception {ex.Message}>"); }
        }
    }
}
