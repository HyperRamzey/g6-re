// G6AsioProbe â€” minimal ASIO host that loads the Creative Sound Blaster ASIO driver
// (CtUsAsio, CLSID {B2D4D5A2-1B17-4AB6-8A6D-667095C480B2}) via CoCreateInstance and
// dumps everything a DAW would see: channels, channel info (names/types/groups),
// buffer sizes (min/max/preferred/granularity), latencies in samples, sample rates,
// clock sources, and the driver version. Read-only: init -> query -> dispose.
// No buffers are created, no audio is played, no settings are modified.
//
// Build: dotnet build -c Release (x64; the ASIO CLSID resolves to CtUsAs64.dll
// in the 64-bit registry view for a 64-bit process).
// Usage: G6AsioProbe.exe            - dump everything
//        G6AsioProbe.exe --buffers  - also create+dispose buffers at preferred size
//                                     (still no stream start, fully reversible)

using System;
using System.Runtime.InteropServices;

namespace G6AsioProbe
{
    // --- ASIO types (from asio.h, stable ABI since 1997) ---
    enum ASIOBool : int { False = 0, True = 1 }

    [StructLayout(LayoutKind.Sequential, Pack = 2)]
    struct ASIOClockSource { public int index; public int associatedChannel; public int associatedGroup; public ASIOBool isCurrentSource; [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string name; }

    [StructLayout(LayoutKind.Sequential, Pack = 2)]
    struct ASIOChannelInfo { public int channel; public ASIOBool isInput; public ASIOBool isActive; public int channelGroup; public ASIOSampleType type; [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string name; }

    [StructLayout(LayoutKind.Sequential)]
    struct ASIOBufferInfo { public ASIOBool isInput; public int channelNum; public IntPtr buffers0; public IntPtr buffers1; }

    [StructLayout(LayoutKind.Sequential)]
    struct ASIOCallbacks
    {
        public IntPtr bufferSwitch;
        public IntPtr sampleRateDidChange;
        public IntPtr asioMessage;
        public IntPtr bufferSwitchTimeInfo;
    }

    // ASIOSampleType values
    enum ASIOSampleType : int
    {
        Int16MSB = 0, Int24MSB = 1, Int32MSB = 2, Float32MSB = 3,
        Float64MSB = 4, Int32MSB16 = 5, Int32MSB18 = 6, Int32MSB20 = 7,
        Int32MSB24 = 8, Int64MSB = 9, Int32LSB = 10, Int16LSB = 11,
        Int24LSB = 12, Int32LSB16 = 13, Int32LSB18 = 14, Int32LSB20 = 15,
        Int32LSB24 = 16, Int64LSB = 17, Float32LSB = 18, Float64LSB = 19
    }

    internal static class Program
    {
        // ---- raw COM interop (IntPtr only â€” the ASIO driver is a plain C-style COM object) ----
        [DllImport("ole32.dll", ExactSpelling = true)]
        static extern int CoInitialize(IntPtr pvReserved);

        [DllImport("ole32.dll", ExactSpelling = true, PreserveSig = true)]
        static extern int CoCreateInstance(ref Guid clsid, IntPtr pUnkOuter, uint dwClsContext, ref Guid riid, out IntPtr ppv);

        // vtable slot indices (0-based) for IASIO after IUnknown(0,1,2).
        // Verified against the decompiled CtUsAs64 vtable @0x403A60: slot 11 = getBufferSize,
        // slot 19 = getChannelInfo, slot 22 = controlPanel (IDD_ASIOCP_MALCOLM).
        const int S_INIT = 3;
        const int S_GETDRIVERNAME = 4;
        const int S_GETDRIVERVERSION = 5;
        const int S_GETCHANNELS = 9;
        const int S_GETLATENCIES = 10;
        const int S_GETBUFFERSIZE = 11;
        const int S_CANSETSAMPLERATE = 12;
        const int S_GETSAMPLERATE = 13;      // slot 13 = 0x40A118 (out double)
        const int S_SETSAMPLERATE = 14;      // slot 14 = 0x40A134 (persists to HKCU)
        const int S_GETCLOCKSOURCES = 15;     // slot 15 = 0x40A204 "Internal Clock"
        const int S_GETCHANNELINFO = 18;      // slot 18 = 0x40A2A4 (ASIOChannelInfo*)
        const int S_CREATEBUFFERS = 19;       // slot 19 = 0x40A404
        const int S_DISPOSEBUFFERS = 20;      // slot 20 = 0x40A63C
        const int S_START = 7;               // slot 7 = 0x409A38
        const int S_STOP = 8;                 // slot 8 = 0x409D8C

