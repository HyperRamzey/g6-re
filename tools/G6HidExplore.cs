// G6HidExplore - probe UNUSED firmware features safely (read-mostly).
// Uses the exact same verified connection method as G6HidSet (CTIntrfu.CTCreateInstanceEx + CTHIDRpA).
// Usage:
//   G6HidExplore query                  -> read-only sweep of safe GETs
//   G6HidExplore spdif96 get | set 0|1  -> 96kHz SPDIF-In passthrough (reversible app-level setting)
//   G6HidExplore localstore list        -> LocalStore data IDs available (read-only)
//   G6HidExplore localstore get ID      -> read one local-store slot (read-only)
//   G6HidExplore jack|displaytime|autosleep|audio|i2cmaster|malcolm|wattage -> single GET
// NO flash commands, NO factory reset, NO restore-default implemented here by design.
using System;
using System.Runtime.InteropServices;
using System.Text;

namespace G6HidExplore
{
    internal static class Program
    {
        static Guid CLSID = new Guid("335871C5-0D55-4FF6-9CE9-F5A3479F1D1F");
        static Guid IID = new Guid("66DE3850-3DBF-4FD7-956F-3B0E0A5AD56C");

        // GETDEVICECONTROL_Msg (from decompiled CTHIDRpALibrary.cs)
        enum GET : uint
        {
            Button = 1, Jack = 2, FeatureMask = 3, NumI2CAddressOverride = 4, I2CAddressOverride = 5,
            NumProfile = 6, ProfileInfo = 7, I2CMasterStatus = 8, MalcolmParameterCustomization = 9,
            StereoDirectMode = 10, HeadphoneHighGainMode = 11, MicBoostAssociatedMic = 12,
            MicBoostRange = 13, MicBoostValue = 14, SPdif96k = 15, SpeakersConfigAvailable = 16,
            SpeakersConfig = 17, LocalStoreAvailable = 18, LocalStore = 19, SPDIFOutDirectMode = 20,
            BatteryLevel = 21, BatteryStatus = 22, JackAvailable = 23, JackState = 24,
            ActiveProfile = 25, DefaultProfile = 26, AudioPromptControl = 27,
            SupportedVoiceFXType = 28, VoiceFXPresetID = 29, NumMCU = 30, MCUType = 31,
            MCUVersion = 32, PowerAdapterWattageMode = 33, DeviceDisplayTime = 34,
            VoiceFXPreviewState = 36, ProfileData = 51, SpeakersHRTFMode = 52,
            AutoSleepMode = 55, ProfileVisibility = 76,
        }

        enum SET : uint
        {
            SetButtonState = 0,
            Set96kHzSPDIFInPassthroughMode = 6,
            SetSpeakersHRTFMode = 30,
            SetHeadphoneHighGainMode = 2,
        }

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
            [PreserveSig] uint GetDeviceControlParam(GET msgGetDeviceControl, IntPtr lparam, uint dwFlag);
            [PreserveSig] uint GetProductAttributes(ulong ulDeviceIndex, ref string path, ref ushort vid, ref ushort pid, ref ushort ver, uint dwFlag);
            [PreserveSig] uint SetVT1728I2CPassthroughSCPCommandParam(ref byte a, uint dwFlag);
            [PreserveSig] uint SetDeviceControlParam(SET msgSetDeviceControl, IntPtr lparam, uint dwFlag);
        }

        static class CTIntrfu
        {
            [DllImport("CTIntrfu.dll", CharSet = CharSet.Unicode)]
            public static extern int CTCreateInstanceEx(ref Guid rclsid, IntPtr pUnkOuter, uint dwClsContext, ref Guid riid, IntPtr pServerInfo, IntPtr pcn, [MarshalAs(UnmanagedType.LPWStr)] string lpcszLibFile, IntPtr pReserved, out IntPtr ppv);
        }

