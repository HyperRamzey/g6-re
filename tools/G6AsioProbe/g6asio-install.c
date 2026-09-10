/* g6asio-install.c ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â one-click installer for the G6 sample-based ASIO patch (v4).
 *
 * Everything end-to-end in a single click, no Python, no admin console:
 *   1. Locate the stock Creative USB ASIO driver (CtUsAs64.dll v1.1.3.0) on disk.
 *   2. Verify the stock byte patterns at every patch site (refuse on mismatch).
 *   3. Apply the raw-sample latency model patches into a per-user copy:
 *        %LOCALAPPDATA%\Creative\G6AsioPatch\CtUsAs64_patched.dll
 *   4. Seed HKCU\Software\Creative Tech\CtUsAsio\LatencyS = 256 (samples).
 *   5. Register the per-user COM class + ASIO enumeration entry (HKCU).
 *   6. Nuendo/Cubase support: add the HKLM\SOFTWARE\ASIO enumeration entry
 *      (Steinberg hosts enumerate HKLM only) via a single UAC self-elevation.
 *   7. Offer to install a logon self-heal (HKCU Run key): every logon the
 *      installer re-runs silently (--silent) and re-asserts the DLL copy and
 *      the HKCU entries if a registry cleaner or update wiped them. The Run
 *      key runs unelevated, so it never pops UAC at logon; the HKLM entry is
 *      durable and only re-asserted during interactive runs.
 *   8. Print a status report for every step.
 *
 * Uninstall: --uninstall removes the registry entries, the Run key and the
 * patched copy (the stock driver is never touched).
 *
 * The stock DLL is only READ; all patches go into our own copy. The patch
 * data below (offsets + byte diffs) is derived from public reverse-engineering
 * documented in the g6-re repository (docs/ASIO.md).
 *
 * Build (MSVC, LTO + max optimization):
 *   cl /O2 /GL /LTCG:incremental g6asio-install.c advapi32.lib shell32.lib user32.lib /Fe:g6-asio-install.exe
 * (clang/LLVM ThinLTO:
 *   clang -O3 -flto=thin -fuse-ld=lld -municode g6asio-install.c -ladvapi32 -lshell32 -luser32 -o g6-asio-install.exe)
 */

#ifndef _CRT_SECURE_NO_WARNINGS
#define _CRT_SECURE_NO_WARNINGS
#endif
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif

#include <windows.h>
#include <shlobj.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ---------------------------------------------------------------- constants */
static const wchar_t *STOCK_PATHS[] = {
    L"C:\\Program Files (x86)\\Creative\\Creative USB Native ASIO\\CtUsAsio\\amd64\\CtUsAs64.dll",
    L"CtUsAs64.dll", /* fallback: relative */
};
static const int NSTOCK = 2;

#define NEW_CLSID_TXT L"{8F5E2A31-6C74-4B9E-9D3A-2E7F5A6B8C90}"
static const GUID NEW_CLSID = {
    0x8F5E2A31, 0x6C74, 0x4B9E, {0x9D, 0x3A, 0x2E, 0x7F, 0x5A, 0x6B, 0x8C, 0x90}};
static const GUID OLD_CLSID = {
    0xB2D4D5A2, 0x1B17, 0x4AB6, {0x8A, 0x6D, 0x66, 0x70, 0x95, 0xC4, 0x80, 0xB2}};

static const wchar_t *ASIO_KEY_HKCU = L"Software\\ASIO\\G6 ASIO (sample-based patch)";
static const wchar_t *ASIO_KEY_HKLM = L"SOFTWARE\\ASIO\\G6 ASIO (sample-based patch)";
static const wchar_t *CLS_KEY = L"Software\\Classes\\CLSID\\" NEW_CLSID_TXT L"\\InprocServer32";
static const wchar_t *CTASIO_KEY = L"Software\\Creative Tech\\CtUsAsio";
static const wchar_t *RUN_KEY = L"Software\\Microsoft\\Windows\\CurrentVersion\\Run";
static const wchar_t *RUN_VALUE = L"G6AsioPatch";

/* --------------------------------------------------------------- patch data */
/* All offsets are FILE offsets in the stock CtUsAs64.dll v1.1.3.0 (177664 bytes).
 * Every site is verified against its expected stock bytes before patching.
 * (VA = file + 0x400C00 for .text.) */

