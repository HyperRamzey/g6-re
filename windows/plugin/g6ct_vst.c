/*
 * g6ct_vst.c - VST2 insert plugin wrapping the Creative MatrixEncoder port.
 *
 * Contract: 8 audio inputs, 2 audio outputs, 48 kHz.
 *
 *   in [0..7] = FL FR FC LFE BL BR SL SR   (WAVEFORMATEXTENSIBLE 7.1 order,
 *                                          identical to VST kSpeakerArr71)
 *   out[0..1] = binaural left / right       (the downmix result)
 *
 * Two outputs, not eight, on purpose.  The six channels the matrix consumed
 * have no output port at all, so a host that wires only these two cannot leave
 * a stale surround channel behind to be summed back into the mix.
 *
 * Internal arithmetic is f64 (compile together with a -DG6CT_DOUBLE build of
 * g6ct.c).  The host-facing float32 path converts per sample; that conversion
 * is exact in both directions.
 *
 * Metering: ten VST parameters expose live levels so any host can display
 * them, and the plugin also ships its own editor with input/output bars.
 *
 *   0..7  input peak, per channel        (linear, 0..1)
 *   8..9  output peak, left / right      (linear, 0..1)
 *
 * Build (mingw64):
 *   gcc -O2 -std=c11 -Wall -Wextra -ffp-contract=off -fno-fast-math \
 *       -DG6CT_DOUBLE -shared -static-libgcc -I../upstream \
 *       -o g6ct.dll g6ct_vst.c ../upstream/g6ct.c -lm -lgdi32 -luser32
 */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#if defined(_WIN32)
#  include <windows.h>
#  define VST_EXPORT __declspec(dllexport)
#  define VSTCALLBACK __cdecl
#else
#  define VST_EXPORT __attribute__((visibility("default")))
#  define VSTCALLBACK
#endif

#include "g6ct.h"

/* ------------------------------------------------------------------ */
/* Minimal VST 2.4 ABI                                                 */
/* ------------------------------------------------------------------ */

typedef int32_t VstInt32;
typedef intptr_t VstIntPtr;

typedef struct AEffect AEffect;

typedef VstIntPtr(VSTCALLBACK *audioMasterCallback)(AEffect *, VstInt32,
                                                    VstInt32, VstIntPtr,
                                                    void *, float);

struct AEffect {
    VstInt32 magic;
    VstIntPtr dispatcher;
    VstIntPtr process;
    VstIntPtr setParameter;
    VstIntPtr getParameter;
    VstInt32 numPrograms;
    VstInt32 numParams;
    VstInt32 numInputs;
    VstInt32 numOutputs;
    VstInt32 flags;
    VstIntPtr ptr1;
    VstIntPtr ptr2;
    VstInt32 initialDelay;
    VstInt32 realQualities;
    VstInt32 offQualities;
    float ioRatio;
    void *object;
    void *user;
    VstInt32 uniqueID;
    VstInt32 version;
    VstIntPtr processReplacing;
    VstIntPtr processDoubleReplacing;
    char future[56];
};

/* VST ERect is ordered top, left, bottom, right. */
typedef struct ERect {
    short top;
    short left;
    short bottom;
    short right;
} ERect;

#define kEffectMagic 0x56737450 /* 'VstP' */

enum {
    effOpen = 0,
    effClose = 1,
    effSetProgram = 2,
    effGetProgram = 3,
    effSetProgramName = 4,
    effGetProgramName = 5,
    effGetParamLabel = 6,
    effGetParamDisplay = 7,
    effGetParamName = 8,
    effSetSampleRate = 10,
    effSetBlockSize = 11,
    effMainsChanged = 12,
    effEditGetRect = 13,
    effEditOpen = 14,
    effEditClose = 15,
    effEditIdle = 19,
    effIdentify = 22,
    effGetChunk = 23,
    effSetChunk = 24,
    effProcessEvents = 25,
    effGetInputLatency = 32,
    effGetOutputLatency = 33,
    effGetPlugCategory = 35,
    effGetEffectName = 45,
    effGetVendorString = 47,
    effGetProductString = 48,
    effGetVendorVersion = 49,
    effCanDo = 51,
    effGetTailSize = 52,
    effGetVstVersion = 58,
    effGetProgramNameIndexed = 29
};

enum {
    effFlagsHasEditor = 1 << 0,
    effFlagsCanReplacing = 1 << 4,
    effFlagsCanDoubleReplacing = 1 << 12
};

