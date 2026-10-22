/*
 * harness.c - run the real Creative CMatrixEncoderEfxMod::Process under Wine.
 *
 * The APO container is not used.  The object is created with its own
 * constructor (RVA 0x678F0), a fake upstream object supplies the input
 * channels, and Process (RVA 0x67D80) is called directly.  That is the same
 * code path libpipewire-module-filter-chain drives on Linux.
 *
 *   harness.exe <KSUSBAPO64.dll> coef
 *   harness.exe <KSUSBAPO64.dll> ir <out-prefix>
 *   harness.exe <KSUSBAPO64.dll> run <in8.raw> <out2.raw> [mask] [chunk] [channels]
 *
 * "coef" dumps the eight all-pass coefficient blocks straight out of the
 * live object; "ir" renders the 8 x 2 impulse-response matrix; "run" feeds
 * an arbitrary interleaved file (channels = 8 or 12, default 8).  The
 * optional mask defaults to 0x63F and the optional chunk (a multiple of 128)
 * splits Process into repeated calls.
 *
 * Build: x86_64-w64-mingw32-gcc -O2 -o harness.exe harness.c
 */
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef unsigned int u32;

#define NFRAMES 4096
#define MAXCH   12
#define OBJ_SZ  1024

/* RVAs in KSUSBAPO64.dll (image base 0x180000000) */
#define RVA_CTOR        0x000678F0
#define RVA_SETMAXFRAMES 0x00069110
#define RVA_PROCESS     0x00067D80

static float *g_plane[MAXCH];
static void  *g_vt[64];
static void  *g_upstream[1];   /* fake upstream object: [0] = vtable */

/* Called as upstream->vtbl[8](upstream, frames, core).  The module expects
 * the upstream to publish the deinterleaved channel pointers and the valid
 * frame count in the core object. */
static long long fake_upstream(void *self, u32 frames, void *core)
{
    void **ch = (void **)((char *)core + 8);
    int i;

    (void)self;
    for (i = 0; i < MAXCH; i++)
        ch[i] = g_plane[i];
    *(u32 *)((char *)core + 4) = frames;
    return 0;
}

typedef struct {
    u32 rate, channels, mask, reserved, bits, type;
} FMT;

typedef struct {
    u32 frames;
    u32 written;
    float *ch[MAXCH];
} OUTDESC;

static void *new_object(char *base)
{
    void *obj = calloc(1, OBJ_SZ);
    void (*ctor)(void *) = (void (*)(void *))(base + RVA_CTOR);

    if (!obj)
        return NULL;
    ctor(obj);
    return obj;
}

