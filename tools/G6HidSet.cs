// G6HidSet - toggle app-level settings on the Sound BlasterX G6 via CTHIDRpA (same calls Sound Blaster Command makes).
// Usage:
//   G6HidSet spdifdirect 0|1     -> SETDEVICECONTROL_Msg_SetSPDIFOutDirectMode (9)
//   G6HidSet stereodirect 0|1    -> SETDEVICECONTROL_Msg_SetStereoDirectMode (1)
//   G6HidSet query               -> read back all relevant states
// State is persisted by the device firmware like a front-panel/app toggle; fully reversible.
using System;
using System.Runtime.InteropServices;
using System.Text;

namespace G6HidProbe
{
    internal static class Program
    {
        static Guid CLSID = new Guid("335871C5-0D55-4FF6-9CE9-F5A3479F1D1F");
        static Guid IID   = new Guid("66DE3850-3DBF-4FD7-956F-3B0E0A5AD56C");

        enum GETDEVICECONTROL_Msg : uint
        {
            GetStereoDirectMode = 10,
            GetSPDIFOutDirectMode = 20,
            GetFirmwareVersionString = 35,
        }

        enum SETDEVICECONTROL_Msg : uint
        {
            SetStereoDirectMode = 1,
            SetSPDIFOutDirectMode = 9,
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        struct GETDEVICECONTROLPARAM_GetFirmwareVersionString
        {
            [MarshalAs(UnmanagedType.ByValArray, SizeConst = 256)]
            public char[] szFirmwareVersionString;
        }

        [StructLayout(LayoutKind.Sequential)]
        struct SETDEVICECONTROLPARAM_SetStereoDirectMode { public byte bState; }
        [StructLayout(LayoutKind.Sequential)]
        struct SETDEVICECONTROLPARAM_SetSPDIFOutDirectMode { public byte bState; }

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
            [PreserveSig] uint SetDeviceControlParam(SETDEVICECONTROL_Msg msgSetDeviceControl, IntPtr lparam, uint dwFlag);
        }

        static class CTIntrfu
        {
            [DllImport("CTIntrfu.dll", CharSet = CharSet.Unicode)]
            public static extern int CTCreateInstanceEx(ref Guid rclsid, IntPtr pUnkOuter, uint dwClsContext, ref Guid riid, IntPtr pServerInfo, IntPtr pcn, [MarshalAs(UnmanagedType.LPWStr)] string lpcszLibFile, IntPtr pReserved, out IntPtr ppv);
        }

        static ICTHIDRpA Connect(out IntPtr pItf, out int openDetail)
        {
            string libFile = @"C:\Program Files (x86)\Creative\Sound Blaster Command\Platform\CTHIDRpA.dll";
            int hr = CTIntrfu.CTCreateInstanceEx(ref CLSID, IntPtr.Zero, 0, ref IID, IntPtr.Zero, IntPtr.Zero, libFile, IntPtr.Zero, out pItf);
            if (hr != 0 || pItf == IntPtr.Zero) throw new Exception($"CTCreateInstanceEx hr=0x{hr:X8}");
            var hid = (ICTHIDRpA)Marshal.GetObjectForIUnknown(pItf);
            uint initHr = hid.Initialize(65543u, 0u);
            if (initHr != 0) throw new Exception($"Initialize hr=0x{initHr:X8}");
            openDetail = 0;
            uint openHr = hid.Open(0x041E, 0x3256, "", 0, 0, null, ref openDetail, 0u);
            if (openHr != 0 && openHr != 1) throw new Exception($"Open hr=0x{openHr:X8}");
            return hid;
        }

        static byte QueryByte(ICTHIDRpA hid, GETDEVICECONTROL_Msg msg)
        {
            IntPtr p = Marshal.AllocHGlobal(1);
            Marshal.WriteByte(p, 0xFF);
            try
            {
                if (hid.GetDeviceControlParam(msg, p, 0) != 0) return 0xFF;
                return Marshal.ReadByte(p);
            }
            finally { Marshal.FreeHGlobal(p); }
        }

        static void Main(string[] args)
        {
            if (args.Length < 1) { Console.WriteLine("usage: G6HidSet <spdifdirect|stereodirect> <0|1> | query"); return; }
            IntPtr pItf;
            int openDetail;
            ICTHIDRpA hid;
            try { hid = Connect(out pItf, out openDetail); }
            catch (Exception ex) { Console.WriteLine($"connect failed: {ex.Message}"); return; }

            try
            {
                if (args[0] == "query")
                {
                    Console.WriteLine($"StereoDirectMode  = {QueryByte(hid, GETDEVICECONTROL_Msg.GetStereoDirectMode)}");
                    Console.WriteLine($"SPDIFOutDirectMode = {QueryByte(hid, GETDEVICECONTROL_Msg.GetSPDIFOutDirectMode)}");
                    return;
                }
                if (args.Length < 2) { Console.WriteLine("missing value"); return; }
                byte val = byte.Parse(args[1]);
                SETDEVICECONTROL_Msg msg;
                int structSize;
                if (args[0] == "spdifdirect") { msg = SETDEVICECONTROL_Msg.SetSPDIFOutDirectMode; structSize = 1; }
                else if (args[0] == "stereodirect") { msg = SETDEVICECONTROL_Msg.SetStereoDirectMode; structSize = 1; }
                else { Console.WriteLine("unknown target"); return; }

                IntPtr p = Marshal.AllocHGlobal(structSize);
                Marshal.WriteByte(p, val);
                uint hr = hid.SetDeviceControlParam(msg, p, 0);
                Marshal.FreeHGlobal(p);
                Console.WriteLine($"SetDeviceControlParam({msg}, {val}) hr=0x{hr:X8}");
                System.Threading.Thread.Sleep(700);
                if (msg == SETDEVICECONTROL_Msg.SetSPDIFOutDirectMode)
                    Console.WriteLine($"readback SPDIFOutDirectMode = {QueryByte(hid, GETDEVICECONTROL_Msg.GetSPDIFOutDirectMode)}");
                else
                    Console.WriteLine($"readback StereoDirectMode  = {QueryByte(hid, GETDEVICECONTROL_Msg.GetStereoDirectMode)}");
            }
            finally
            {
                hid.Close(0);
                hid.Shutdown(0);
                Marshal.Release(pItf);
            }
        }
    }
}
