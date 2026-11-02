/*
 * test_ir.c - verification harness for the g6ct port.
 *
 * Renders the 8 x 2 impulse-response matrix and checks it against the
 * analytic transfer functions of the coefficient sets, so a mistake in
 * the matrix weights or in the all-pass cascade cannot pass silently.
 *
 * It also checks the phase relationship between the ears (a magnitude-only
 * test cannot see a flipped surround sign), the channel-mask gating, and a
 * deterministic render whose FNV-1a hash is committed below.  The float32
 * hash is the same value the real DLL produces for the same input (see
 * ../apo-harness/verification_dll_wine.txt), so it is a DLL-free regression
 * test for the bit-exact build.
 */
#include "g6ct.h"

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define N 4096
#define SR 48000.0
#define GN 48000

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

#ifdef G6CT_DOUBLE
/* Live-renderer hash (no DLL equivalent: the DLL is float32). */
#define GOLDEN_EXPECT 0x5f78798536b3fa72ULL
#else
/* Verified against KSUSBAPO64.dll for golden_in8.raw: bit-identical. */
#define GOLDEN_EXPECT 0x684d7c9b2515f759ULL
#endif

static const char *names[8] = { "FL", "FR", "FC", "LFE", "BL", "BR", "SL", "SR" };

static double dft_mag(const g6ct_real *h, int n, double hz)
{
    double w = 2.0 * M_PI * hz / SR;
    double re = 0.0, im = 0.0;
    int i;

    for (i = 0; i < n; i++) {
        re += h[i] * cos(w * i);
        im -= h[i] * sin(w * i);
    }
    return sqrt(re * re + im * im);
}

static double cascade_mag(const g6ct_ap2 *a, const g6ct_ap2 *b, double hz)
{
    double w = 2.0 * M_PI * hz / SR;
    return g6ct_ap2_mag(a, w) * g6ct_ap2_mag(b, w);
}

static double energy(const g6ct_real *x, int n)
{
    double e = 0.0;
    int i;

    for (i = 0; i < n; i++)
        e += (double)x[i] * (double)x[i];
    return e;
}

static double maxabs(const g6ct_real *x, int n)
{
    double m = 0.0;
    int i;

    for (i = 0; i < n; i++) {
        double v = fabs((double)x[i]);
        if (v > m)
            m = v;
    }
    return m;
}

static double corr(const g6ct_real *a, const g6ct_real *b, int n)
{
    double ab = 0.0, aa = 0.0, bb = 0.0;
    int i;

    for (i = 0; i < n; i++) {
        ab += (double)a[i] * (double)b[i];
        aa += (double)a[i] * (double)a[i];
        bb += (double)b[i] * (double)b[i];
    }
    return (aa > 0.0 && bb > 0.0) ? ab / sqrt(aa * bb) : 0.0;
}

static uint64_t fnv_u32(uint64_t h, uint32_t v)
{
    h ^= v;
    h *= 1099511628211ULL;
    return h;
}

/* Render 8 deinterleaved channels through a fresh state with a given mask. */
static void render_mask(unsigned mask, const g6ct_real *const src[8],
                        g6ct_real *outL, g6ct_real *outR, int n)
{
    static const int slot[8] = { 0, 1, 2, 3, 4, 5, 9, 10 };
    const g6ct_real *in[12] = { NULL };
    g6ct_state st;
    int c;

    g6ct_init(&st, mask);
    for (c = 0; c < 8; c++)
        in[slot[c]] = src[c];
    g6ct_process(&st, in, outL, outR, (size_t)n);
}

static int same_render(unsigned ma, unsigned mb,
                       const g6ct_real *const src[8], int n)
{
    static g6ct_real al[N], ar[N], bl[N], br[N];
    int i;

    render_mask(ma, src, al, ar, n);
    render_mask(mb, src, bl, br, n);
    for (i = 0; i < n; i++)
        if (al[i] != bl[i] || ar[i] != br[i])
            return 0;
    return 1;
}

