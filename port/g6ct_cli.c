/*
 * g6ct_cli.c - render the port over raw interleaved float32.
 *
 *   g6ct_cli <in8.raw> <out2.raw> [mask]
 *
 * in:  8 channels interleaved float32 (FL FR FC LFE BL BR SL SR)
 * out: 2 channels interleaved float32
 *
 * Used by the verification script to produce the reference signal that the
 * PipeWire graph must reproduce.
 */
#include "g6ct.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define BLOCK 1024

int main(int argc, char **argv)
{
    FILE *fi, *fo;
    g6ct_state st;
    unsigned mask = G6CT_MASK_7_1;
    float *ibuf;
    static g6ct_real obuf[2 * BLOCK];
    size_t got;

    if (argc < 3) {
        fprintf(stderr, "usage: %s <in8.raw> <out2.raw> [mask]\n", argv[0]);
        return 2;
    }
    if (argc > 3)
        mask = (unsigned)strtoul(argv[3], NULL, 0);

    fi = fopen(argv[1], "rb");
    if (!fi) { perror(argv[1]); return 1; }
    fo = fopen(argv[2], "wb");
    if (!fo) { perror(argv[2]); fclose(fi); return 1; }

    ibuf = malloc(sizeof(float) * 8 * BLOCK);
    if (!ibuf) { fprintf(stderr, "oom\n"); return 1; }

    g6ct_init(&st, mask);

    while ((got = fread(ibuf, sizeof(float) * 8, BLOCK, fi)) > 0) {
        static const int slot[8] = { 0, 1, 2, 3, 4, 5, 9, 10 };
        static g6ct_real tmp[8][BLOCK];
        g6ct_real *in[12] = { NULL };
        size_t i;
        int c;

        for (i = 0; i < got; i++)
            for (c = 0; c < 8; c++)
                tmp[c][i] = (g6ct_real)ibuf[i * 8 + c];
        for (i = 0; i < 8; i++)
            in[slot[i]] = tmp[i];

        g6ct_process(&st, in, obuf, obuf + BLOCK, got);
        /* interleave */
        for (i = 0; i < got; i++) {
            float pair[2];

            pair[0] = (float)obuf[i];
            pair[1] = (float)obuf[BLOCK + i];
            fwrite(pair, sizeof(float), 2, fo);
        }
    }

    free(ibuf);
    fclose(fi);
    fclose(fo);
    return 0;
}
