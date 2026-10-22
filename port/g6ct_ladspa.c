/*
 * g6ct_ladspa.c - LADSPA wrapper for the Creative MatrixEncoder port.
 *
 * PipeWire filter-chain usage:
 *   { type = ladspa name = enc plugin = "/path/libg6ct_ladspa.so"
 *     label = "g6ct_matrix_encoder" control = { "Channel Mask" = 1599 } }
 *
 * Ports: 8 audio inputs (FL FR FC LFE BL BR SL SR), 2 audio outputs
 * (OutL OutR) and one control input "Channel Mask".
 */
#include <stdlib.h>
#include <string.h>

#include "g6ct.h"

/* ------------------------------------------------------------------ */
/* Minimal LADSPA 1.1 ABI (we do not depend on an installed ladspa.h)  */
/* ------------------------------------------------------------------ */

typedef float LADSPA_Data;
typedef int LADSPA_Properties;
typedef int LADSPA_PortDescriptor;
typedef unsigned long LADSPA_PortRangeHintDescriptor;

typedef struct {
    LADSPA_PortRangeHintDescriptor HintDescriptor;
    LADSPA_Data LowerBound;
    LADSPA_Data UpperBound;
} LADSPA_PortRangeHint;

typedef struct _LADSPA_Descriptor LADSPA_Descriptor;
typedef void *LADSPA_Handle;

struct _LADSPA_Descriptor {
    unsigned long UniqueID;
    const char *Label;
    LADSPA_Properties Properties;
    const char *Name;
    const char *Maker;
    const char *Copyright;
    unsigned long PortCount;
    const LADSPA_PortDescriptor *PortDescriptors;
    const char *const *PortNames;
    const LADSPA_PortRangeHint *PortRangeHints;
    void *ImplementationData;
    LADSPA_Handle (*instantiate)(const LADSPA_Descriptor *, unsigned long);
    void (*connect_port)(LADSPA_Handle, unsigned long, LADSPA_Data *);
    void (*activate)(LADSPA_Handle);
    void (*run)(LADSPA_Handle, unsigned long);
    void (*run_adding)(LADSPA_Handle, unsigned long);
    void (*set_run_adding_gain)(LADSPA_Handle, LADSPA_Data);
    void (*deactivate)(LADSPA_Handle);
    void (*cleanup)(LADSPA_Handle);
};

#define LADSPA_PORT_INPUT     0x1
#define LADSPA_PORT_OUTPUT    0x2
#define LADSPA_PORT_CONTROL   0x4
#define LADSPA_PORT_AUDIO     0x8

#define HINT_INTEGER     0x20

/* ------------------------------------------------------------------ */

enum {
    P_FL = 0, P_FR, P_FC, P_LFE, P_BL, P_BR, P_SL, P_SR,
    P_OUTL, P_OUTR, P_MASK, PORT_COUNT
};

#define G6CT_CHUNK 256

#ifdef G6CT_DOUBLE
/* Port index of each of the 8 input channels, and its WAVE bit position. */
static const unsigned char k_pmap[8] = { P_FL, P_FR, P_FC, P_LFE,
                                         P_BL, P_BR, P_SL, P_SR };
static const unsigned char k_slot[8] = { 0, 1, 2, 3, 4, 5, 9, 10 };
#endif

typedef struct {
    g6ct_state st;
    float *p[PORT_COUNT];
    unsigned mask_cache;
#ifdef G6CT_DOUBLE
    /* LADSPA carries float32; the double build converts per chunk. */
    g6ct_real cin[8][G6CT_CHUNK];
    g6ct_real col[G6CT_CHUNK], cor[G6CT_CHUNK];
#endif
} G6ctInstance;

static const LADSPA_PortDescriptor g_ports[PORT_COUNT] = {
    LADSPA_PORT_INPUT | LADSPA_PORT_AUDIO,
    LADSPA_PORT_INPUT | LADSPA_PORT_AUDIO,
    LADSPA_PORT_INPUT | LADSPA_PORT_AUDIO,
    LADSPA_PORT_INPUT | LADSPA_PORT_AUDIO,
    LADSPA_PORT_INPUT | LADSPA_PORT_AUDIO,
    LADSPA_PORT_INPUT | LADSPA_PORT_AUDIO,
    LADSPA_PORT_INPUT | LADSPA_PORT_AUDIO,
    LADSPA_PORT_INPUT | LADSPA_PORT_AUDIO,
    LADSPA_PORT_OUTPUT | LADSPA_PORT_AUDIO,
    LADSPA_PORT_OUTPUT | LADSPA_PORT_AUDIO,
    LADSPA_PORT_INPUT | LADSPA_PORT_CONTROL,
};