        static ICTHIDRpA Connect(out IntPtr pItf)
        {
            string libFile = @"C:\Program Files (x86)\Creative\Sound Blaster Command\Platform\CTHIDRpA.dll";
            int hr = CTIntrfu.CTCreateInstanceEx(ref CLSID, IntPtr.Zero, 0, ref IID, IntPtr.Zero, IntPtr.Zero, libFile, IntPtr.Zero, out pItf);
            if (hr != 0 || pItf == IntPtr.Zero) throw new Exception($"CTCreateInstanceEx hr=0x{hr:X8}");
            var hid = (ICTHIDRpA)Marshal.GetObjectForIUnknown(pItf);
            uint initHr = hid.Initialize(65543u, 0u);
            if (initHr != 0) throw new Exception($"Initialize hr=0x{initHr:X8}");
            int openDetail = 0;
            uint openHr = hid.Open(0x041E, 0x3256, "", 0, 0, null, ref openDetail, 0u);
            if (openHr != 0 && openHr != 1) throw new Exception($"Open hr=0x{openHr:X8} detail={openDetail}");
            return hid;
        }

        static string TryGetBytes(ICTHIDRpA hid, GET msg, int size)
        {
            IntPtr p = Marshal.AllocHGlobal(size);
            try
            {
                if (hid.GetDeviceControlParam(msg, p, 0) != 0) return "FAILED";
                byte[] b = new byte[size];
                Marshal.Copy(p, b, 0, size);
                string s = BitConverter.ToString(b, 0, Math.Min(size, 32));
                if (msg == GET.StereoDirectMode || msg == GET.SPDIFOutDirectMode || msg == GET.SPdif96k
                    || msg == GET.HeadphoneHighGainMode || msg == GET.SpeakersHRTFMode)
                    return $"{b[0]} (raw {s})";
                return s;
            }
            finally { Marshal.FreeHGlobal(p); }
        }