int main(void)
{
    static g6ct_real irL[8][N], irR[8][N];
    static g6ct_real buf[8][1024];
    const double probe_hz[] = { 50.0, 440.0, 1000.0, 5000.0, 15000.0 };
    int ch, i, k, bad = 0;

    printf("g6ct impulse-response matrix (%d taps @ %.0f Hz, mask 0x%03X, %s)\n\n",
           N, SR, G6CT_MASK_7_1, g6ct_precision());

    for (ch = 0; ch < 8; ch++) {
        g6ct_state st;
        int off;

        g6ct_init(&st, G6CT_MASK_7_1);
        for (off = 0; off < N; off += 1024) {
            /* WAVE bit position: FL FR FC LFE BL BR -> 0..5, SL SR -> 9,10 */
            static const int slot[8] = { 0, 1, 2, 3, 4, 5, 9, 10 };
            const g6ct_real *in[12] = { NULL };
            int n = (N - off) < 1024 ? (N - off) : 1024;

            memset(buf, 0, sizeof buf);
            for (i = 0; i < 8; i++)
                in[slot[i]] = buf[i];
            if (off == 0)
                buf[ch][0] = (g6ct_real)1.0;
            g6ct_process(&st, in, &irL[ch][off], &irR[ch][off], (size_t)n);
        }
    }

    printf("channel     DC gain L/R      |H| @ 1 kHz L/R     first taps L\n");
    for (ch = 0; ch < 8; ch++) {
        double dcL = 0.0, dcR = 0.0, k1L, k1R;

        for (i = 0; i < N; i++) {
            dcL += irL[ch][i];
            dcR += irR[ch][i];
        }
        k1L = dft_mag(irL[ch], N, 1000.0);
        k1R = dft_mag(irR[ch], N, 1000.0);
        printf("%-3s      %+.9f / %+.9f   %.9f / %.9f   ", names[ch], dcL, dcR, k1L, k1R);
        for (i = 0; i < 5; i++)
            printf("%+.6f ", irL[ch][i]);
        printf("\n");
    }

    /* The front branches must be pure all-pass: unity magnitude. */
    {
        g6ct_state st;
        g6ct_init(&st, G6CT_MASK_7_1);
        printf("\nall-pass cascade magnitude (front A*B, surround C*D):\n");
        for (k = 0; k < (int)(sizeof probe_hz / sizeof probe_hz[0]); k++) {
            double fab = cascade_mag(&st.front_l[0], &st.front_l[1], probe_hz[k]);
            double fcd = cascade_mag(&st.sur_l[0], &st.sur_l[1], probe_hz[k]);

            printf("  %8.1f Hz  |AB| = %.12f   |CD| = %.12f\n",
                   probe_hz[k], fab, fcd);
            if (fabs(fab - 1.0) > 1e-6 || fabs(fcd - 1.0) > 1e-6)
                bad++;
        }
    }

    /* Cross-check the measured IR against  weight * all-pass  at 1 kHz. */
    printf("\nmeasured vs expected |H(1 kHz)| (exact float weights x all-pass):\n");
    {
        g6ct_state st;
        double ab, cd;
        const double k707 = 0.7070000171661377, k485 = 0.48500001430511475;
        const double k619 = 0.6190000176429749, k786 = 0.7860000133514404;
        const double k875 = 0.875;
        const double wl[8] = { 1.0, 0.0, k707, k707, k786, k619, k875, k485 };
        const double wr[8] = { 0.0, 1.0, k707, k707, -k619, -k786, -k485, -k875 };

        g6ct_init(&st, G6CT_MASK_7_1);
        ab = cascade_mag(&st.front_l[0], &st.front_l[1], 1000.0);
        cd = cascade_mag(&st.sur_l[0], &st.sur_l[1], 1000.0);
        for (ch = 0; ch < 8; ch++) {
            double expL = fabs(wl[ch]) * (ch < 4 ? ab : cd);
            double expR = fabs(wr[ch]) * (ch < 4 ? ab : cd);
            double gotL = dft_mag(irL[ch], N, 1000.0);
            double gotR = dft_mag(irR[ch], N, 1000.0);
            /* 1e-4 allows for the 4096-tap truncation of the 0.99485 pole */
            int ok = fabs(gotL - expL) < 1e-4 && fabs(gotR - expR) < 1e-4;

            if (!ok)
                bad++;
            printf("  %-3s  L %.9f (exp %.9f)  R %.9f (exp %.9f)  %s\n",
                   names[ch], gotL, expL, gotR, expR, ok ? "ok" : "MISMATCH");
        }
    }

    /* Stability: every pole must lie inside the unit circle. */
    printf("\nsection poles (radius must be < 1):\n");
    {
        g6ct_state st;
        g6ct_ap2 *secs[8];
        const char *labels[8] = { "frontL.A", "frontL.B", "surL.C", "surL.D",
                                  "frontR.A", "frontR.B", "surR.C", "surR.D" };

        g6ct_init(&st, G6CT_MASK_7_1);
        secs[0] = &st.front_l[0]; secs[1] = &st.front_l[1];
        secs[2] = &st.sur_l[0];   secs[3] = &st.sur_l[1];
        secs[4] = &st.front_r[0]; secs[5] = &st.front_r[1];
        secs[6] = &st.sur_r[0];   secs[7] = &st.sur_r[1];
        for (i = 0; i < 8; i++) {
            double a1 = (double)secs[i]->a1, a2 = (double)secs[i]->a2;
            double disc = a1 * a1 - 4.0 * a2;
            double r;
            if (disc >= 0.0) {
                double sq = sqrt(disc);
                double r1 = fabs((-a1 + sq) / 2.0), r2 = fabs((-a1 - sq) / 2.0);
                r = r1 > r2 ? r1 : r2;
            } else {
                r = sqrt(a2);
            }
            if (r >= 1.0)
                bad++;
            printf("  %-9s a1=%+.9f a2=%+.9f  rmax=%.9f %s\n",
                   labels[i], a1, a2, r, r < 1.0 ? "stable" : "UNSTABLE");
        }
    }

    /* The defining feature of the surround path is the sign: L and R must be
     * anti-phase for BL/BR/SL/SR.  Magnitude-only checks cannot see a flip. */
    printf("\nsurround phase (normalised L/R correlation over the IR):\n");
    {
        static const int sur[4] = { 4, 5, 6, 7 };

        for (k = 0; k < 4; k++) {
            double c, eL, eR;
            int ok;

            ch = sur[k];
            c = corr(irL[ch], irR[ch], N);
            eL = energy(irL[ch], N);
            eR = energy(irR[ch], N);
            ok = (c < -0.999999 && eL > 1e-12 && eR > 1e-12);
            if (!ok)
                bad++;
            printf("  %-3s corr=%+.9f  E(L)/E(R)=%.9f  %s\n",
                   names[ch], c, eR > 0.0 ? eL / eR : 0.0,
                   ok ? "anti-phase" : "FAIL");
        }
    }

    /* FL must not leak into the right ear (and FR not into the left). */
    printf("\nfront isolation (max |opposite ear| / max |same ear|):\n");
    {
        double leakL = maxabs(irR[0], N) / maxabs(irL[0], N);
        double leakR = maxabs(irL[1], N) / maxabs(irR[1], N);
        int ok = leakL < 1e-7 && leakR < 1e-7;

        if (!ok)
            bad++;
        printf("  FL -> R %.3e   FR -> L %.3e   %s\n",
               leakL, leakR, ok ? "isolated" : "FAIL");
    }

    /* Back-centre path: both ears the same magnitude, opposite sign. */
    printf("\nback-centre (mask 0x%03X):\n", G6CT_MASK_7_1 | G6CT_BC);
    {
        static g6ct_real bl[N], br[N], bc[1024];
        const g6ct_real *in[12] = { NULL };
        g6ct_state st;
        double c, eL, eR, got, exp;
        int off;

        g6ct_init(&st, G6CT_MASK_7_1 | G6CT_BC);
        for (off = 0; off < N; off += 1024) {
            int n = (N - off) < 1024 ? (N - off) : 1024;

            memset(bc, 0, sizeof bc);
            if (off == 0)
                bc[0] = (g6ct_real)1.0;
            memset(in, 0, sizeof in);
            in[8] = bc;
            g6ct_process(&st, in, &bl[off], &br[off], (size_t)n);
        }
        c = corr(bl, br, N);
        eL = energy(bl, N);
        eR = energy(br, N);
        got = dft_mag(bl, N, 1000.0);
        exp = 0.7070000171661377 * cascade_mag(&st.sur_l[0], &st.sur_l[1], 1000.0);
        {
            int ok = c < -0.999999 && fabs(eL / eR - 1.0) < 1e-6
                     && fabs(got - exp) < 1e-4;
            if (!ok)
                bad++;
            printf("  corr=%+.9f  E(L)/E(R)=%.9f  |H(1k)|=%.9f (exp %.9f)  %s\n",
                   c, eL / eR, got, exp, ok ? "ok" : "FAIL");
        }
    }

    /* Every mask bit must gate its own channels.  The render is compared
     * bit-for-bit, so a change in the matrix weights cannot hide here. */
    printf("\nchannel-mask gating (bitwise render comparison):\n");
    {
        static g6ct_real src[8][N], src_noss[8][N], src_nobs[8][N];
        const g6ct_real *s[8], *s_noss[8], *s_nobs[8];
        uint32_t rng = 0x67365431u;
        int ok;

        for (i = 0; i < N; i++) {
            for (ch = 0; ch < 8; ch++) {
                int32_t v;
                rng = rng * 1664525u + 1013904223u;
                v = (int32_t)(rng >> 8) - 8388608;
                src[ch][i] = (g6ct_real)v * (g6ct_real)(1.0 / 8388608.0);
            }
        }
        memcpy(src_noss, src, sizeof src);
        memcpy(src_nobs, src, sizeof src);
        for (i = 0; i < N; i++) {
            src_noss[6][i] = src_noss[7][i] = 0;
            src_nobs[4][i] = src_nobs[5][i] = 0;
        }
        for (ch = 0; ch < 8; ch++) {
            s[ch] = src[ch];
            s_noss[ch] = src_noss[ch];
            s_nobs[ch] = src_nobs[ch];
        }

        ok = same_render(0, G6CT_FL, s, N);
        printf("  mask 0 == mask 0x1 (front path, filtered)            %s\n",
               ok ? "ok" : "FAIL");
        bad += !ok;

        /* 0x3 is the DLL's stereo bypass: raw FL/FR, no all-pass. */
        {
            static g6ct_real xl[N], xr[N];
            int j;

            render_mask(G6CT_FL | G6CT_FR, s, xl, xr, N);
            ok = 1;
            for (j = 0; j < N; j++)
                if (xl[j] != src[0][j] || xr[j] != src[1][j])
                    ok = 0;
            printf("  mask 0x3 bypasses the DSP (raw FL/FR)                %s\n",
                   ok ? "ok" : "FAIL");
            bad += !ok;
        }

        ok = same_render(G6CT_MASK_7_1, G6CT_MASK_7_1 & ~(G6CT_SL | G6CT_SR),
                         s_noss, N);
        printf("  clearing SL/SR with SL/SR silent is a no-op          %s\n",
               ok ? "ok" : "FAIL");
        bad += !ok;

        ok = !same_render(G6CT_MASK_7_1, G6CT_MASK_7_1 & ~(G6CT_SL | G6CT_SR),
                          s, N);
        printf("  clearing SL/SR with SL/SR active changes the render  %s\n",
               ok ? "ok" : "FAIL");
        bad += !ok;

        ok = !same_render(G6CT_MASK_7_1, G6CT_MASK_7_1 & ~G6CT_FC, s, N);
        printf("  clearing FC changes the render                       %s\n",
               ok ? "ok" : "FAIL");
        bad += !ok;

        ok = !same_render(G6CT_MASK_7_1, G6CT_MASK_7_1 & ~G6CT_LFE, s, N);
        printf("  clearing LFE changes the render                      %s\n",
               ok ? "ok" : "FAIL");
        bad += !ok;

        ok = !same_render(G6CT_MASK_7_1,
                          G6CT_MASK_7_1 & ~(G6CT_BL | G6CT_BR), s, N);
        printf("  clearing BL/BR changes the render                    %s\n",
               ok ? "ok" : "FAIL");
        bad += !ok;

        ok = !same_render(G6CT_MASK_7_1,
                          G6CT_MASK_7_1 & ~(G6CT_SL | G6CT_SR), s, N);
        printf("  clearing SL/SR changes the render                    %s\n",
               ok ? "ok" : "FAIL");
        bad += !ok;

        ok = same_render(G6CT_MASK_7_1,
                         G6CT_MASK_7_1 & ~(G6CT_BL | G6CT_BR), s_nobs, N);
        printf("  BL/BR silent with BL/BR cleared is a no-op           %s\n",
               ok ? "ok" : "FAIL");
        bad += !ok;
    }

    /* Deterministic render, hashed.  The generator is integer-only, so the
     * input bits do not depend on libm; the float32 hash is the DLL's hash
     * for the same file.  This is the regression test that does not need the
     * proprietary DLL. */
    printf("\ndeterministic render (%d frames, mask 0x%03X):\n", GN, G6CT_MASK_7_1);
    {
        static g6ct_real gl[GN], gr[GN];
        static g6ct_real block[8][1024];
        g6ct_state st;
        uint32_t rng = 0x67365431u;
        uint64_t h = 1469598103934665603ULL;
        size_t off;
        int c;

        g6ct_init(&st, G6CT_MASK_7_1);
        for (off = 0; off < GN; off += 1024) {
            static const int slot[8] = { 0, 1, 2, 3, 4, 5, 9, 10 };
            const g6ct_real *in[12] = { NULL };
            size_t n = (GN - off) < 1024 ? (GN - off) : 1024;
            size_t j;

            for (j = 0; j < n; j++) {
                for (c = 0; c < 8; c++) {
                    int32_t v;
                    rng = rng * 1664525u + 1013904223u;
                    v = (int32_t)(rng >> 8) - 8388608;
                    block[c][j] = (g6ct_real)v * (g6ct_real)(1.0 / 8388608.0);
                }
            }
            for (c = 0; c < 8; c++)
                in[slot[c]] = block[c];
            g6ct_process(&st, in, gl + off, gr + off, n);
        }

        for (off = 0; off < GN; off++) {
            float l = (float)gl[off], r = (float)gr[off];
            uint32_t bl, br;

            memcpy(&bl, &l, sizeof bl);
            memcpy(&br, &r, sizeof br);
            h = fnv_u32(h, bl);
            h = fnv_u32(h, br);
        }

        printf("  hash 0x%016llx  expected 0x%016llx  %s\n",
               (unsigned long long)h, (unsigned long long)GOLDEN_EXPECT,
               h == GOLDEN_EXPECT ? "ok" : "MISMATCH");
        if (h != GOLDEN_EXPECT)
            bad++;
    }

    printf("\n%s (%d failures)\n", bad ? "FAILED" : "PASSED", bad);
    return bad ? 1 : 0;
}