enum { kPlugCategEffect = 1 };

/* ------------------------------------------------------------------ */
/* Plugin state                                                        */
/* ------------------------------------------------------------------ */

#define G6CT_VST_IN       8
#define G6CT_VST_OUT      2
#define G6CT_VST_CHUNK    1024
#define G6CT_VST_PARAMS   (G6CT_VST_IN + G6CT_VST_OUT)
#define G6CT_VST_UID      0x47364354 /* 'G6CT' */
#define G6CT_VST_VERSION  1100

#define EDITOR_W 340
#define EDITOR_H 250
#define METER_FALL_S 0.30   /* peak-hold release time constant */

/* VST channel index -> WAVEFORMATEXTENSIBLE channel-bit slot (g6ct in[12]). */
static const int g_slot[G6CT_VST_IN] = { 0, 1, 2, 3, 4, 5, 9, 10 };

static const char *g_in_name[G6CT_VST_IN] = { "In1", "In2", "In3", "In4",
                                              "In5", "In6", "In7", "In8" };
static const char *g_out_name[G6CT_VST_OUT] = { "OutL", "OutR" };

typedef struct {
    AEffect *effect;
    g6ct_state st;
    VstInt32 block_size;
    float sample_rate;
    /* float32 host path stages through the working precision per chunk */
    g6ct_real cin[G6CT_VST_IN][G6CT_VST_CHUNK];
    g6ct_real col[G6CT_VST_CHUNK];
    g6ct_real cor[G6CT_VST_CHUNK];
    /* metering (linear peak, decayed) */
    float meter_in[G6CT_VST_IN];
    float meter_out[G6CT_VST_OUT];
    float decay;
    /* editor */
    ERect rect;
    void *hwnd;
} G6ctVst;

/* Hosts may rewrite numInputs / numOutputs after negotiation, so never trust
 * the compile-time constants when touching their buffers. */
static int clamp_count(VstInt32 n, int limit)
{
    if (n < 0)
        return 0;
    return n > limit ? limit : (int)n;
}

/* Per-call decay for a peak-hold meter. */
static float decay_for(const G6ctVst *p, VstInt32 n)
{
    double sr = p->sample_rate > 0.0f ? (double)p->sample_rate : 48000.0;
    if (sr <= 0.0)
        sr = 48000.0;
    return (float)exp(-(double)n / (METER_FALL_S * sr));
}

/* Instant attack, exponential release. */
static float hold_level(float prev, float peak, float decay)
{
    float fall = prev * decay;
    return peak > fall ? peak : fall;
}

/* Meter value -> VST parameter.  Parameters are a normalised dB scale so the
 * number a host reads and the string it displays always agree; the editor is
 * what reports overshoot past 0 dB. */
static float level_to_param(float v)
{
    double db = v > 0.0f ? 20.0 * log10((double)v) : -60.0;

    if (db < -60.0)
        db = -60.0;
    if (db > 0.0)
        db = 0.0;
    return (float)((db + 60.0) / 60.0);
}

/* ------------------------------------------------------------------ */
/* Metering                                                            */
/* ------------------------------------------------------------------ */

static void meter_inputs(G6ctVst *p, const g6ct_real *const din[12], VstInt32 n)
{
    int c;

    for (c = 0; c < G6CT_VST_IN; c++) {
        const g6ct_real *x = din[g_slot[c]];
        float peak = 0.0f;

        if (x) {
            VstInt32 i;

            for (i = 0; i < n; i++) {
                float v = (float)fabs((double)x[i]);
                if (v > peak)
                    peak = v;
            }
        }
        p->meter_in[c] = hold_level(p->meter_in[c], peak, p->decay);
    }
}

static void meter_one(float *dst, const g6ct_real *x, VstInt32 n, float decay)
{
    float peak = 0.0f;

    if (x) {
        VstInt32 i;

        for (i = 0; i < n; i++) {
            float v = (float)fabs((double)x[i]);
            if (v > peak)
                peak = v;
        }
    }
    *dst = hold_level(*dst, peak, decay);
}

/* ------------------------------------------------------------------ */
/* Processing                                                          */
/* ------------------------------------------------------------------ */