        static void Main(string[] args)
        {
            IntPtr pItf;
            ICTHIDRpA hid;
            try { hid = Connect(out pItf); }
            catch (Exception ex) { Console.WriteLine($"connect failed: {ex.Message}"); return; }

            string cmd = args.Length > 0 ? args[0].ToLowerInvariant() : "query";
            try
            {
                switch (cmd)
                {
                    case "query":
                        Console.WriteLine($"FeatureMask                : {TryGetBytes(hid, GET.FeatureMask, 16)}");
                        Console.WriteLine($"96kSPDIFInPassthrough      : {TryGetBytes(hid, GET.SPdif96k, 1)}");
                        Console.WriteLine($"SpeakersHRTFMode           : {TryGetBytes(hid, GET.SpeakersHRTFMode, 4)}");
                        Console.WriteLine($"I2CMasterStatus            : {TryGetBytes(hid, GET.I2CMasterStatus, 8)}");
                        Console.WriteLine($"MalcolmParamCustomization  : {TryGetBytes(hid, GET.MalcolmParameterCustomization, 16)}");
                        Console.WriteLine($"NumI2CAddressOverride      : {TryGetBytes(hid, GET.NumI2CAddressOverride, 4)}");
                        Console.WriteLine($"I2CAddressOverride         : {TryGetBytes(hid, GET.I2CAddressOverride, 16)}");
                        Console.WriteLine($"JackState                  : {TryGetBytes(hid, GET.JackState, 8)}");
                        Console.WriteLine($"JackAvailable              : {TryGetBytes(hid, GET.JackAvailable, 8)}");
                        Console.WriteLine($"DeviceDisplayTime          : {TryGetBytes(hid, GET.DeviceDisplayTime, 4)}");
                        Console.WriteLine($"AutoSleepMode              : {TryGetBytes(hid, GET.AutoSleepMode, 4)}");
                        Console.WriteLine($"AudioPromptControl         : {TryGetBytes(hid, GET.AudioPromptControl, 8)}");
                        Console.WriteLine($"PowerAdapterWattageMode    : {TryGetBytes(hid, GET.PowerAdapterWattageMode, 4)}");
                        Console.WriteLine($"BatteryLevel               : {TryGetBytes(hid, GET.BatteryLevel, 4)}");
                        Console.WriteLine($"NumMCU/MCUType/MCUVersion  : {TryGetBytes(hid, GET.NumMCU, 4)} {TryGetBytes(hid, GET.MCUType, 4)} {TryGetBytes(hid, GET.MCUVersion, 4)}");
                        Console.WriteLine($"ProfileVisibility          : {TryGetBytes(hid, GET.ProfileVisibility, 16)}");
                        Console.WriteLine($"LocalStoreAvailable        : {LocalStoreList(hid)}");
                        break;

                    case "hrtf":
                        if (args.Length >= 3 && args[1] == "set")
                        {
                            byte val = byte.Parse(args[2]);
                            IntPtr p = Marshal.AllocHGlobal(1);
                            Marshal.WriteByte(p, val);
                            uint hr = hid.SetDeviceControlParam(SET.SetSpeakersHRTFMode, p, 0);
                            Marshal.FreeHGlobal(p);
                            Console.WriteLine($"SetSpeakersHRTFMode({val}) hr=0x{hr:X8}");
                            System.Threading.Thread.Sleep(500);
                        }
                        Console.WriteLine($"SpeakersHRTFMode now: {TryGetBytes(hid, GET.SpeakersHRTFMode, 4)}");
                        break;

                    case "gain":
                        if (args.Length >= 3 && args[1] == "set")
                        {
                            byte val = byte.Parse(args[2]);
                            IntPtr p = Marshal.AllocHGlobal(1);
                            Marshal.WriteByte(p, val);
                            uint hr = hid.SetDeviceControlParam(SET.SetHeadphoneHighGainMode, p, 0);
                            Marshal.FreeHGlobal(p);
                            Console.WriteLine($"SetHeadphoneHighGainMode({val}) hr=0x{hr:X8}");
                            System.Threading.Thread.Sleep(500);
                        }
                        Console.WriteLine($"HeadphoneHighGainMode now: {TryGetBytes(hid, GET.HeadphoneHighGainMode, 1)}");
                        break;

                    case "spdif96":
                        if (args.Length >= 3 && args[1] == "set")
                        {
                            byte val = byte.Parse(args[2]);
                            IntPtr p = Marshal.AllocHGlobal(1);
                            Marshal.WriteByte(p, val);
                            uint hr = hid.SetDeviceControlParam(SET.Set96kHzSPDIFInPassthroughMode, p, 0);
                            Marshal.FreeHGlobal(p);
                            Console.WriteLine($"Set96kHzSPDIFInPassthrough({val}) hr=0x{hr:X8}");
                            System.Threading.Thread.Sleep(500);
                        }
                        Console.WriteLine($"96kSPDIFInPassthrough now: {TryGetBytes(hid, GET.SPdif96k, 1)}");
                        break;

                    case "localstore":
                        if (args.Length >= 3 && args[1] == "get")
                        {
                            byte id = byte.Parse(args[2]);
                            IntPtr p = Marshal.AllocHGlobal(300);
                            Marshal.WriteByte(p, id);
                            if (hid.GetDeviceControlParam(GET.LocalStore, p, 0) == 0)
                            {
                                byte count = Marshal.ReadByte(p, 1);
                                byte[] data = new byte[255];
                                Marshal.Copy(p + 2, data, 0, 255);
                                var sb = new StringBuilder();
                                int n = Math.Min((int)count, 64);
                                for (int i = 0; i < n; i++) sb.Append(data[i].ToString("X2")).Append(' ');
                                Console.WriteLine($"localstore[{id}] len={count}: {sb}");
                            }
                            else Console.WriteLine($"get {id} FAILED");
                            Marshal.FreeHGlobal(p);
                        }
                        else
                            Console.WriteLine(LocalStoreList(hid));
                        break;

                    default:
                        Console.WriteLine("cmds: query | hrtf get|set 0|1 | gain get|set 0|1 | spdif96 get|set 0|1 | localstore list|get ID");
                        break;
                }
            }
            finally
            {
                hid.Close(0);
                hid.Shutdown(0);
                Marshal.Release(pItf);
                Console.WriteLine("[G6HidExplore] done");
            }
        }

        static string LocalStoreList(ICTHIDRpA hid)
        {
            IntPtr p = Marshal.AllocHGlobal(300);
            try
            {
                if (hid.GetDeviceControlParam(GET.LocalStoreAvailable, p, 0) != 0) return "FAILED";
                byte n = Marshal.ReadByte(p);
                byte[] ids = new byte[255];
                Marshal.Copy(p + 1, ids, 0, 255);
                var sb = new StringBuilder();
                int cnt = Math.Min((int)n, 64);
                for (int i = 0; i < cnt; i++) sb.Append(ids[i]).Append(' ');
                return $"count={n} ids=[{sb}]";
            }
            finally { Marshal.FreeHGlobal(p); }
        }
    }
}