typedef struct {
    const char *name;
    DWORD file_off;
    const unsigned char *orig;
    const unsigned char *patch;
    DWORD len;
} Site;

/* getBufferSize min sequence: imul ecx,cs:[427A08]; mul ecx; mov eax,esi; shr edx,6; mov [rbx],edx */
static const unsigned char GB_MIN_ORIG[] =
    "\x0F\xAF\x0D\x8C\xDA\x01\x00\xF7\xE1\x8B\xC6\xC1\xEA\x06\x89\x13";
static const unsigned char GB_MIN_PATCH[] =
    "\x41\x8B\x4A\x28\x89\x0B\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90";
/* mov ecx,[r10+28h]; mov [rbx],ecx; nops ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â min = raw LatencyS */

/* getBufferSize max sequence: imul ecx,cs:[427A38]; mul ecx; shr edx,6; mov [r8],edx */
static const unsigned char GB_MAX_ORIG[] =
    "\x0F\xAF\x0D\xA6\xDA\x01\x00\xF7\xE1\xC1\xEA\x06\x41\x89\x10";
static const unsigned char GB_MAX_PATCH[] =
    "\x41\x8B\x4A\x28\x41\x89\x08\x90\x90\x90\x90\x90\x90\x90\x90";
/* mov ecx,[r10+28h]; mov [r8],ecx; nops ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â max = raw LatencyS */

/* getBufferSize preferred block (70 bytes): stock round-to-8 ms->samples
 * replaced with preferred = raw LatencyS ([r10+28h]) then jmp shared tail. */
static const unsigned char GB_PREF_ORIG[] =
    "\xF2\x49\x0F\x2C\x42\x64\x41\x8B\x4A\x28\x0F\xAF\xC8\x8B\xC6\xF7\xE1"
    "\x8B\xCA\xC1\xE9\x06\x8B\xC1\x99\x83\xE2\x07\x03\xC2\x8B\xF0\x83\xE0"
    "\x07\xC1\xFE\x03\x3B\xC2\x74\x0C\x8D\x04\xF5\x08\x00\x00\x00\x41\x89"
    "\x01\xEB\x03\x41\x89\x09\x41\x39\x39\x75\x14\x41\x89\x09\xBF\x18\xFC\xFF\xFF";
static const unsigned char GB_PREF_PATCH[] =
    "\x41\x8B\x42\x28\x41\x89\x01\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\xEB\x0C";
/* mov eax,[r10+28h]; mov [r9],eax; nops; jmp +0x0C -> shared tail 0x409FF6 */

/* getBufferSize tail: min=max=preferred overwrite + gran -> gran=16 only */
static const unsigned char BS_ORIG[] =
    "\x41\x8B\x09\x41\x89\x08\x89\x0B\x41\x83\x23\x00";
static const unsigned char BS_PATCH[] =
    "\x41\xC7\x03\x10\x00\x00\x00\x90\x90\x90\x90\x90";
/* mov dword [r11],16; nops ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â min/max keep raw, granularity = 16 */

/* panel scan bound: cmp eax,0Dh -> cmp eax,10h */
static const unsigned char SCAN_ORIG[] = "\x83\xF8\x0D";
static const unsigned char SCAN_PATCH[] =
    "\x83\xF8\x10";

/* panel save clamp: cmp r13d,0Dh -> cmp r13d,10h */
static const unsigned char CLAMP_ORIG[] = "\x41\x83\xFD\x0D";
static const unsigned char CLAMP_PATCH[] =
    "\x41\x83\xFD\x10";

/* panel save advisory-arg block (22B): r11 = rate*ms magic-div -> r11 = raw */
static const unsigned char ADV_ORIG[] =
    "\xF2\x4C\x0F\x2C\x5F\x64\x44\x0F\xAF\x5F\x28\xB8\xD3\x4D\x62\x10\x41\xF7\xE3\xC1\xEA\x06";
static const unsigned char ADV_PATCH[] =
    "\x44\x8B\x5F\x28\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90\x90";
/* mov r11d,[rdi+28h]; nops */