static void VSTCALLBACK dsp_process_float(AEffect *e, float **inputs,
                                          float **outputs, VstInt32 n)
{
    G6ctVst *p;
    int ni;
    int no;
    VstInt32 done = 0;

    /* e is the AEffect the host handed us; a null one means nothing to do
     * and nothing to address, so bail before reading any of its fields. */
    if (!e)
        return;

    p = (G6ctVst *)e->object;
    ni = clamp_count(e->numInputs, G6CT_VST_IN);
    no = clamp_count(e->numOutputs, G6CT_VST_OUT);

    if (!p || n <= 0) {
        if (no > 0 && outputs[0])
            memset(outputs[0], 0, (size_t)(n > 0 ? n : 0) * sizeof(float));
        if (no > 1 && outputs[1])
            memset(outputs[1], 0, (size_t)(n > 0 ? n : 0) * sizeof(float));
        return;
    }

    while (done < n) {
        VstInt32 k = n - done;
        const g6ct_real *din[12];
        int c;

        if (k > G6CT_VST_CHUNK)
            k = G6CT_VST_CHUNK;

        /* decay is per chunk, and the last chunk may be shorter */
        p->decay = decay_for(p, k);

        memset(din, 0, sizeof din);
        for (c = 0; c < G6CT_VST_IN; c++) {
            g6ct_real *dst = p->cin[c];
            const float *src = c < ni ? inputs[c] : NULL;

            if (src) {
                VstInt32 j;

                src += done;
                for (j = 0; j < k; j++)
                    dst[j] = (g6ct_real)src[j];
            } else {
                memset(dst, 0, (size_t)k * sizeof *dst);
            }
            din[g_slot[c]] = dst;
        }

        meter_inputs(p, din, k);
        g6ct_process(&p->st, din, p->col, p->cor, (size_t)k);
        meter_one(&p->meter_out[0], p->col, k, p->decay);
        meter_one(&p->meter_out[1], p->cor, k, p->decay);

        if (no > 0 && outputs[0]) {
            VstInt32 j;
            for (j = 0; j < k; j++)
                outputs[0][done + j] = (float)p->col[j];
        }
        if (no > 1 && outputs[1]) {
            VstInt32 j;
            for (j = 0; j < k; j++)
                outputs[1][done + j] = (float)p->cor[j];
        }
        done += k;
    }
}

#ifdef G6CT_DOUBLE
static void VSTCALLBACK dsp_process_double(AEffect *e, double **inputs,
                                           double **outputs, VstInt32 n)
{
    G6ctVst *p;
    int ni;
    int no;
    const g6ct_real *din[12];
    g6ct_real *left;
    g6ct_real *right;
    int c;

    if (!e)
        return;

    p = (G6ctVst *)e->object;
    ni = clamp_count(e->numInputs, G6CT_VST_IN);
    no = clamp_count(e->numOutputs, G6CT_VST_OUT);

    if (!p || n <= 0) {
        if (no > 0 && outputs[0])
            memset(outputs[0], 0, (size_t)(n > 0 ? n : 0) * sizeof(double));
        if (no > 1 && outputs[1])
            memset(outputs[1], 0, (size_t)(n > 0 ? n : 0) * sizeof(double));
        return;
    }

    p->decay = decay_for(p, n);

    /* g6ct_real is double here, so the host buffers are used in place: no
     * staging copy and no precision change anywhere in the chain. */
    memset(din, 0, sizeof din);
    for (c = 0; c < G6CT_VST_IN; c++)
        din[g_slot[c]] = c < ni ? (const g6ct_real *)inputs[c] : NULL;

    left = (no > 0 && outputs[0]) ? (g6ct_real *)outputs[0] : p->col;
    right = (no > 1 && outputs[1]) ? (g6ct_real *)outputs[1] : p->cor;

    /* no chunking on this path, so the meter sees the whole block */
    meter_inputs(p, din, n);
    g6ct_process(&p->st, din, left, right, (size_t)n);
    meter_one(&p->meter_out[0], left, n, p->decay);
    meter_one(&p->meter_out[1], right, n, p->decay);
}
#endif /* G6CT_DOUBLE */

/* ------------------------------------------------------------------ */
/* Editor                                                              */
/* ------------------------------------------------------------------ */

static LRESULT CALLBACK editor_proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp);

