// G6SoundCoreProbe - enumerate the G6's SoundCore params live via SndCrUSB's ISoundCore COM server.
// READ-ONLY by design: only GetParamValue/GetParamInfo/EnumFeatures/EnumContexts/GetParamValueEx_unsafe.
// Uses CTIntrfu.CTCreateInstanceEx with an explicit lib path (no registry activation needed),
// exactly like the proven G6HidExplore tool. Must build x86 (SndCrUSB is 32-bit).
//
// Usage:
//   G6SoundCoreProbe filters   -> dump DACFilterTypeSelect (21) + EnumDACFilterTypeSelect (22) of MalcolmDeviceControl
//   G6SoundCoreProbe param F P -> GetParamInfo + GetParamValue for feature F param P (both decimal or 0x..)
using System;
using System.Runtime.InteropServices;
using System.Text;

namespace G6SoundCoreProbe
{
    internal static class Program
    {
        static Guid CLSID_SndCrUSB = new Guid("495E4C24-85ED-4f19-885E-C2D01D7EA26C");
        static Guid IID_ISoundCore = new Guid("6111E7C4-3EA4-47ED-B074-C638875282C4");

        // vtable order (ISoundCore.cs, InterfaceIsIUnknown, no PreserveSig -> HRESULTs translated):
        // 0 QueryInterface..3 IUnknown, then:
        //  4 BindHardware,  5 EnumContexts,  6 GetContextInfo,  7 GetContext,  8 SetContext,
        //  9 EnumFeatures, 10 GetFeatureInfo, 11 EnumParams,   12 GetParamInfo,
        // 13 GetParamValue, 14 SetParamValue, 15 GetParamValueEx, 16 SetParamValueEx,
        // 17 ValidateParamValue, 18 ValidateParamValueEx, 19 GetParamValueEx_unsafe, 20 SetParamValueEx_unsafe,
        // 21 ValidateParamValueEx_unsafe  (+ IEventNotify if the server also implements it)
        [ComImport, Guid("6111E7C4-3EA4-47ED-B074-C638875282C4"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        interface ISoundCore
        {
            void BindHardware(ref _stHardwareInfo hardwareInfo);
            void EnumContexts(uint index, out _stContextInfo contextInfo);
            void GetContextInfo(uint contextId, out _stContextInfo contextInfo);
            void GetContext(out uint contextId);
            void SetContext(uint contextId, uint restoreState);
            void EnumFeatures(uint contextId, uint index, out _stFeatureInfo featureInfo);
            void GetFeatureInfo(uint contextId, uint featureId, out _stFeatureInfo featureInfo);
            void EnumParams(uint contextId, uint index, uint featureId, out _stParamInfo paramInfo);
            void GetParamInfo(_stParam param, out _stParamInfo paramInfo);
            void GetParamValue(_stParam param, out _stParamValue paramValue);
            // vtable slots after GetParamValue (unreferenced here): SetParamValue, GetParamValueEx,
            // SetParamValueEx, ValidateParamValue, ValidateParamValueEx,
            // GetParamValueEx_unsafe, SetParamValueEx_unsafe, ValidateParamValueEx_unsafe,
            // then IEventNotify::RegisterEventCallback / UnregisterEventCallback (separate interface).
        }

        [StructLayout(LayoutKind.Sequential, Pack = 4)]
        struct _PARAM_DATA
        {
            public uint paramSize;
            public IntPtr paramData;
        }

        [StructLayout(LayoutKind.Sequential, Pack = 4)]
        struct _stHardwareInfo
        {
            public uint infoType;            // eHardwareInfoType_EndpointId = 0
            [MarshalAs(UnmanagedType.ByValArray, SizeConst = 260)] public ushort[] endpointId;
        }

        [StructLayout(LayoutKind.Sequential, Pack = 4)]
        struct _stParam
        {
            public uint paramId;
            public uint featureId;
            public uint contextId;
        }

        [StructLayout(LayoutKind.Sequential, Pack = 4)]
        struct _stParamValue
        {
            public uint paramType;
            public uint raw;                  // union float/bool/dword/long
        }

        [StructLayout(LayoutKind.Sequential, Pack = 4)]
        struct _stContextInfo
        {
            public uint contextId;
            [MarshalAs(UnmanagedType.ByValArray, SizeConst = 32)] public sbyte[] szDescription;
        }

        [StructLayout(LayoutKind.Sequential, Pack = 4)]
        struct _stFeatureInfo
        {
            public uint featureId;
            [MarshalAs(UnmanagedType.ByValArray, SizeConst = 32)] public sbyte[] szDescription;
            [MarshalAs(UnmanagedType.ByValArray, SizeConst = 16)] public sbyte[] szVersion;
        }

        [StructLayout(LayoutKind.Sequential, Pack = 4)]
        struct _stParamInfo
        {
            public _stParam paramId;
            public uint paramType;
            public uint paramDataSize;
            public _stParamValue minVal;
            public _stParamValue maxVal;
            public _stParamValue stepSize;
            public _stParamValue defaultVal;
            public uint paramAttrib;
            [MarshalAs(UnmanagedType.ByValArray, SizeConst = 32)] public sbyte[] szDescription;
        }

        static class CTIntrfu
        {
            [DllImport("CTIntrfu.dll", CharSet = CharSet.Unicode)]
            public static extern int CTCreateInstanceEx(ref Guid rclsid, IntPtr pUnkOuter, uint dwClsContext,
                ref Guid riid, IntPtr pServerInfo, IntPtr pcn, [MarshalAs(UnmanagedType.LPWStr)] string lpcszLibFile,
                IntPtr pReserved, out IntPtr ppv);
        }

        static string Sz(sbyte[] b)
        {
            int n = Array.IndexOf(b, (sbyte)0);
            if (n < 0) return "";
            byte[] ub = new byte[n];
            Buffer.BlockCopy(b, 0, ub, 0, n);
            return Encoding.ASCII.GetString(ub);
        }

        static string CodeName(ushort c) => c switch
        {
            0 => "FastRolloff",
            1 => "SlowRolloff",
            2 => "MinimumPhase",
            3 => "FastRolloffMinimumPhase",
            4 => "SlowRolloffMinimumPhase",
            5 => "NonOverSampling",
            6 => "FastRolloffLinearPhase",
            7 => "SlowRolloffLinearPhase",
            8 => "ApodizingFastRolloff",
            9 => "HybridFastRolloff",
            10 => "BrickWall",
            _ => $"UNKNOWN({c})"
        };

        static void DumpUnused() { }

        static int Main(string[] args)
        {
            const uint F_MALCOLM = 0x01000001;   // eFeature_System_MalcolmDeviceControl
            const uint F_PROCCFG = 0x01000002;    // eFeature_System_ProcessingControl
            string libFile = @"C:\Program Files (x86)\Creative\Sound Blaster Command\Platform\SndCrUSB.DLL";
            IntPtr pItf;
            int hr = CTIntrfu.CTCreateInstanceEx(ref CLSID_SndCrUSB, IntPtr.Zero, 0, ref IID_ISoundCore,
                IntPtr.Zero, IntPtr.Zero, libFile, IntPtr.Zero, out pItf);
            if (hr != 0 || pItf == IntPtr.Zero) { Console.WriteLine($"CTCreateInstanceEx hr=0x{hr:X8}"); return 1; }
            ISoundCore sc = (ISoundCore)Marshal.GetObjectForIUnknown(pItf);

            try
            {
                // Bind to the G6 speakers endpoint (from MMDeviceEnumerator live query)
                _stHardwareInfo hw = new _stHardwareInfo();
                hw.infoType = 0;
                hw.endpointId = new ushort[260];
                string ep = "{0.0.0.00000000}.{b14c16b8-7fd2-492f-abbe-63ad5e3634e7}";
                char[] chars = ep.ToCharArray();
                for (int i = 0; i < chars.Length; i++) hw.endpointId[i] = chars[i];
                sc.BindHardware(ref hw);
                Console.WriteLine("BindHardware OK");

                // Enumerate contexts
                Console.WriteLine("\n== Contexts ==");
                for (uint i = 0; ; i++)
                {
                    try
                    {
                        _stContextInfo ci;
                        sc.EnumContexts(i, out ci);
                        Console.WriteLine($"  ctx {ci.contextId}: {Sz(ci.szDescription)}");
                    }
                    catch (COMException) { break; }
                }

                uint ctx;
                sc.GetContext(out ctx);
                Console.WriteLine($"\nCurrent context: {ctx}");

                // Enumerate features of the current context
                Console.WriteLine("\n== Features (current context) ==");
                for (uint i = 0; ; i++)
                {
                    try
                    {
                        _stFeatureInfo fi;
                        sc.EnumFeatures(ctx, i, out fi);
                        Console.WriteLine($"  0x{fi.featureId:X8}: {Sz(fi.szDescription)}");
                    }
                    catch (COMException) { break; }
                }

                // DACFilterTypeSelect (MalcolmDeviceControl param 21) + enum list (param 22)
                Console.WriteLine("\n== DAC filter params (feature 0x01000001) ==");
                for (uint i = 0; ; i++)
                {
                    try
                    {
                        _stParamInfo pi;
                        sc.EnumParams(ctx, i, F_MALCOLM, out pi);
                        Console.WriteLine($"  param {pi.paramId.paramId}: type={pi.paramType} size={pi.paramDataSize} '{Sz(pi.szDescription)}'");
                    }
                    catch (COMException) { break; }
                }

                // Current filter value (param 21)
                try
                {
                    _stParam p21 = new _stParam { paramId = 21, featureId = F_MALCOLM, contextId = ctx };
                    _stParamValue v;
                    sc.GetParamValue(p21, out v);
                    Console.WriteLine($"\nDACFilterTypeSelect(21) = raw 0x{v.raw:X8} (type {v.paramType})");
                }
                catch (Exception ex) { Console.WriteLine($"GetParamValue(21) failed: {ex.Message}"); }

                // Param info for 21/22 (min/max/step/default reveal the enum)
                foreach (uint pn in new uint[] { 21, 22 })
                {
                    try
                    {
                        _stParam p = new _stParam { paramId = pn, featureId = F_MALCOLM, contextId = ctx };
                        _stParamInfo pi;
                        sc.GetParamInfo(p, out pi);
                        Console.WriteLine($"\nParamInfo({pn}): type={pi.paramType} size={pi.paramDataSize} min=0x{pi.minVal.raw:X8} max=0x{pi.maxVal.raw:X8} step=0x{pi.stepSize.raw:X8} default=0x{pi.defaultVal.raw:X8} desc='{Sz(pi.szDescription)}'");
                    }
                    catch (Exception ex) { Console.WriteLine($"GetParamInfo({pn}) failed: {ex.Message}"); }
                }

                // Variable-size enum list (param 22): raw vtable call to GetParamValueEx_unsafe.
                // _PARAM_DATA = { uint paramSize; IntPtr paramData } passed by ref.
                // Vtable layout for InterfaceIsIUnknown: [0]QI [1]AddRef [2]Release, then method slots in order.
                try
                {
                    unsafe
                    {
                        IntPtr pUnk = Marshal.GetIUnknownForObject(sc);
                        uint** vt = (uint**)pUnk;
                        uint* slots = *vt;
                        // slot indices after 3 (IUnknown):
                        // 0-based vtable: 0 QI, 1 AddRef, 2 Release, 3 BindHardware, 4 EnumContexts,
                        // 5 GetContextInfo, 6 GetContext, 7 SetContext, 8 EnumFeatures, 9 GetFeatureInfo,
                        // 10 EnumParams, 11 GetParamInfo, 12 GetParamValue, 13 SetParamValue,
                        // 14 GetParamValueEx, 15 SetParamValueEx, 16 ValidateParamValue,
                        // 17 ValidateParamValueEx, 18 GetParamValueEx_unsafe, 19 SetParamValueEx_unsafe
                        uint* pfn = &slots[18]; // GetParamValueEx_unsafe — READ (slots[19] is the WRITE fn!)
                        delegate* unmanaged[Stdcall]<IntPtr, _stParam, ref _PARAM_DATA, int> getExUnsafe;
                        getExUnsafe = (delegate* unmanaged[Stdcall]<IntPtr, _stParam, ref _PARAM_DATA, int>)(*pfn);

                        _stParam p22 = new _stParam { paramId = 22, featureId = F_MALCOLM, contextId = ctx };

                        // Iterate the enumeration like the .NET code does: pre-write index at paramData[0],
                        // call GetParamValueEx_unsafe, read back { int index; <data> } until it fails.
                        Console.WriteLine("\nEnumerating filter list (index-prewrite pattern):");
                        for (uint idx = 0; idx < 16; idx++)
                        {
                            byte[] scratch = new byte[64];
                            _PARAM_DATA pd2 = new _PARAM_DATA { paramSize = 8, paramData = Marshal.AllocHGlobal(64) };
                            try
                            {
                                Marshal.WriteInt32(pd2.paramData, 0, (int)idx);   // index in
                                Marshal.WriteInt32(pd2.paramData, 4, 0);            // data slot zeroed
                                int hrIt = getExUnsafe(pUnk, p22, ref pd2);
                                if (hrIt < 0) { Console.WriteLine($"  idx {idx}: end of list (hr=0x{hrIt:X8})"); break; }
                                int retIdx = Marshal.ReadInt32(pd2.paramData, 0);
                                ushort code = (ushort)(Marshal.ReadInt32(pd2.paramData, 4) & 0xFFFF);
                                string nm = CodeName(code);
                                Console.WriteLine($"  idx {idx}: hr=0x{hrIt:X8} retIdx={retIdx} code={code} ({nm})");
                            }
                            finally { Marshal.FreeHGlobal(pd2.paramData); }
                        }
                    }
                }
                catch (Exception ex) { Console.WriteLine($"Ex dump failed: {ex.Message}"); }
                return 0;
            }
            catch (Exception ex)
            {
                Console.WriteLine($"ERROR: {ex.Message}");
                return 1;
            }
        }
    }
}
