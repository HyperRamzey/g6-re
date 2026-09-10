// G6AsioEnum — reproduces Nuendo/Cubase ASIO driver discovery EXACTLY (proven by
// disassembly of baios.dll, the Steinberg ASIO host component):
//
//   sub_180006FC0 (top):
//     1. folder scan  C:\Program Files\Common Files\ASIO3\*.dll
//     2. RegOpenKeyW(HKEY_LOCAL_MACHINE, "SOFTWARE\\ASIO")   <- HKLM ONLY
//          sub_1800079A0: enumerate subkeys
//          sub_180008030: per key: read required "CLSID" value, optional
//                         "Description" (falls back to key name)
//          sub_180007CC0: validate CLSID via HKCR\CLSID\<clsid>\InprocServer32
//                         (CreateFileW OPEN_EXISTING check, with a
//                         CSIDL_SYSTEM-relative fallback path join)
//
// A driver is LISTED by Nuendo iff it passes the HKLM enumeration + CLSID check.
// This tool prints exactly that list plus each stage's outcome, so "Nuendo can
// see it" is verifiable programmatically without launching Nuendo.
//
// Usage: G6AsioEnum.exe            - list drivers as Nuendo sees them
//        G6AsioEnum.exe --verbose  - also show per-stage detail and failures
//
// Read-only: opens registry keys and checks file existence only.

using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

namespace G6AsioEnum
{
    static class Program
    {
        // ---------------- P/Invoke (exactly what baios.dll calls) ----------------
        [DllImport("advapi32.dll", CharSet = CharSet.Unicode)]
        static extern int RegOpenKeyW(IntPtr hKey, string lpSubKey, out IntPtr phkResult);

        static readonly IntPtr HKEY_LOCAL_MACHINE = new IntPtr(unchecked((int)0x80000002u));
        static readonly IntPtr HKEY_CLASSES_ROOT = new IntPtr(unchecked((int)0x80000000u));

        [DllImport("advapi32.dll")]
        static extern int RegCloseKey(IntPtr hKey);

        [DllImport("advapi32.dll", CharSet = CharSet.Unicode)]
        static extern int RegQueryInfoKeyW(IntPtr hKey, IntPtr lpClass, IntPtr lpcchClass,
            IntPtr lpReserved, ref int lpcSubKeys, ref int lpcbMaxSubKeyLen, IntPtr lpcbMaxClassLen,
            IntPtr lpcValues, IntPtr lpcbMaxValueNameLen, IntPtr lpcbMaxValueLen,
            IntPtr lpcbSecurityDescriptor, IntPtr lpftLastWriteTime);

        [DllImport("advapi32.dll", CharSet = CharSet.Ansi)]
        static extern int RegEnumKeyA(IntPtr hKey, int dwIndex, StringBuilder lpName, int cchName);

        [DllImport("advapi32.dll", CharSet = CharSet.Unicode)]
        static extern int RegQueryValueExW(IntPtr hKey, string lpValueName, IntPtr lpReserved,
            out int lpType, [Out] byte[] lpData, ref int lpcbData);

        const int ERROR_SUCCESS = 0;

        // ---------------- helpers ----------------
        static bool Verbose;
        static string DecodeUtf16(byte[] data, int len)
        {
            if (len < 0 || data == null || len > data.Length) len = data?.Length ?? 0;
            len &= ~1; // whole WCHARs
            return data == null ? "" : Encoding.Unicode.GetString(data, 0, len).TrimEnd('\0');
        }

        static string ReadRegStringW(IntPtr hKey, string valueName)
        {
            int cb = 0;
            int hr = RegQueryValueExW(hKey, valueName, IntPtr.Zero, out _, null, ref cb);
            if (hr != ERROR_SUCCESS || cb <= 0) return null;
            byte[] buf = new byte[cb + 2];
            hr = RegQueryValueExW(hKey, valueName, IntPtr.Zero, out _, buf, ref cb);
            if (hr != ERROR_SUCCESS) return null;
            return DecodeUtf16(buf, cb);
        }