static void draw_meter(HDC dc, int x, int top, int w, int h, float level,
                       const char *label, int small)
{
    int filled = 0;
    int i;
    RECT r;
    HBRUSH br;
    COLORREF col;
    char buf[32];
    double db;

    if (level > 0.0f) {
        db = 20.0 * log10((double)level);
        if (db > 0.0)
            db = 0.0;
        if (db < -60.0)
            db = -60.0;
        filled = (int)(((db + 60.0) / 60.0) * (double)h + 0.5);
    } else {
        db = -120.0;
    }
    if (filled > h)
        filled = h;
    if (filled < 0)
        filled = 0;

    /* trough */
    r.left = x;
    r.top = top;
    r.right = x + w;
    r.bottom = top + h;
    br = CreateSolidBrush(RGB(18, 18, 22));
    FillRect(dc, &r, br);
    DeleteObject(br);

    /* bar, one band per 6 dB so the colour steps are visible */
    for (i = 0; i < filled; i++) {
        double frac = (double)i / (double)h;
        if (frac > 0.90)
            col = RGB(230, 60, 50);
        else if (frac > 0.78)
            col = RGB(230, 190, 60);
        else
            col = RGB(70, 200, 90);

        r.left = x;
        r.right = x + w;
        r.bottom = top + h - i;
        r.top = r.bottom - 1;
        br = CreateSolidBrush(col);
        FillRect(dc, &r, br);
        DeleteObject(br);
    }

    /* frame */
    r.left = x;
    r.top = top;
    r.right = x + w;
    r.bottom = top + h;
    br = (HBRUSH)GetStockObject(GRAY_BRUSH);
    FrameRect(dc, &r, br);

    /* over-0 dB indicator, since the bar and the dB scale both stop at 0 */
    if (level > 1.0f) {
        r.left = x - 1;
        r.top = top - 5;
        r.right = x + w + 1;
        r.bottom = top - 1;
        br = CreateSolidBrush(RGB(240, 40, 30));
        FillRect(dc, &r, br);
        DeleteObject(br);
    } else {
        r.left = x - 1;
        r.top = top - 5;
        r.right = x + w + 1;
        r.bottom = top - 1;
        br = CreateSolidBrush(RGB(60, 60, 66));
        FillRect(dc, &r, br);
        DeleteObject(br);
    }

    SetTextColor(dc, RGB(190, 190, 200));
    TextOutA(dc, x - (small ? 2 : 6), top + h + 3, label, (int)strlen(label));

    if (db <= -119.0)
        strcpy(buf, " -inf");
    else
        sprintf(buf, "%5.1f", db);
    TextOutA(dc, x - (small ? 6 : 10), top + h + 17, buf, (int)strlen(buf));
}

static void paint_editor(HWND hwnd, const G6ctVst *p)
{
    PAINTSTRUCT ps;
    HDC dc;
    RECT rc;
    HBRUSH bg;

    dc = BeginPaint(hwnd, &ps);
    GetClientRect(hwnd, &rc);

    bg = CreateSolidBrush(RGB(34, 34, 40));
    FillRect(dc, &rc, bg);
    DeleteObject(bg);

    SetBkMode(dc, TRANSPARENT);
    SetTextColor(dc, RGB(225, 225, 235));
    TextOutA(dc, 12, 8, "g6ct  MatrixEncoder  7.1 -> binaural", 36);

    if (p) {
        int i;
        int x;
        SetTextColor(dc, RGB(120, 200, 255));
        TextOutA(dc, 12, 26, "INPUT", 5);
        TextOutA(dc, 232, 26, "OUTPUT", 6);

        for (i = 0; i < G6CT_VST_IN; i++) {
            x = 14 + i * 24;
            draw_meter(dc, x, 46, 18, 150, p->meter_in[i], g_in_name[i], 1);
        }
        for (i = 0; i < G6CT_VST_OUT; i++) {
            x = 236 + i * 52;
            draw_meter(dc, x, 46, 44, 150, p->meter_out[i], g_out_name[i], 0);
        }
    }

    EndPaint(hwnd, &ps);
}

static LRESULT CALLBACK editor_proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    const G6ctVst *p = (const G6ctVst *)GetWindowLongPtrW(hwnd, GWLP_USERDATA);

    switch (msg) {
    case WM_TIMER:
        InvalidateRect(hwnd, NULL, FALSE);
        return 0;

    case WM_PAINT:
        paint_editor(hwnd, p);
        return 0;

    case WM_ERASEBKGND:
        return 1;

    case WM_DESTROY:
        KillTimer(hwnd, 1);
        return 0;

    default:
        break;
    }
    (void)wp;
    (void)lp;
    return DefWindowProcW(hwnd, msg, wp, lp);
}

