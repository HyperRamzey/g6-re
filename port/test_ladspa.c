/*
 * test_ladspa.c - host-side regression test for the LADSPA wrapper.
 *
 * The host connects every port once (the normal LADSPA behaviour), runs
 * several blocks, and compares each block with the same DSP called directly.
 * The original f64 wrapper advanced its stored port pointers inside run(),
 * so the second block read and wrote past the caller's buffers; with this
 * test the second comparison fails (and ASan aborts).  The control-port
 * default and clamping are checked too.
 *
 * Build with -DG6CT_DOUBLE for the float64 wrapper.
 */
#include "g6ct.h"

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ------------------------------------------------------------------ */
/* Minimal LADSPA 1.1 ABI, identical to g6ct_ladspa.c                  */
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

extern const LADSPA_Descriptor *ladspa_descriptor(unsigned long index);

/* ------------------------------------------------------------------ */

enum {
    P_FL = 0, P_FR, P_FC, P_LFE, P_BL, P_BR, P_SL, P_SR,
    P_OUTL, P_OUTR, P_MASK, PORT_COUNT
};

#define NMAX 8192

static uint32_t rng_state;

static void fill_input(float in[8][NMAX], int n)
{
    int c, i;

    for (i = 0; i < n; i++) {
        for (c = 0; c < 8; c++) {
            int32_t v;
            rng_state = rng_state * 1664525u + 1013904223u;
            v = (int32_t)(rng_state >> 8) - 8388608;
            in[c][i] = (float)((double)v * (1.0 / 8388608.0));
        }
    }
}

static void ref_render(g6ct_state *st, float in[8][NMAX], int n,
                       g6ct_real *outL, g6ct_real *outR)
{
    static const int slot[8] = { 0, 1, 2, 3, 4, 5, 9, 10 };
    static g6ct_real tmp[8][NMAX];
    const g6ct_real *p[12] = { NULL };
    int c, i;

    for (c = 0; c < 8; c++)
        for (i = 0; i < n; i++)
            tmp[c][i] = (g6ct_real)in[c][i];
    for (c = 0; c < 8; c++)
        p[slot[c]] = tmp[c];
    g6ct_process(st, p, outL, outR, (size_t)n);
}

static int compare_block(const char *what, const float *gotL, const float *gotR,
                         const g6ct_real *expL, const g6ct_real *expR, int n)
{
    int i, diffs = 0;

    for (i = 0; i < n; i++) {
        if (gotL[i] != (float)expL[i] || gotR[i] != (float)expR[i])
            diffs++;
    }
    printf("  %-38s %s", what, diffs ? "FAIL" : "ok");
    if (diffs)
        printf(" (%d/%d samples differ)", diffs, n);
    printf("\n");
    return diffs == 0;
}