        // baios.dll sub_180007CC0: resolve CLSID -> InprocServer32 path (via HKCR
        // merged view), with the System32-relative fallback for bare file names.
        static string ResolveInprocServer32(string clsid)
        {
            if (RegOpenKeyW(HKEY_CLASSES_ROOT, "CLSID", out IntPtr hClsidRoot) != ERROR_SUCCESS)
                return null;
            try
            {
                if (RegOpenKeyW(hClsidRoot, clsid, out IntPtr hClsid) != ERROR_SUCCESS)
                    return null;
                try
                {
                    if (RegOpenKeyW(hClsid, "InprocServer32", out IntPtr hInp) != ERROR_SUCCESS)
                        return null;
                    try
                    {
                        string path = ReadRegStringW(hInp, null);
                        if (string.IsNullOrEmpty(path)) return null;
                        // baios: if the stored path fails the existence check, retry
                        // with System32 prepended (SHGetFolderPath CSIDL_SYSTEM + "\\" + path)
                        if (File.Exists(path)) return path;
                        string sys = Environment.GetFolderPath(Environment.SpecialFolder.System);
                        string joined = Path.Combine(sys, path);
                        return File.Exists(joined) ? joined : null;
                    }
                    finally { RegCloseKey(hInp); }
                }
                finally { RegCloseKey(hClsid); }
            }
            finally { RegCloseKey(hClsidRoot); }
        }

        static int Main(string[] args)
        {
            Verbose = args.Length > 0 && args[0] == "--verbose";
            Console.OutputEncoding = Encoding.UTF8;
            Console.WriteLine("=== Nuendo/Cubase ASIO enumeration reproduction (baios.dll logic) ===");
            Console.WriteLine("source 1: C:\\Program Files\\Common Files\\ASIO3\\*.dll (folder scan)");
            string asio3 = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.CommonProgramFiles), "ASIO3");
            if (Directory.Exists(asio3))
            {
                foreach (string f in Directory.GetFiles(asio3, "*.dll", SearchOption.AllDirectories))
                    Console.WriteLine($"  [ASIO3 dll] {f}");
                if (Directory.GetFiles(asio3, "*.dll", SearchOption.AllDirectories).Length == 0)
                    Console.WriteLine("  (empty)");
            }
            else
            {
                Console.WriteLine("  (folder does not exist)");
            }

            Console.WriteLine("source 2: HKLM\\SOFTWARE\\ASIO (RegOpenKeyW(HKEY_LOCAL_MACHINE)) - HKLM ONLY");
            Console.WriteLine();

            if (RegOpenKeyW(HKEY_LOCAL_MACHINE, "SOFTWARE\\ASIO", out IntPtr hAsio) != ERROR_SUCCESS)
            {
                Console.WriteLine("  (no HKLM\\SOFTWARE\\ASIO key - no registry ASIO drivers)");
                return 0;
            }
            try
            {
                int cSubKeys = 0, maxLen = 0;
                RegQueryInfoKeyW(hAsio, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero,
                    ref cSubKeys, ref maxLen, IntPtr.Zero, IntPtr.Zero,
                    IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);

                Console.WriteLine($"  {cSubKeys} subkeys; drivers as Nuendo would list them:");
                Console.WriteLine();
                int listed = 0;
                for (int i = 0; i < cSubKeys; i++)
                {
                    var name = new StringBuilder(maxLen + 2);
                    if (RegEnumKeyA(hAsio, i, name, maxLen + 2) != ERROR_SUCCESS) continue;
                    if (RegOpenKeyW(hAsio, name.ToString(), out IntPtr hDriver) != ERROR_SUCCESS) continue;
                    try
                    {
                        string clsid = ReadRegStringW(hDriver, "CLSID");
                        string desc = ReadRegStringW(hDriver, "Description");
                        if (string.IsNullOrEmpty(desc)) desc = name.ToString(); // baios fallback
                        if (clsid == null)
                        {
                            if (Verbose) Console.WriteLine($"  [SKIP] {name}: no CLSID value -> ignored by Nuendo");
                            continue;
                        }
                        string dll = ResolveInprocServer32(clsid);
                        bool fileOk = dll != null;
                        if (Verbose)
                        {
                            Console.WriteLine($"  entry: {name}");
                            Console.WriteLine($"    CLSID       : {clsid}");
                            Console.WriteLine($"    Description : {desc}");
                            Console.WriteLine($"    InprocServer32: {dll ?? "(unresolvable!)"}");
                        }
                        if (!fileOk)
                        {
                            Console.WriteLine($"  [DEAD] {desc} - CLSID resolves to no existing DLL (Nuendo drops it)");
                            continue;
                        }
                        string marker = dll.IndexOf("CtUsAs64_patched", StringComparison.OrdinalIgnoreCase) >= 0
                            ? "  <- PATCHED SAMPLE-LATENCY DRIVER"
                            : "";
                        Console.WriteLine($"  [LISTED] {desc}{marker}");
                        listed++;
                    }
                    finally { RegCloseKey(hDriver); }
                }
                Console.WriteLine();
                Console.WriteLine($"  => {listed} driver(s) would appear in Nuendo's driver list.");
            }
            finally { RegCloseKey(hAsio); }
            return 0;
        }
    }
}