/* dialog lea rel32: r12 -> sample table @0x42FF68 (opcode 4C 8D 25 kept) */
static const unsigned char DLG_LEA_ORIG[] = "\x4C\x8D\x25\x46\xE6\x01\x00";
static const unsigned char DLG_LEA_PATCH[] =
    "\x4C\x8D\x25\xA6\x6B\x02\x00";
/* rel32 = 0x42FF68 - 0x4093C2 = 0x21F8C */

/* dialog counter: lea r13d,[rbp+0Dh] -> [rbp+10h] */
static const unsigned char DLG_CNT_ORIG[] = "\x44\x8D\x6D\x0D";
static const unsigned char DLG_CNT_PATCH[] =
    "\x44\x8D\x6D\x10";

/* dialog format string "%d ms\0" + 6 pad bytes -> "%d samples\0\0" (12B total) */
static const unsigned char FMT_ORIG[] = "%d ms\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00";
static const unsigned char FMT_PATCH[] =
    "\x25\x64\x20\x73\x61\x6D\x70\x6C\x65\x73\x00\x00";

/* advisory gate: jbe -> jmp (never fires reset requests) */
static const unsigned char GATE_ORIG[] = "\x76\x7F";
static const unsigned char GATE_PATCH[] =
    "\xEB\x7F";

/* panel "Latency" name leas (init read + panel save) -> "LatencyS" @0x42FFA8 */
static const unsigned char LEA1_ORIG[] = "\x48\x8D\x15\x13\x8F\xFF\xFF";
static const unsigned char LEA1_PATCH[] =
    "\x48\x8D\x15\xE3\x54\x02\x00";
/* rel32 = 0x42FFA8 - 0x40AAC5 = 0x254E4 */
static const unsigned char LEA2_ORIG[] = "\x48\x8D\x15\xEA\xA0\xFF\xFF";
static const unsigned char LEA2_PATCH[] =
    "\x48\x8D\x15\xBA\x66\x02\x00";
/* rel32 = 0x42FFA8 - 0x4098EE = 0x257FC */

/* panel table leas (4 sites) -> sample table @0x42FF68 */
static const unsigned char PL1_ORIG[] = "\x4C\x8D\x35\x23\xD1\x01\x00";
static const unsigned char PL1_PATCH[] =
    "\x4C\x8D\x35\x83\x56\x02\x00"; /* 0x42FF68-0x40A8E5 */
static const unsigned char PL2_ORIG[] = "\x4C\x8D\x35\x10\xD0\x01\x00";
static const unsigned char PL2_PATCH[] =
    "\x4C\x8D\x35\x70\x55\x02\x00"; /* 0x42FF68-0x40A9F8 */
static const unsigned char PL3_ORIG[] = "\x4C\x8D\x35\xDD\xCF\x01\x00";
static const unsigned char PL3_PATCH[] =
    "\x4C\x8D\x35\x3D\x55\x02\x00"; /* 0x42FF68-0x40AA2B */
static const unsigned char PL4_ORIG[] = "\x4C\x8D\x35\xC8\xCF\x01\x00";
static const unsigned char PL4_PATCH[] =
    "\x4C\x8D\x35\x28\x55\x02\x00"; /* 0x42FF68-0x40AA40 */

static const Site SITES[] = {
    {"getBufferSize min",       0x9375, GB_MIN_ORIG,  GB_MIN_PATCH,  16},
    {"getBufferSize max",       0x938B, GB_MAX_ORIG,  GB_MAX_PATCH,  15},
    {"getBufferSize preferred", 0x93A4, GB_PREF_ORIG, GB_PREF_PATCH, 70},
    {"getBufferSize gran=16",   0x9437, BS_ORIG,      BS_PATCH,      12},
    {"panel scan 16",           0x9CF4, SCAN_ORIG,    SCAN_PATCH,     3},
    {"panel clamp 16",          0x9D41, CLAMP_ORIG,   CLAMP_PATCH,    4},
    {"panel adv raw",           0x9EE8, ADV_ORIG,     ADV_PATCH,     22},
    {"dialog lea table",        0x87BB, DLG_LEA_ORIG, DLG_LEA_PATCH,  7},
    {"dialog count 16",         0x87C2, DLG_CNT_ORIG, DLG_CNT_PATCH,  4},
    {"dialog fmt samples",      0x2C54, FMT_ORIG,     FMT_PATCH,     12},
    {"gate neuter",             0xAEFA, GATE_ORIG,    GATE_PATCH,     2},
    {"name lea save",           0x9EBE, LEA1_ORIG,    LEA1_PATCH,     7},
    {"name lea init",           0x8CE7, LEA2_ORIG,   LEA2_PATCH,     7},
    {"panel lea 1",             0x9CDE, PL1_ORIG,     PL1_PATCH,      7},
    {"panel lea 2",             0x9DF1, PL2_ORIG,     PL2_PATCH,      7},
    {"panel lea 3",             0x9E24, PL3_ORIG,     PL3_PATCH,      7},
    {"panel lea 4",             0x9E39, PL4_ORIG,     PL4_PATCH,      7},
};
#define NSITES (sizeof(SITES) / sizeof(SITES[0]))