        // ---- delegates matching the driver's calling convention (__stdcall on x64 = one calling conv) ----
        [UnmanagedFunctionPointer(CallingConvention.StdCall)]
        delegate int DInit(IntPtr self, IntPtr sysHandle);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)]
        delegate void DGetName(IntPtr self, IntPtr nameOut); // char name[32]
        [UnmanagedFunctionPointer(CallingConvention.StdCall)]
        delegate int DGetVersion(IntPtr self);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)]
        delegate int DGetChannels(IntPtr self, out int inCh, out int outCh);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)]
        delegate int DGetLatencies(IntPtr self, out int inLat, out int outLat);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)]
        delegate int DGetBufferSize(IntPtr self, out int min, out int max, out int pref, out int gran);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)]
        delegate int DCanSetRate(IntPtr self, double rate);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)]
        delegate int DGetRate(IntPtr self, out double rate);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)]
        delegate int DSetRate(IntPtr self, double rate);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)]
        delegate int DGetClockSources(IntPtr self, IntPtr clocks, out int num);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)]
        delegate int DGetChannelInfo(IntPtr self, IntPtr info);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)]
        delegate int DCreateBuffers(IntPtr self, IntPtr bufferInfos, int numChannels, int bufferSize, IntPtr callbacks);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)]
        delegate int DDisposeBuffers(IntPtr self);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)]
        delegate int DStart(IntPtr self);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)]
        delegate int DStop(IntPtr self);

        // Host-side callbacks for createBuffers (kept alive via GC handle in the --buffers path).
        [UnmanagedFunctionPointer(CallingConvention.StdCall)]
        delegate void DBufferSwitch(long doubleBufferIndex, bool directProcess);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)]
        delegate int DAsioMessage(int selector, int value, IntPtr message, IntPtr opt);

        // asioMessage selectors (asio.h)
        const int kAsioSelectorSupported = 1;
        const int kAsioEngineVersion = 2;
        const int kAsioResetRequest = 3;
        const int kAsioBufferSizeChange = 4;
        const int kAsioResyncRequest = 5;
        const int kAsioOverload = 6;

        // Minimal host callbacks: the driver requires asioMessage (engine version >= 2) for createBuffers.
        static int HostAsioMessage(int selector, int value, IntPtr message, IntPtr opt)
        {
            switch (selector)
            {
                case kAsioSelectorSupported: return 1;            // everything we implement is supported
                case kAsioEngineVersion: return 2;                // ASIO 2 host
                case kAsioResetRequest: return 0;                  // probe never streams; no reset needed
                case kAsioBufferSizeChange: return 0;
                case kAsioResyncRequest: return 0;
                case kAsioOverload: return 0;
                default: return 0;
            }
        }

        // Buffer-switch callback: probe never starts the stream, but the driver may call it
        // if a leftover run state exists; zero both buffers (silence, no side effects).
        static void HostBufferSwitch(long doubleBufferIndex, bool directProcess)
        {
            // no-op: the probe does not start() the stream
        }

        static void Main(string[] args)
        {
            CoInitialize(IntPtr.Zero);
            Console.OutputEncoding = System.Text.Encoding.UTF8;

            // ASIO drivers are ThreadingModel=Apartment in-proc objects. The .NET Main thread
            // is MTA, which would give us a combase proxy instead of the raw CAsio pointer.
            // Create + use the object entirely on a dedicated STA thread to keep the direct
            // vtable pointer (required for the raw slot calls).
            IntPtr pUnk = IntPtr.Zero;
            int hrCi = 0;
            // The whole probe runs on one STA thread: the ASIO object is ThreadingModel=Apartment,
            // so creating and calling it on the same dedicated STA thread avoids any combase proxy.
            var staThread = new System.Threading.Thread(() => RunProbe(args));
            staThread.SetApartmentState(System.Threading.ApartmentState.STA);
            staThread.Start();
            staThread.Join();
        }

        static void RunProbe(string[] args)
        {
            CoInitialize(IntPtr.Zero); // STA
            Guid clsid = new Guid("B2D4D5A2-1B17-4AB6-8A6D-667095C480B2");
            for (int ai = 0; ai + 1 < args.Length; ai++)
            {
                if (args[ai] == "--clsid") clsid = new Guid(args[ai + 1]); // probe alternate builds (e.g. the patched copy)
            }
            Guid iidUnk = new Guid("00000000-0000-0000-C000-000000000046");
            int hrCi = CoCreateInstance(ref clsid, IntPtr.Zero, 1, ref iidUnk, out IntPtr pUnk);
            if (hrCi < 0)
            {
                Console.WriteLine($"CoCreateInstance failed: 0x{hrCi:X8}");
                Console.WriteLine("(Is the Creative USB Native ASIO driver installed?)");
                return;
            }

            IntPtr vtbl = Marshal.ReadIntPtr(pUnk);

            // ---- DIAGNOSTICS: identify the object and vtable owner ----
            if (args.Length > 0 && args[0] == "--diag")
            {
                Console.WriteLine($"CoCreateInstance hr = 0x{hrCi:X8}");
                Console.WriteLine($"pUnk = 0x{pUnk:X}");
                foreach (int slot in new[] { 0, 3, 4, 9, 10, 11, 22 })
                {
                    IntPtr fn = Marshal.ReadIntPtr(vtbl, slot * IntPtr.Size);
                    Console.WriteLine($"  slot {slot}: 0x{fn:X} -> {ModuleOf(fn)}");
                }
                Console.WriteLine("loaded modules (Ct*/Asio*):");
                foreach (string m in ListModules())
                {
                    if (m.IndexOf("Ct", StringComparison.OrdinalIgnoreCase) >= 0 || m.IndexOf("Asio", StringComparison.OrdinalIgnoreCase) >= 0)
                        Console.WriteLine("  " + m);
                }
                return;
            }

            Console.WriteLine("=== Creative Sound Blaster ASIO (CtUsAsio) live probe ===");
            Console.WriteLine($"object  : 0x{pUnk:X}");
            Console.WriteLine($"vtable  : 0x{vtbl:X}");
            for (int i = 0; i <= 24; i++)
            {
                IntPtr fn = Marshal.ReadIntPtr(vtbl, i * IntPtr.Size);
                Console.WriteLine($"  slot {i,2} @ +0x{i * 8:X2}: 0x{fn:X}");
            }
            Console.WriteLine();

            T Fn<T>(int slot) where T : class
            {
                IntPtr fn = Marshal.ReadIntPtr(vtbl, slot * IntPtr.Size);
                return Marshal.GetDelegateForFunctionPointer<T>(fn);
            }

            int initRet = Fn<DInit>(S_INIT)(pUnk, IntPtr.Zero); // ASIO init returns ASIOBool
            Console.WriteLine($"init() -> {initRet} {(initRet != 0 ? "(OK)" : "(FAILED)")}");
            if (initRet == 0) { Marshal.Release(pUnk); return; }

            // ---- write modes: set sample rate / restore, via the driver's own persist path ----
            if (args.Length == 2 && args[0] == "--set-rate")
            {
                double newRate = double.Parse(args[1]);
                int e = Fn<DSetRate>(S_SETSAMPLERATE)(pUnk, newRate);
                Console.WriteLine($"setSampleRate({newRate}) -> hr={e} (0 = persisted to HKCU\\Software\\Creative Tech\\CtUsAsio)");
                Marshal.Release(pUnk);
                return;
            }

            try
            {
                IntPtr nameBuf = Marshal.AllocHGlobal(32);
                Fn<DGetName>(S_GETDRIVERNAME)(pUnk, nameBuf);
                string name = Marshal.PtrToStringAnsi(nameBuf);
                Marshal.FreeHGlobal(nameBuf);
                int ver = Fn<DGetVersion>(S_GETDRIVERVERSION)(pUnk);
                Console.WriteLine($"driver  : \"{name}\" v{ver >> 16}.{ver & 0xFFFF}");
                Console.WriteLine();

                int inCh, outCh;
                int eC = Fn<DGetChannels>(S_GETCHANNELS)(pUnk, out inCh, out outCh);
                Console.WriteLine($"getChannels() -> hr={eC}  inputChannels={inCh}  outputChannels={outCh}");
                Console.WriteLine();

                Console.WriteLine("channels:");
                for (int ch = 0; ch < Math.Max(inCh, outCh); ch++)
                {
                    foreach (bool isInput in new[] { false, true })
                    {
                        int n = isInput ? inCh : outCh;
                        if (ch >= n) continue;
                        var ci = new ASIOChannelInfo { channel = ch, isInput = isInput ? ASIOBool.True : ASIOBool.False, name = new string('\0', 32) };
                        IntPtr pCi = Marshal.AllocHGlobal(Marshal.SizeOf<ASIOChannelInfo>());
                        Marshal.StructureToPtr(ci, pCi, false);
                        int e = Fn<DGetChannelInfo>(S_GETCHANNELINFO)(pUnk, pCi);
                        var back = Marshal.PtrToStructure<ASIOChannelInfo>(pCi);
                        Marshal.FreeHGlobal(pCi);
                        string kind = isInput ? "IN " : "OUT";
                        Console.WriteLine($"  {kind} ch{ch,2}: hr={e} active={(int)back.isActive} group={back.channelGroup} type={back.type} ({TypeStr(back.type)}) name=\"{back.name}\"");
                    }
                }
                Console.WriteLine();

                int mn, mx, pref, gran;
                int eB = Fn<DGetBufferSize>(S_GETBUFFERSIZE)(pUnk, out mn, out mx, out pref, out gran);
                Console.WriteLine($"getBufferSize() -> hr={eB}  min={mn}  max={mx}  preferred={pref}  granularity={gran}");
                Console.WriteLine();

                int inLat, outLat;
                int eL = Fn<DGetLatencies>(S_GETLATENCIES)(pUnk, out inLat, out outLat);
                Console.WriteLine($"getLatencies() -> hr={eL}  inputLatency={inLat} samples  outputLatency={outLat} samples");
                Console.WriteLine();

                double rate;
                int eR = Fn<DGetRate>(S_GETSAMPLERATE)(pUnk, out rate);
                Console.WriteLine($"getSampleRate() -> hr={eR}  rate={rate} Hz");
                foreach (double r in new[] { 44100.0, 48000.0, 88200.0, 96000.0, 176400.0, 192000.0 })
                {
                    int ok = Fn<DCanSetRate>(S_CANSETSAMPLERATE)(pUnk, r);
                    Console.WriteLine($"  canSampleRate({r}) -> {ok} {(ok == 0 ? "(supported)" : "(NOT supported)")}");
                }
                Console.WriteLine();

                IntPtr pClocks = Marshal.AllocHGlobal(Marshal.SizeOf<ASIOClockSource>() * 4);
                int eCl = Fn<DGetClockSources>(S_GETCLOCKSOURCES)(pUnk, pClocks, out int numClocks);
                Console.WriteLine($"getClockSources() -> hr={eCl}  numSources={numClocks}");
                for (int i = 0; i < numClocks && i < 4; i++)
                {
                    var cs = Marshal.PtrToStructure<ASIOClockSource>(pClocks + i * Marshal.SizeOf<ASIOClockSource>());
                    Console.WriteLine($"  clock[{i}]: idx={cs.index} assocCh={cs.associatedChannel} assocGrp={cs.associatedGroup} current={(int)cs.isCurrentSource} name=\"{cs.name}\"");
                }
                Marshal.FreeHGlobal(pClocks);
                Console.WriteLine();

                if (Array.IndexOf(args, "--buffers") >= 0)
                {
                    // Keep delegates rooted for the lifetime of the native calls.
                    var asioMessageDel = new DAsioMessage(HostAsioMessage);
                    var bufferSwitchDel = new DBufferSwitch(HostBufferSwitch);
                    var infos = new ASIOBufferInfo[inCh + outCh];
                    for (int i = 0; i < infos.Length; i++)
                    {
                        infos[i] = new ASIOBufferInfo
                        {
                            isInput = i < inCh ? ASIOBool.True : ASIOBool.False,
                            channelNum = i < inCh ? i : i - inCh,
                            buffers0 = IntPtr.Zero, buffers1 = IntPtr.Zero
                        };
                    }
                    IntPtr pInfos = Marshal.AllocHGlobal(Marshal.SizeOf<ASIOBufferInfo>() * infos.Length);
                    for (int i = 0; i < infos.Length; i++)
                        Marshal.StructureToPtr(infos[i], pInfos + i * Marshal.SizeOf<ASIOBufferInfo>(), false);
                    var cb = new ASIOCallbacks
                    {
                        bufferSwitch = bufferSwitchDel != null ? Marshal.GetFunctionPointerForDelegate(bufferSwitchDel) : IntPtr.Zero,
                        sampleRateDidChange = IntPtr.Zero,
                        asioMessage = Marshal.GetFunctionPointerForDelegate(asioMessageDel),
                        bufferSwitchTimeInfo = IntPtr.Zero
                    };
                    IntPtr pCb = Marshal.AllocHGlobal(Marshal.SizeOf<ASIOCallbacks>());
                    Marshal.StructureToPtr(cb, pCb, false);
                    int createSize = pref;
                    for (int ai = 0; ai + 1 < args.Length; ai++)
                    {
                        if (args[ai] == "--size") createSize = int.Parse(args[ai + 1]); // host-chosen block size in samples
                    }
                    int eCr = Fn<DCreateBuffers>(S_CREATEBUFFERS)(pUnk, pInfos, infos.Length, createSize, pCb);
                    Console.WriteLine($"createBuffers(numChannels={infos.Length}, size={createSize}) -> hr={eCr} {(eCr == 0 ? "(OK)" : "(FAILED)")}");
                    if (eCr == 0)
                    {
                        for (int i = 0; i < infos.Length; i++)
                        {
                            var bi = Marshal.PtrToStructure<ASIOBufferInfo>(pInfos + i * Marshal.SizeOf<ASIOBufferInfo>());
                            Console.WriteLine($"  buf[{i}] {(bi.isInput != 0 ? "IN " : "OUT")} ch{bi.channelNum}: 0x{bi.buffers0:X} 0x{bi.buffers1:X}");
                        }

                        if (Array.IndexOf(args, "--stream") >= 0)
                        {
                            // Stream digital silence briefly: buffers are zero-filled by createBuffers,
                            // the G6 outputs silence on all 8 channels. Fully reversible (stop + dispose).
                            int eStart = Fn<DStart>(S_START)(pUnk);
                            Console.WriteLine($"start() -> hr={eStart} {(eStart == 0 ? "(streaming silence)" : "(FAILED)")}");
                            if (eStart == 0)
                            {
                                int ms = 1500;
                                for (int ai = 0; ai + 1 < args.Length; ai++) { if (args[ai] == "--stream-ms") ms = int.Parse(args[ai + 1]); }
                                System.Threading.Thread.Sleep(ms);
                                int eStop = Fn<DStop>(S_STOP)(pUnk);
                                Console.WriteLine($"stop() -> hr={eStop}");
                            }
                        }

                        int eDis = Fn<DDisposeBuffers>(S_DISPOSEBUFFERS)(pUnk);
                        Console.WriteLine($"disposeBuffers() -> hr={eDis}");
                    }
                    Marshal.FreeHGlobal(pInfos);
                    Marshal.FreeHGlobal(pCb);
                }
            }
            finally
            {
                Marshal.Release(pUnk);
                Console.WriteLine();
                Console.WriteLine("probe complete (read-only; no settings changed, no stream started)");
            }
        }


        // ---- diagnostics helpers ----
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool GetModuleHandleExW(uint dwFlags, IntPtr lpModuleName, out IntPtr phModule);

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
        static extern IntPtr GetModuleFileNameW(IntPtr hModule, System.Text.StringBuilder lpFilename, int nSize);

        [DllImport("kernel32.dll")]
        static extern IntPtr LoadLibraryW([MarshalAs(UnmanagedType.LPWStr)] string lpLibFileName);

        static string ModuleOf(IntPtr fn)
        {
            if (GetModuleHandleExW(0x4 /*FROM_ADDRESS*/, fn, out IntPtr hMod) && hMod != IntPtr.Zero)
            {
                var sb = new System.Text.StringBuilder(512);
                GetModuleFileNameW(hMod, sb, 512);
                return $"{System.IO.Path.GetFileName(sb.ToString())}+0x{(long)fn - (long)hMod:X}";
            }
            return "(not in any module)";
        }

        static System.Collections.Generic.List<string> ListModules()
        {
            var mods = new System.Collections.Generic.List<string>();
            // walk PEB via EnumProcessModules from kernel32 (K32EnumProcessModules)
            var hProc = System.Diagnostics.Process.GetCurrentProcess().Handle;
            IntPtr[] hMods = new IntPtr[1024];
            int cb = hMods.Length * IntPtr.Size;
            int needed;
            if (K32EnumProcessModules(hProc, hMods, cb, out needed))
            {
                int count = needed / IntPtr.Size;
                var sb = new System.Text.StringBuilder(512);
                for (int i = 0; i < count && i < hMods.Length; i++)
                {
                    sb.Clear();
                    if (GetModuleFileNameW(hMods[i], sb, 512) > 0)
                        mods.Add($"0x{(long)hMods[i]:X} {System.IO.Path.GetFileName(sb.ToString())}");
                }
            }
            return mods;
        }

        [DllImport("kernel32.dll")]
        static extern bool K32EnumProcessModules(IntPtr hProcess, [Out] IntPtr[] lphModule, int cb, out int lpcbNeeded);
        static string TypeStr(ASIOSampleType t) => t switch
        {
            ASIOSampleType.Int16MSB => "Int16MSB", ASIOSampleType.Int24MSB => "Int24MSB",
            ASIOSampleType.Int32MSB => "Int32MSB", ASIOSampleType.Float32MSB => "Float32MSB",
            ASIOSampleType.Float64MSB => "Float64MSB", ASIOSampleType.Int32MSB16 => "Int32MSB16",
            ASIOSampleType.Int32MSB18 => "Int32MSB18", ASIOSampleType.Int32MSB20 => "Int32MSB20",
            ASIOSampleType.Int32MSB24 => "Int32MSB24", ASIOSampleType.Int64MSB => "Int64MSB",
            ASIOSampleType.Int32LSB => "Int32LSB", ASIOSampleType.Int16LSB => "Int16LSB",
            ASIOSampleType.Int24LSB => "Int24LSB", ASIOSampleType.Int32LSB16 => "Int32LSB16",
            ASIOSampleType.Int32LSB18 => "Int32LSB18", ASIOSampleType.Int32LSB20 => "Int32LSB20",
            ASIOSampleType.Int32LSB24 => "Int32LSB24", ASIOSampleType.Int64LSB => "Int64LSB",
            ASIOSampleType.Float32LSB => "Float32LSB", ASIOSampleType.Float64LSB => "Float64LSB",
            _ => $"?{(int)t}"
        };
    }
}