static const char *const g_port_names[PORT_COUNT] = {
    "FL", "FR", "FC", "LFE", "BL", "BR", "SL", "SR",
    "OutL", "OutR", "Channel Mask",
};

static const LADSPA_PortRangeHint g_hints[PORT_COUNT] = {
    { 0, 0, 0 }, { 0, 0, 0 }, { 0, 0, 0 }, { 0, 0, 0 },
    { 0, 0, 0 }, { 0, 0, 0 }, { 0, 0, 0 }, { 0, 0, 0 },
    { 0, 0, 0 }, { 0, 0, 0 },
    { HINT_INTEGER, 0.0f, 4095.0f },
};

static void *inst(const LADSPA_Descriptor *d, unsigned long rate)
{
    G6ctInstance *i = calloc(1, sizeof *i);

    (void)d;
    (void)rate;
    if (!i)
        return NULL;
    g6ct_init(&i->st, G6CT_MASK_7_1);
    i->mask_cache = G6CT_MASK_7_1;
    return i;
}

static void conn(LADSPA_Handle h, unsigned long port, LADSPA_Data *loc)
{
    G6ctInstance *i = h;

    if (port < PORT_COUNT)
        i->p[port] = loc;
}

static void act(LADSPA_Handle h)
{
    G6ctInstance *i = h;

    g6ct_reset(&i->st);
}

static void run(LADSPA_Handle h, unsigned long n)
{
    G6ctInstance *i = h;
#ifndef G6CT_DOUBLE
    float *in[12] = { NULL };
#endif

    if (i->p[P_MASK]) {
        unsigned m = (unsigned)(*i->p[P_MASK] + 0.5f) & 0xFFFFu;

        if (m != i->mask_cache) {
            /* mask change keeps the filter history, as re-locking the
             * APO would; only the active matrix taps change */
            i->st.mask = m;
            i->mask_cache = m;
        }
    }

#ifndef G6CT_DOUBLE
    in[0] = i->p[P_FL];
    in[1] = i->p[P_FR];
    in[2] = i->p[P_FC];
    in[3] = i->p[P_LFE];
    in[4] = i->p[P_BL];
    in[5] = i->p[P_BR];
    in[9] = i->p[P_SL];
    in[10] = i->p[P_SR];
#endif

    if (!i->p[P_OUTL] || !i->p[P_OUTR])
        return;

#ifdef G6CT_DOUBLE
    while (n) {
        unsigned long k = n > G6CT_CHUNK ? G6CT_CHUNK : n, j;
        g6ct_real *din[12] = { NULL };
        int c;

        for (c = 0; c < 8; c++) {
            const float *src = i->p[k_pmap[c]];
            g6ct_real *dst = i->cin[c];

            if (src) {
                for (j = 0; j < k; j++)
                    dst[j] = (g6ct_real)src[j];
            } else {
                memset(dst, 0, k * sizeof *dst);
            }
            din[k_slot[c]] = dst;
        }

        g6ct_process(&i->st, din, i->col, i->cor, (size_t)k);

        for (j = 0; j < k; j++) {
            i->p[P_OUTL][j] = (float)i->col[j];
            i->p[P_OUTR][j] = (float)i->cor[j];
        }
        for (c = 0; c < 8; c++)
            if (i->p[k_pmap[c]])
                i->p[k_pmap[c]] += k;
        i->p[P_OUTL] += k;
        i->p[P_OUTR] += k;
        n -= k;
    }
#else
    g6ct_process(&i->st, in, i->p[P_OUTL], i->p[P_OUTR], (size_t)n);
#endif
}

static void dact(LADSPA_Handle h)
{
    (void)h;
}

static void fin(LADSPA_Handle h)
{
    free(h);
}

static const LADSPA_Descriptor g_desc = {
    /* UniqueID */ 0x67365431UL,
    /* Label    */ "g6ct_matrix_encoder",
    /* Props    */ 0,
    /* Name     */ "Sound BlasterX G6 Creative MatrixEncoder 7.1 to binaural",
    /* Maker    */ "Clean-room port of KSUSBAPO64.dll CMatrixEncoderEfxMod",
    /* Copyright*/ "none",
    /* PortCount*/ PORT_COUNT,
    /* PortDescriptors */ g_ports,
    /* PortNames        */ g_port_names,
    /* PortRangeHints   */ g_hints,
    /* ImplementationData */ NULL,
    inst, conn, act, run, NULL, NULL, dact, fin,
};

const LADSPA_Descriptor *ladspa_descriptor(unsigned long index)
{
    return index == 0 ? &g_desc : NULL;
}