/* .rsrc: sample table (16 entries) + "LatencyS" name; VirtualSize 0x2F68 -> 0x3000 */
#define TABLE_OFF 0x2AD68
#define NAME_OFF  (TABLE_OFF + 64)
static const unsigned int SAMPLE_TABLE[16] = {
    48, 96, 128, 192, 256, 320, 384, 512, 640, 768,
    1024, 1536, 2048, 3072, 3840, 4800};
static const unsigned char LATNAME[] = "LatencyS\x00";
#define RSRC_NAME_OFF 0x270   /* .rsrc section header entry */
#define RSRC_VSIZE_OFF (RSRC_NAME_OFF + 8)

/* ------------------------------------------------------------ little helpers */
static int g_silent = 0;

static int fail(const wchar_t *fmt, ...) {
    va_list ap;
    wchar_t buf[512];
    va_start(ap, fmt);
    _vsnwprintf(buf, 512, fmt, ap);
    va_end(ap);
    fwprintf(stderr, L"[FAIL] %ls\n", buf);
    return 1;
}

static void okmsg(const wchar_t *fmt, ...) {
    va_list ap;
    wchar_t buf[512];
    if (g_silent)
        return;
    va_start(ap, fmt);
    _vsnwprintf(buf, 512, fmt, ap);
    va_end(ap);
    wprintf(L"[ OK ] %ls\n", buf);
}

static int is_elevated(void) {
    BOOL f = FALSE;
    HANDLE tok = NULL;
    if (OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &tok)) {
        TOKEN_ELEVATION e;
        DWORD n = 0;
        if (GetTokenInformation(tok, TokenElevation, &e, sizeof(e), &n))
            f = e.TokenIsElevated;
        CloseHandle(tok);
    }
    return f;
}

/* spawn an elevated copy of this exe with the given argument; -1 = child
 * launched (caller should exit quietly), 0 = already elevated, 1 = declined */
static int self_elevate(const wchar_t *param) {
    SHELLEXECUTEINFOW sei;
    wchar_t exe[MAX_PATH];
    if (is_elevated())
        return 0;
    GetModuleFileNameW(NULL, exe, MAX_PATH);
    memset(&sei, 0, sizeof(sei));
    sei.cbSize = sizeof(sei);
    sei.lpVerb = L"runas";
    sei.lpFile = exe;
    sei.lpParameters = param;
    sei.nShow = SW_NORMAL;
    if (!ShellExecuteExW(&sei)) {
        if (!g_silent)
            return fail(L"UAC elevation declined or failed (error %lu)", GetLastError());
        return 1;
    }
    return -1;
}

/* ------------------------------------------------------------- registry bits */
static int reg_set(HKEY root, const wchar_t *sub, const wchar_t *val,
                   DWORD type, const void *data, DWORD cb) {
    HKEY k;
    if (RegCreateKeyExW(root, sub, 0, NULL, 0, KEY_SET_VALUE, NULL, &k, NULL))
        return fail(L"RegCreateKeyEx %ls failed", sub);
    LSTATUS r = RegSetValueExW(k, val, 0, type, data, cb);
    RegCloseKey(k);
    return r ? fail(L"RegSetValueEx %ls\\%ls failed (%ld)", sub, val, r) : 0;
}

static int reg_del_tree(HKEY root, const wchar_t *sub) {
    LSTATUS r = RegDeleteTreeW(root, sub);
    return (r == ERROR_SUCCESS || r == ERROR_FILE_NOT_FOUND) ? 0
           : fail(L"RegDeleteTree %ls failed (%ld)", sub, r);
}

