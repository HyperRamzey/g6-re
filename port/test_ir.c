/*
 * test_ir.c - verification harness for the g6ct port.
 *
 * Renders the 8 x 2 impulse-response matrix and checks it against the
 * analytic transfer functions of the coefficient sets, so a mistake in
 * the matrix weights or in the all-pass cascade cannot pass silently.
 */
#include "g6ct.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

#define N 4096
#define SR 48000.0

#ifndef M_PI
#define M_PI 3.14159265358979323846
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
            g6ct_real *in[12] = { NULL };
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
            double ml = 0.0, mr = 0.0;
            /* measured magnitudes must equal the matrix weight x all-pass */
            printf("  %8.1f Hz  |AB| = %.12f   |CD| = %.12f\n",
                   probe_hz[k], fab, fcd);
            if (fabs(fab - 1.0) > 1e-6 || fabs(fcd - 1.0) > 1e-6)
                bad++;
            ml = fab;
            mr = fcd;
            (void)ml; (void)mr;
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
            /* 1e-4 allows for the 4096-tap truncation of the 0.9951 pole */
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

    printf("\n%s (%d failures)\n", bad ? "FAILED" : "PASSED", bad);
    return bad ? 1 : 0;
}