int main(void)
{
    const LADSPA_Descriptor *d;
    LADSPA_Handle h, h2;
    static float in[8][NMAX], outL[NMAX], outR[NMAX];
    static g6ct_real rl[NMAX], rr[NMAX];
    g6ct_state ref;
    float mask;
    const LADSPA_PortRangeHint *mh;
    const int blocks[] = { 4096, 4096, 1000, 257, 1024, 13 };
    int bad = 0, i, nb, hint_ok;

    printf("LADSPA host test (%s)\n", g6ct_precision());

    d = ladspa_descriptor(0);
    if (!d) {
        printf("FAIL: no descriptor\n");
        return 1;
    }

    mh = &d->PortRangeHints[P_MASK];
    hint_ok = (mh->HintDescriptor & 0x2) != 0        /* BOUNDED_BELOW */
              && (mh->HintDescriptor & 0x4) != 0    /* BOUNDED_ABOVE */
              && (mh->HintDescriptor & 0x20) != 0   /* INTEGER       */
              && mh->LowerBound == 0.0f
              && mh->UpperBound == 4095.0f;
    printf("  mask hint bounded 0..4095, integer: %s\n", hint_ok ? "ok" : "FAIL");
    if (!hint_ok)
        bad++;

    h = d->instantiate(d, 48000);
    if (!h) {
        printf("FAIL: instantiate\n");
        return 1;
    }
    for (i = 0; i < 8; i++)
        d->connect_port(h, (unsigned long)i, in[i]);
    d->connect_port(h, P_OUTL, outL);
    d->connect_port(h, P_OUTR, outR);
    d->connect_port(h, P_MASK, &mask);

    /* The host connects once and then runs many blocks.  Each run() must
     * start at offset 0 of the caller's buffers, not at the end of the
     * previous block. */
    rng_state = 0x67365431;
    mask = 1599.0f;                     /* 0x63F, 7.1 */
    g6ct_init(&ref, G6CT_MASK_7_1);
    d->activate(h);

    nb = (int)(sizeof blocks / sizeof blocks[0]);
    for (i = 0; i < nb; i++) {
        int n = blocks[i];
        char label[64];

        fill_input(in, n);
        memset(outL, 0, sizeof outL);
        memset(outR, 0, sizeof outR);
        d->run(h, (unsigned long)n);
        ref_render(&ref, in, n, rl, rr);

        snprintf(label, sizeof label, "block %d (%d frames%s)", i + 1, n,
                 i == 1 ? ", second call" : "");
        if (!compare_block(label, outL, outR, rl, rr, n))
            bad++;
    }

    /* Control port: 0 is the documented 7.1 default, values are clamped to
     * the hinted range, and non-finite/negative values fall back to 7.1. */
    {
        struct { float v; unsigned expect; const char *name; } cases[] = {
            { 0.0f, G6CT_MASK_7_1, "0 -> 7.1 default" },
            { 3.0f, G6CT_FL | G6CT_FR, "0x3 -> stereo bypass" },
            { 1599.0f, G6CT_MASK_7_1, "1599 -> 7.1" },
            { NAN, G6CT_MASK_7_1, "NaN -> 7.1 default" },
            { -1.0f, G6CT_MASK_7_1, "-1 -> 7.1 default" },
            { -INFINITY, G6CT_MASK_7_1, "-inf -> 7.1 default" },
            { INFINITY, G6CT_MASK_7_1, "+inf -> 7.1 default" },
            { 1.0e30f, 4095u, "1e30 -> 4095 clamp" },
            { 4095.9f, 4095u, "4095.9 -> 4095 clamp" },
        };
        size_t ci;
        int n = 1000;

        for (ci = 0; ci < sizeof cases / sizeof cases[0]; ci++) {
            char label[64];

            mask = cases[ci].v;
            d->activate(h);
            g6ct_init(&ref, cases[ci].expect);
            fill_input(in, n);
            memset(outL, 0, sizeof outL);
            memset(outR, 0, sizeof outR);
            d->run(h, (unsigned long)n);
            ref_render(&ref, in, n, rl, rr);

            snprintf(label, sizeof label, "control %s", cases[ci].name);
            if (!compare_block(label, outL, outR, rl, rr, n))
                bad++;
        }
    }

    d->cleanup(h);

    /* A host may leave the control port unconnected; the instance's initial
     * mask (7.1) must be used. */
    h2 = d->instantiate(d, 48000);
    if (!h2) {
        printf("FAIL: instantiate (unconnected control)\n");
        return 1;
    }
    for (i = 0; i < 8; i++)
        d->connect_port(h2, (unsigned long)i, in[i]);
    d->connect_port(h2, P_OUTL, outL);
    d->connect_port(h2, P_OUTR, outR);

    {
        int n = 1000;

        g6ct_init(&ref, G6CT_MASK_7_1);
        fill_input(in, n);
        memset(outL, 0, sizeof outL);
        memset(outR, 0, sizeof outR);
        d->run(h2, (unsigned long)n);
        ref_render(&ref, in, n, rl, rr);
        if (!compare_block("unconnected control -> 7.1", outL, outR, rl, rr, n))
            bad++;
    }
    d->cleanup(h2);

    printf("%s (%d failures)\n", bad ? "FAILED" : "PASSED", bad);
    return bad ? 1 : 0;
}