static int reg_value_exists(HKEY root, const wchar_t *sub, const wchar_t *val) {
    HKEY k;
    if (RegOpenKeyExW(root, sub, 0, KEY_QUERY_VALUE, &k))
        return 0;
    int ok = RegQueryValueExW(k, val, NULL, NULL, NULL, NULL) == ERROR_SUCCESS;
    RegCloseKey(k);
    return ok;
}

/* ---------------------------------------------------------- driver patching */
/* returns 0 = already patched (all sites match), 1 = needs patching, -1 = error */
static int check_patched(const wchar_t *dst) {
    HANDLE h = CreateFileW(dst, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
                           NULL, OPEN_EXISTING, 0, NULL);
    if (h == INVALID_HANDLE_VALUE)
        return 1;
    DWORD size = GetFileSize(h, NULL);
    unsigned char *buf = malloc(size ? size : 1);
    if (!buf) { CloseHandle(h); return -1; }
    DWORD rd = 0;
    int okread = ReadFile(h, buf, size, &rd, NULL) && rd == size;
    CloseHandle(h);
    if (!okread) { free(buf); return -1; }
    int all = 1;
    for (DWORD i = 0; i < NSITES; i++) {
        if (memcmp(buf + SITES[i].file_off, SITES[i].patch, SITES[i].len) != 0) {
            all = 0;
            break;
        }
    }
    free(buf);
    return all ? 0 : 1;
}