int main(int argc, char **argv)
{
    HMODULE h;
    char *base;
    void *obj;
    FMT *ifmt, *ofmt;
    OUTDESC od;
    long hr;
    int ch, i;

    if (argc < 3) {
        fprintf(stderr, "usage: %s <dll> coef|ir [outprefix]\n", argv[0]);
        return 2;
    }

    CoInitializeEx(NULL, COINIT_MULTITHREADED);
    h = LoadLibraryA(argv[1]);
    if (!h) {
        printf("LoadLibrary failed: %lu\n", (unsigned long)GetLastError());
        return 1;
    }
    base = (char *)h;
    printf("module base %p\n", (void *)base);

    g_vt[8] = (void *)fake_upstream;
    g_upstream[0] = (void *)g_vt;

    /* ---------------- coefficient dump ---------------- */
    if (!strcmp(argv[2], "coef")) {
        obj = new_object(base);
        if (!obj) return 1;
        printf("ctor: +128=%u +92=%u +520=%u +524=%u core(+536)=%p\n",
               *(u32 *)((char *)obj + 128), *(u32 *)((char *)obj + 92),
               *(u32 *)((char *)obj + 520), *(u32 *)((char *)obj + 524),
               *(void **)((char *)obj + 536));
        for (i = 0; i < 8; i++) {
            unsigned *blk = (unsigned *)((char *)obj + 0xE8 + i * 36);
            printf("block %d @%03X:", i, 0xE8 + i * 36);
            for (ch = 0; ch < 9; ch++)
                printf(" %08X", blk[ch]);
            printf("\n");
        }
        return 0;
    }

    /* ---------------- arbitrary signal ---------------- */
    if (!strcmp(argv[2], "run")) {
        FILE *fi, *fo;
        long sz;
        unsigned nf, npad, chunk, k, mask = 0x63F, channels = 8;
        float *in, *ol, *orr;
        float *plane[MAXCH] = { NULL };
        void *scratch[MAXCH];

        if (argc < 5) { fprintf(stderr, "run needs <in8.raw> <out2.raw>\n"); return 2; }
        if (argc > 5)
            mask = (unsigned)strtoul(argv[5], NULL, 0);
        chunk = argc > 6 ? (unsigned)strtoul(argv[6], NULL, 0) : 0;
        if (argc > 7) {
            channels = (unsigned)strtoul(argv[7], NULL, 0);
            if (channels != 8 && channels != 12) {
                fprintf(stderr, "channels must be 8 or 12\n");
                return 2;
            }
        }

        fi = fopen(argv[3], "rb");
        if (!fi) { perror(argv[3]); return 1; }
        fseek(fi, 0, SEEK_END); sz = ftell(fi); rewind(fi);
        if (sz % (long)(channels * 4)) {
            fprintf(stderr, "input size is not a multiple of %u channels\n", channels);
            return 2;
        }
        nf = (unsigned)(sz / (channels * 4));
        npad = (nf + 127u) & ~127u;
        if (chunk == 0)
            chunk = npad;
        if (chunk % 128u || chunk > npad) {
            fprintf(stderr, "chunk must be a multiple of 128 and <= %u\n", npad);
            return 2;
        }
        in = calloc((size_t)npad * channels, sizeof(float));
        if (!in) return 1;
        if (fread(in, sizeof(float), (size_t)nf * channels, fi) != (size_t)nf * channels) return 1;
        fclose(fi);

        obj = new_object(base);
        *(void **)((char *)obj + 536) = calloc(1, 0x328);
        *(void **)((char *)obj + 8) = (void *)g_upstream;

        ifmt = (FMT *)((char *)obj + 32);
        ifmt->rate = 48000; ifmt->channels = channels; ifmt->mask = mask; ifmt->bits = 32;
        ofmt = (FMT *)((char *)obj + 56);
        ofmt->rate = 48000; ofmt->channels = 2; ofmt->mask = 0x3; ofmt->bits = 32;

        if (((long (*)(void *, unsigned))(base + RVA_SETMAXFRAMES))(obj, npad) != 0) return 1;
        {
            /* SetMaxFrames points the core's 12 channel slots at its scratch.
             * The fake upstream replaces them with the caller's planes during
             * Process; the next Process starts by clearing the scratch
             * through slot 0, so restore the scratch pointers first. */
            void *core = *(void **)((char *)obj + 536);

            for (k = 0; k < MAXCH; k++)
                scratch[k] = *(void **)((char *)core + 8 + 8 * k);
        }

        ol = calloc(npad, sizeof(float));
        orr = calloc(npad, sizeof(float));
        for (k = 0; k < MAXCH; k++) {
            plane[k] = calloc(npad, sizeof(float));
            if (!plane[k]) return 1;
            g_plane[k] = plane[k];
        }
        for (k = 0; k < npad; k++) {
            static const int slot8[8]  = { 0, 1, 2, 3, 4, 5, 9, 10 };
            static const int slot12[12] = { 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11 };
            unsigned c;

            for (c = 0; c < channels; c++)
                g_plane[channels == 8 ? slot8[c] : slot12[c]][k] = in[k*channels+c];
        }

        {
            unsigned off;

            for (off = 0; off < npad; off += chunk) {
                unsigned kk = npad - off < chunk ? npad - off : chunk;

                for (k = 0; k < MAXCH; k++)
                    g_plane[k] = plane[k] ? plane[k] + off : NULL;
                {
                    void *core = *(void **)((char *)obj + 536);

                    for (k = 0; k < MAXCH; k++)
                        *(void **)((char *)core + 8 + 8 * k) = scratch[k];
                }
                memset(&od, 0, sizeof od);
                od.frames = kk;
                od.ch[0] = ol + off;
                od.ch[1] = orr + off;
                hr = ((long (*)(void *, unsigned, OUTDESC *))(base + RVA_PROCESS))(obj, kk, &od);
                if (hr != 0 || od.written != kk) {
                    printf("Process -> 0x%lx at off %u: written=%u (expected %u)\n",
                           (unsigned long)hr, off, od.written, kk);
                    return 1;
                }
            }
        }
        printf("run: mask=0x%03X chunk=%u Process -> ok  frames=%u\n",
               mask, chunk, npad);

        fo = fopen(argv[4], "wb");
        if (!fo) { perror(argv[4]); return 1; }
        for (k = 0; k < npad; k++) {
            float pr[2];

            pr[0] = ol[k];
            pr[1] = orr[k];
            if (fwrite(pr, sizeof(float), 2, fo) != 2) {
                perror(argv[4]);
                return 1;
            }
        }
        if (fclose(fo) != 0) { perror(argv[4]); return 1; }
        free(in);
        for (k = 0; k < MAXCH; k++) free(plane[k]);
        free(ol);
        free(orr);
        return 0;
    }

    /* ---------------- impulse responses ---------------- */
    if (strcmp(argv[2], "ir") || argc < 4) {
        fprintf(stderr, "need out prefix\n");
        return 2;
    }

    for (ch = 0; ch < 8; ch++) {
        static const int slot[8] = { 0, 1, 2, 3, 4, 5, 9, 10 };
        char path[512];
        FILE *fp;
        float *outL, *outR;

        obj = new_object(base);
        if (!obj) return 1;

        /* The core is normally allocated by sub_180068EA0 (which needs a
         * property store at +24).  Allocate it here instead; SetMaxFrames
         * expects it to exist and memsets it. */
        *(void **)((char *)obj + 536) = calloc(1, 0x328);

        *(void **)((char *)obj + 8) = (void *)g_upstream;

        ifmt = (FMT *)((char *)obj + 32);
        ifmt->rate = 48000; ifmt->channels = 8; ifmt->mask = 0x63F;
        ifmt->reserved = 0; ifmt->bits = 32; ifmt->type = 0;

        ofmt = (FMT *)((char *)obj + 56);
        ofmt->rate = 48000; ofmt->channels = 2; ofmt->mask = 0x3;
        ofmt->reserved = 0; ofmt->bits = 32; ofmt->type = 0;

        hr = ((long (*)(void *, unsigned))(base + RVA_SETMAXFRAMES))(obj, NFRAMES);
        printf("ch %d: SetMaxFrames -> 0x%lx  core=%p\n", ch, (unsigned long)hr,
               *(void **)((char *)obj + 536));
        if (hr != 0) return 1;

        outL = calloc(NFRAMES, sizeof(float));
        outR = calloc(NFRAMES, sizeof(float));
        for (i = 0; i < MAXCH; i++) {
            g_plane[i] = calloc(NFRAMES, sizeof(float));
            if (!g_plane[i]) return 1;
        }
        g_plane[slot[ch]][0] = 1.0f;

        memset(&od, 0, sizeof od);
        od.frames = NFRAMES;
        od.ch[0] = outL;
        od.ch[1] = outR;

        hr = ((long (*)(void *, unsigned, OUTDESC *))(base + RVA_PROCESS))
                 (obj, NFRAMES, &od);
        printf("ch %d: Process -> 0x%lx  framesWritten=%u  L[0..3]=%g %g %g %g\n",
               ch, (unsigned long)hr, od.written,
               outL[0], outL[1], outL[2], outL[3]);
        if (hr != 0) return 1;

        sprintf(path, "%s_%d.raw", argv[3], ch);
        fp = fopen(path, "wb");
        if (!fp) { perror(path); return 1; }
        for (i = 0; i < NFRAMES; i++) {
            float pair[2];
            pair[0] = outL[i];
            pair[1] = outR[i];
            fwrite(pair, sizeof(float), 2, fp);
        }
        fclose(fp);

        for (i = 0; i < MAXCH; i++) { free(g_plane[i]); g_plane[i] = NULL; }
        free(outL);
        free(outR);
        free(obj);
    }
    printf("done\n");
    return 0;
}