static void *editor_open(void *parent, G6ctVst *p)
{
    static int registered = 0;
    HWND hwnd;
    HINSTANCE inst;

    if (!parent)
        return NULL;

    inst = (HINSTANCE)GetWindowLongPtrW((HWND)parent, GWLP_HINSTANCE);

    if (!registered) {
        WNDCLASSW wc;

        memset(&wc, 0, sizeof wc);
        wc.style = CS_HREDRAW | CS_VREDRAW;
        wc.lpfnWndProc = editor_proc;
        wc.hInstance = inst;
        wc.hCursor = LoadCursorW(NULL, (LPCWSTR)IDC_ARROW);
        wc.lpszClassName = L"g6ct_editor_wnd";
        RegisterClassW(&wc);
        registered = 1;
    }

    hwnd = CreateWindowExW(0, L"g6ct_editor_wnd", L"g6ct",
                           WS_CHILD | WS_VISIBLE,
                           0, 0, EDITOR_W, EDITOR_H,
                           (HWND)parent, NULL, inst, NULL);
    if (!hwnd)
        return NULL;

    SetWindowLongPtrW(hwnd, GWLP_USERDATA, (LONG_PTR)p);
    SetTimer(hwnd, 1, 33, NULL);
    return hwnd;
}

static void editor_close(G6ctVst *p)
{
    if (p && p->hwnd) {
        DestroyWindow((HWND)p->hwnd);
        p->hwnd = NULL;
    }
}

/* ------------------------------------------------------------------ */
/* Dispatcher                                                          */
/* ------------------------------------------------------------------ */

static void copy_str(void *dst, const char *src, size_t cap)
{
    if (!dst || cap == 0)
        return;
    strncpy((char *)dst, src, cap - 1);
    ((char *)dst)[cap - 1] = '\0';
}

static VstIntPtr VSTCALLBACK dsp_dispatcher(AEffect *e, VstInt32 op,
                                            VstInt32 index, VstIntPtr value,
                                            void *ptr, float opt)
{
    G6ctVst *p = e ? (G6ctVst *)e->object : NULL;

    switch (op) {
    case effOpen:
        return 0;

    case effClose:
        if (p) {
            editor_close(p);
            free(p);
        }
        free(e);
        return 0;

    case effSetSampleRate:
        if (p)
            p->sample_rate = opt;
        return 0;

    case effSetBlockSize:
        if (p)
            p->block_size = (VstInt32)value;
        return 0;

    case effMainsChanged:
        if (p) {
            g6ct_reset(&p->st);
            memset(p->meter_in, 0, sizeof p->meter_in);
            memset(p->meter_out, 0, sizeof p->meter_out);
        }
        return 0;

    case effEditGetRect:
        if (p && ptr) {
            p->rect.top = 0;
            p->rect.left = 0;
            p->rect.bottom = EDITOR_H;
            p->rect.right = EDITOR_W;
            *(ERect **)ptr = &p->rect;
            return 1;
        }
        return 0;

    case effEditOpen:
        if (p) {
            p->hwnd = editor_open(ptr, p);
            return p->hwnd ? 1 : 0;
        }
        return 0;

    case effEditClose:
        editor_close(p);
        return 0;

    case effEditIdle:
        if (p && p->hwnd)
            InvalidateRect((HWND)p->hwnd, NULL, FALSE);
        return 0;

    case effGetEffectName:
        copy_str(ptr, "g6ct MatrixEncoder", 32);
        return 1;

    case effGetVendorString:
        copy_str(ptr, "g6ct", 64);
        return 1;

    case effGetProductString:
        copy_str(ptr, "MatrixEncoder 7.1 to binaural", 64);
        return 1;

    case effGetVendorVersion:
        return G6CT_VST_VERSION;

    case effGetVstVersion:
        return 2400;

    case effGetPlugCategory:
        return kPlugCategEffect;

    case effGetTailSize:
        return 0;

    case effGetProgramName:
        copy_str(ptr, "Default", 24);
        return 0;

    case effGetProgramNameIndexed:
        if (ptr && index == 0) {
            copy_str(ptr, "Default", 24);
            return 1;
        }
        return 0;

    case effGetParamName:
        if (ptr && index >= 0 && index < G6CT_VST_PARAMS) {
            if (index < G6CT_VST_IN)
                copy_str(ptr, g_in_name[index], 8);
            else
                copy_str(ptr, g_out_name[index - G6CT_VST_IN], 8);
            return 1;
        }
        return 0;

    case effGetParamLabel:
        copy_str(ptr, "dB", 8);
        return 1;

    case effGetParamDisplay: {
        float v;
        char buf[24];
        double db;

        if (!p || !ptr || index < 0 || index >= G6CT_VST_PARAMS)
            return 0;
        v = index < G6CT_VST_IN ? p->meter_in[index]
                                : p->meter_out[index - G6CT_VST_IN];
        db = v > 0.0f ? 20.0 * log10((double)v) : -60.0;
        if (db < -60.0)
            db = -60.0;
        if (db > 0.0)
            db = 0.0;
        sprintf(buf, "%.1f", db);
        copy_str(ptr, buf, 24);
        return 1;
    }

    case effGetChunk:
        return 0; /* no opaque state: everything is fixed 7.1 */

    case effSetChunk:
        if (p) {
            g6ct_reset(&p->st);
            memset(p->meter_in, 0, sizeof p->meter_in);
            memset(p->meter_out, 0, sizeof p->meter_out);
        }
        return 0;

    case effProcessEvents:
        return 0;

    case effGetInputLatency:
    case effGetOutputLatency:
        return 0;

    case effCanDo: {
        const char *s = (const char *)ptr;

        if (!s)
            return 0;
        if (!strcmp(s, "offline"))
            return 1;
        return 0;
    }

    default:
        (void)index;
        (void)value;
        (void)opt;
        return 0;
    }
}