static int patch_driver(const wchar_t *dst) {
    /* find stock */
    const wchar_t *src = NULL;
    for (int i = 0; i < NSTOCK; i++) {
        if (GetFileAttributesW(STOCK_PATHS[i]) != INVALID_FILE_ATTRIBUTES) {
            src = STOCK_PATHS[i];
            break;
        }
    }
    if (!src)
        return fail(L"stock CtUsAs64.dll not found (install Creative USB Native ASIO first)");

    HANDLE h = CreateFileW(src, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (h == INVALID_HANDLE_VALUE)
        return fail(L"cannot open stock driver %ls", src);
    DWORD size = GetFileSize(h, NULL);
    if (size != 177664) {
        CloseHandle(h);
        return fail(L"unexpected stock size %lu (expected 177664 = v1.1.3.0)", size);
    }
    unsigned char *buf = malloc(size);
    if (!buf) { CloseHandle(h); return fail(L"out of memory"); }
    DWORD rd = 0;
    if (!ReadFile(h, buf, size, &rd, NULL) || rd != size) {
        CloseHandle(h); free(buf);
        return fail(L"read error on stock driver");
    }
    CloseHandle(h);

    /* verify + apply every site */
    for (DWORD i = 0; i < NSITES; i++) {
        const Site *s = &SITES[i];
        if (memcmp(buf + s->file_off, s->orig, s->len) != 0) {
            wchar_t eb[40], gb[40];
            for (DWORD j = 0; j < s->len && j < 16; j++)
                swprintf(eb + j * 2, 4, L"%02X", buf[s->file_off + j]);
            for (DWORD j = 0; j < s->len && j < 16; j++)
                swprintf(gb + j * 2, 4, L"%02X", (unsigned char)s->orig[j]);
            free(buf);
            return fail(L"pattern mismatch at %hs (file 0x%lX): got %ls want %ls - "
                         L"unsupported CtUsAs64.dll version", s->name, s->file_off, eb, gb);
        }
        memcpy(buf + s->file_off, s->patch, s->len);
    }
    /* .rsrc padding must be zero */
    for (int i = 0; i < 0x98; i++) {
        if (buf[TABLE_OFF + i]) {
            free(buf);
            return fail(L".rsrc padding not empty - layout changed, aborting");
        }
    }
    /* sample table + name + VirtualSize extension */
    memcpy(buf + TABLE_OFF, SAMPLE_TABLE, sizeof(SAMPLE_TABLE));
    memcpy(buf + NAME_OFF, LATNAME, sizeof(LATNAME));
    *(unsigned int *)(buf + RSRC_VSIZE_OFF) = 0x3000;

    /* CLSID rebind (binary GUID + both ASCII forms) */
    int n = 0;
    for (DWORD i = 0; i + 16 <= size; i++) {
        if (!memcmp(buf + i, &OLD_CLSID, 16)) {
            memcpy(buf + i, &NEW_CLSID, 16);
            n++; i += 15;
        }
    }
    static const char OLD_A[] = "B2D4D5A2-1B17-4AB6-8A6D-667095C480B2";
    static const char NEW_A[] = "8F5E2A31-6C74-4B9E-9D3A-2E7F5A6B8C90";
    static const char OLD_B[] = "{B2D4D5A2-1B17-4AB6-8A6D-667095C480B2}";
    static const char NEW_B[] = "{8F5E2A31-6C74-4B9E-9D3A-2E7F5A6B8C90}";
    char *p = (char *)buf;
    for (DWORD i = 0; i + 36 <= size; i++) {
        if (!memcmp(p + i, OLD_A, 36)) { memcpy(p + i, NEW_A, 36); n++; i += 35; }
    }
    for (DWORD i = 0; i + 38 <= size; i++) {
        if (!memcmp(p + i, OLD_B, 38)) { memcpy(p + i, NEW_B, 38); n++; i += 37; }
    }

    /* write the patched copy */
    h = CreateFileW(dst, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, 0, NULL);
    if (h == INVALID_HANDLE_VALUE) {
        free(buf);
        if (g_silent)
            return 0; /* logon heal: file locked = a DAW has it loaded = it is fine */
        return fail(L"cannot write %ls (close Nuendo/DAW first)", dst);
    }
    DWORD wr = 0;
    int wok = WriteFile(h, buf, size, &wr, NULL) && wr == size;
    CloseHandle(h);
    free(buf);
    if (!wok)
        return g_silent ? 0 : fail(L"write error on patched copy");
    okmsg(L"patched driver written (%d CLSID rewrites): %ls", n, dst);
    return 0;
}

/* ------------------------------------------------------------- registration */
static int register_hkcu(const wchar_t *dll) {
    if (reg_set(HKEY_CURRENT_USER, CLS_KEY, NULL, REG_SZ, dll,
                (DWORD)((wcslen(dll) + 1) * sizeof(wchar_t))))
        return 1;
    if (reg_set(HKEY_CURRENT_USER, CLS_KEY, L"ThreadingModel", REG_SZ, L"Apartment", 20))
        return 1;
    okmsg(L"registered per-user COM class " NEW_CLSID_TXT);

    if (reg_set(HKEY_CURRENT_USER, ASIO_KEY_HKCU, NULL, REG_SZ, L"G6 sample-based ASIO", 40))
        return 1;
    if (reg_set(HKEY_CURRENT_USER, ASIO_KEY_HKCU, L"CLSID", REG_SZ, NEW_CLSID_TXT, 78))
        return 1;
    if (reg_set(HKEY_CURRENT_USER, ASIO_KEY_HKCU, L"Description", REG_SZ,
                L"Creative Sound Blaster ASIO (sample latency patch)", 92))
        return 1;
    okmsg(L"registered HKCU ASIO entry");
    return 0;
}

static int register_hklm(void) {
    if (reg_set(HKEY_LOCAL_MACHINE, ASIO_KEY_HKLM, NULL, REG_SZ, L"G6 sample-based ASIO", 40))
        return 1;
    if (reg_set(HKEY_LOCAL_MACHINE, ASIO_KEY_HKLM, L"CLSID", REG_SZ, NEW_CLSID_TXT, 78))
        return 1;
    if (reg_set(HKEY_LOCAL_MACHINE, ASIO_KEY_HKLM, L"Description", REG_SZ,
                L"Creative Sound Blaster ASIO (sample latency patch)", 92))
        return 1;
    okmsg(L"registered HKLM ASIO entry (Nuendo/Cubase support)");
    return 0;
}

static int seed_latency(void) {
    HKEY k;
    DWORD have = 0, cb = 4, t = 0;
    if (!RegOpenKeyExW(HKEY_CURRENT_USER, CTASIO_KEY, 0, KEY_QUERY_VALUE, &k)) {
        if (RegQueryValueExW(k, L"LatencyS", NULL, &t, (void *)&have, &cb) || t != REG_DWORD)
            have = 0;
        RegCloseKey(k);
    }
    if (have) {
        okmsg(L"LatencyS already present = %lu samples (kept)", have);
        return 0;
    }
    DWORD seed = 256;
    if (reg_set(HKEY_CURRENT_USER, CTASIO_KEY, L"LatencyS", REG_DWORD, &seed, 4))
        return 1;
    okmsg(L"seeded LatencyS = 256 samples");
    return 0;
}

/* --------------------------------------------------------------- startup opt */
static int startup_installed(void) {
    return reg_value_exists(HKEY_CURRENT_USER, RUN_KEY, RUN_VALUE);
}

static int set_startup(int enable) {
    if (enable) {
        wchar_t exe[MAX_PATH], cmd[MAX_PATH + 32];
        GetModuleFileNameW(NULL, exe, MAX_PATH);
        _snwprintf(cmd, MAX_PATH + 32, L"\"%ls\" --silent", exe);
        if (reg_set(HKEY_CURRENT_USER, RUN_KEY, RUN_VALUE, REG_SZ, cmd,
                    (DWORD)((wcslen(cmd) + 1) * sizeof(wchar_t))))
            return 1;
        okmsg(L"logon self-heal enabled (HKCU Run: %ls)", RUN_VALUE);
        return 0;
    }
    HKEY k;
    if (RegOpenKeyW(HKEY_CURRENT_USER, RUN_KEY, &k) == ERROR_SUCCESS) {
        RegDeleteValueW(k, RUN_VALUE);
        RegCloseKey(k);
    }
    okmsg(L"logon self-heal removed");
    return 0;
}

static void ask_startup(void) {
    int yes = MessageBoxW(NULL,
        L"Automatically re-apply the patch at every logon?\n\n"
        L"This adds a silent startup entry that re-asserts the patched driver\n"
        L"and its registration if anything was wiped (e.g. by a registry\n"
        L"cleaner or a Creative software update). It never pops UAC prompts.\n\n"
        L"Add to startup?",
        L"G6 ASIO sample patch", MB_YESNO | MB_ICONQUESTION);
    set_startup(yes == IDYES);
}

/* ---------------------------------------------------------------- installer */
/* full install path (interactive + elevated-child + silent) */
static int install(const wchar_t *dll) {
    /* 1. patched DLL (skip if already good) */
    int st = check_patched(dll);
    if (st < 0)
        return 1;
    if (st == 0) {
        okmsg(L"patched driver already in place: %ls", dll);
    } else if (patch_driver(dll)) {
        return 1;
    }

    /* 2. seed LatencyS */
    if (seed_latency())
        return 1;

    /* 3. per-user registrations */
    if (register_hkcu(dll))
        return 1;

    /* 4. HKLM entry (Nuendo/Cubase). In silent logon mode: only if we happen
     * to be elevated; never self-elevate (no UAC at logon). */
    if (is_elevated()) {
        if (register_hklm())
            return 1;
    } else if (g_silent) {
        if (reg_value_exists(HKEY_LOCAL_MACHINE, ASIO_KEY_HKLM, L"CLSID"))
            okmsg(L"HKLM ASIO entry present (kept)");
        else
            fwprintf(stderr, L"[WARN] HKLM entry missing; run the installer "
                              L"interactively once to restore Nuendo support\n");
    } else {
        wprintf(L"[INFO] Nuendo/Cubase support needs one UAC confirmation...\n");
        fflush(stdout);
        int r = self_elevate(L"--finish");
        if (r < 0)
            return -1;    /* elevated child took over the remaining steps */
        if (r > 0) {
            fwprintf(stderr, L"[WARN] HKLM registration skipped (UAC declined) - "
                              L"REAPER-style hosts still work; rerun for Nuendo support\n");
        }
    }

    /* 5. done */
    if (!g_silent) {
        wprintf(L"\nDone. Pick \"G6 ASIO (sample-based patch)\" in your DAW's ASIO driver list\n"
                L"(Nuendo: Studio > Audio Connections > Audio System). Driver panel + buffer\n"
                L"sizes are now in samples (48..4800, steps of 16; e.g. 128/256/512).\n");
    }
    return 0;
}

static int uninstall(const wchar_t *dll) {
    set_startup(0);
    if (reg_del_tree(HKEY_CURRENT_USER, ASIO_KEY_HKCU))
        return 1;
    if (reg_del_tree(HKEY_CURRENT_USER, L"Software\\Classes\\CLSID\\" NEW_CLSID_TXT))
        return 1;
    okmsg(L"removed HKCU entries");
    if (is_elevated()) {
        if (reg_del_tree(HKEY_LOCAL_MACHINE, ASIO_KEY_HKLM))
            return 1;
        okmsg(L"removed HKLM entry");
    } else {
        wprintf(L"[INFO] HKLM removal needs one UAC confirmation...\n");
        fflush(stdout);
        int r = self_elevate(L"--uninstall-hklm");
        if (r < 0)
            return -1;
        if (r > 0)
            fwprintf(stderr, L"[WARN] HKLM entry kept (UAC declined)\n");
    }
    if (DeleteFileW(dll) || GetLastError() == ERROR_FILE_NOT_FOUND)
        okmsg(L"removed patched DLL");
    else
        fwprintf(stderr, L"[WARN] could not delete %ls (close Nuendo/DAW first)\n", dll);
    if (!g_silent)
        wprintf(L"\nUninstalled. The stock \"Creative Sound Blaster ASIO\" was never touched.\n");
    return 0;
}

int wmain(int argc, wchar_t **argv) {
    int do_uninstall = 0;
    for (int i = 1; i < argc; i++) {
        if (!_wcsicmp(argv[i], L"--uninstall"))
            do_uninstall = 1;
        else if (!_wcsicmp(argv[i], L"--uninstall-hklm")) {
            /* elevated child: remove HKLM entry only, then exit */
            g_silent = 0;
            if (reg_del_tree(HKEY_LOCAL_MACHINE, ASIO_KEY_HKLM))
                return 1;
            okmsg(L"removed HKLM entry");
            wprintf(L"\nUninstalled. The stock \"Creative Sound Blaster ASIO\" was never touched.\n");
            return 0;
        } else if (!_wcsicmp(argv[i], L"--finish")) {
            /* elevated child: HKLM entry + startup question + final message */
            g_silent = 0;
            if (register_hklm())
                return 1;
            ask_startup();
            wprintf(L"\nDone. Pick \"G6 ASIO (sample-based patch)\" in your DAW's ASIO driver list\n"
                    L"(Nuendo: Studio > Audio Connections > Audio System). Driver panel + buffer\n"
                    L"sizes are now in samples (48..4800, steps of 16; e.g. 128/256/512).\n");
            return 0;
        } else if (!_wcsicmp(argv[i], L"--silent")) {
            g_silent = 1; /* logon self-heal: quiet, no UAC, no prompts */
        } else if (!_wcsicmp(argv[i], L"--help") || !_wcsicmp(argv[i], L"-h")) {
            wprintf(L"Usage: g6-asio-install.exe [--uninstall | --silent]\n"
                     L"One-click install/uninstall of the G6 sample-based ASIO patch.\n"
                     L"--silent re-asserts everything without prompts (used by the\n"
                     L"logon self-heal entry).\n");
            return 0;
        }
    }

    wchar_t dir[MAX_PATH], dll[MAX_PATH];
    if (!SUCCEEDED(SHGetFolderPathW(NULL, CSIDL_LOCAL_APPDATA, NULL, 0, dir)))
        return fail(L"cannot resolve LOCALAPPDATA");
    _snwprintf(dll, MAX_PATH, L"%ls\\Creative\\G6AsioPatch", dir);
    CreateDirectoryW(dll, NULL); /* best-effort */
    wcscat_s(dll, MAX_PATH, L"\\CtUsAs64_patched.dll");

    if (do_uninstall) {
        int r = uninstall(dll);
        return r == -1 ? 0 : (r ? 1 : 0);
    }
    int r = install(dll);
    if (r == -1)
        return 0; /* elevated child took over */
    /* interactive success: offer the startup self-heal if not already set
     * (the elevated --finish child asks instead when UAC was used) */
    if (!g_silent && !startup_installed() && r == 0) {
        /* asked in the elevated child when possible; only ask here when
         * we were already elevated (no child was spawned) */
        if (is_elevated())
            ask_startup();
    }
    return r ? 1 : 0;
}