static void VSTCALLBACK dsp_set_parameter(AEffect *e, VstInt32 index, float v)
{
    (void)e;
    (void)index;
    (void)v; /* meters are read-only */
}

/* The AEffect* is fixed by the VST2 ABI (getParameter is a host callback and
 * the host passes a mutable pointer), so it stays non-const even though this
 * function only reads. */
static float VSTCALLBACK dsp_get_parameter(AEffect *e, VstInt32 index)
{
    const G6ctVst *p = e ? (const G6ctVst *)e->object : NULL;

    if (!p || index < 0 || index >= G6CT_VST_PARAMS)
        return 0.0f;

    if (index < G6CT_VST_IN)
        return level_to_param(p->meter_in[index]);
    index -= G6CT_VST_IN;
    return level_to_param(p->meter_out[index]);
}

/* ------------------------------------------------------------------ */
/* Entry point                                                         */
/* ------------------------------------------------------------------ */

VST_EXPORT AEffect *VSTPluginMain(audioMasterCallback audioMaster)
{
    AEffect *e;
    G6ctVst *p;

    (void)audioMaster;

    e = (AEffect *)calloc(1, sizeof *e);
    p = (G6ctVst *)calloc(1, sizeof *p);
    if (!e || !p) {
        free(e);
        free(p);
        return NULL;
    }

    g6ct_init(&p->st, G6CT_MASK_7_1);
    p->effect = e;
    p->block_size = G6CT_VST_CHUNK;
    p->sample_rate = 48000.0f;
    p->decay = decay_for(p, 512);

    e->magic = kEffectMagic;
    e->dispatcher = (VstIntPtr)dsp_dispatcher;
    e->process = (VstIntPtr)dsp_process_float;
    e->setParameter = (VstIntPtr)dsp_set_parameter;
    e->getParameter = (VstIntPtr)dsp_get_parameter;
    e->numPrograms = 1;
    e->numParams = G6CT_VST_PARAMS;
    e->numInputs = G6CT_VST_IN;
    e->numOutputs = G6CT_VST_OUT;
    e->flags = effFlagsCanReplacing | effFlagsHasEditor;
#ifdef G6CT_DOUBLE
    e->flags |= effFlagsCanDoubleReplacing;
    e->processDoubleReplacing = (VstIntPtr)dsp_process_double;
#endif
    e->initialDelay = 0;
    e->realQualities = 0;
    e->offQualities = 0;
    e->ioRatio = 1.0f;
    e->object = p;
    e->user = NULL;
    e->uniqueID = G6CT_VST_UID;
    e->version = G6CT_VST_VERSION;
    e->processReplacing = (VstIntPtr)dsp_process_float;

    return e;
}

/* Pre-2.4 hosts look for a plain "main" export. */
VST_EXPORT AEffect *main(audioMasterCallback audioMaster)
{
    return VSTPluginMain(audioMaster);
}
