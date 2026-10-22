# g6ct - Creative MatrixEncoder (Sound BlasterX G6) 7.1 -> binaural downmixer
#
# The float32 build is bit-identical to KSUSBAPO64.dll (verified under Wine).
# The float64 build (G6CT_DOUBLE) keeps the exact same coefficients but runs
# the state and accumulation in double; it is a separate .so because the
# symbols have the same names with a different scalar type.

CC       ?= cc
CFLAGS   ?= -O2
# Numerical contract, not tuning knobs.  Kept separate from CFLAGS and placed
# after it so an exported CFLAGS=... cannot silently turn FMA contraction back
# on (the DLL replica would stop being bit-exact).
G6CT_CFLAGS = -std=c11 -Wall -Wextra -ffp-contract=off -fno-fast-math
ALL_CFLAGS  = $(CFLAGS) $(G6CT_CFLAGS)
F64FLAGS    = $(ALL_CFLAGS) -DG6CT_DOUBLE
LDLIBS      = -lm

all: test_ir test_ir64 test_ladspa test_ladspa64 g6ct_cli g6ct_cli64 \
     libg6ct_ladspa.so libg6ct_ladspa_f64.so

g6ct.c g6ct.h: ;

test_ir: g6ct.c test_ir.c g6ct.h
	$(CC) $(ALL_CFLAGS) -o $@ g6ct.c test_ir.c $(LDLIBS)

test_ir64: g6ct.c test_ir.c g6ct.h
	$(CC) $(F64FLAGS) -o $@ g6ct.c test_ir.c $(LDLIBS)

test_ladspa: g6ct.c g6ct_ladspa.c test_ladspa.c g6ct.h
	$(CC) $(ALL_CFLAGS) -o $@ g6ct.c g6ct_ladspa.c test_ladspa.c $(LDLIBS)

test_ladspa64: g6ct.c g6ct_ladspa.c test_ladspa.c g6ct.h
	$(CC) $(F64FLAGS) -o $@ g6ct.c g6ct_ladspa.c test_ladspa.c $(LDLIBS)

g6ct_cli: g6ct.c g6ct_cli.c g6ct.h
	$(CC) $(ALL_CFLAGS) -o $@ g6ct.c g6ct_cli.c $(LDLIBS)

g6ct_cli64: g6ct.c g6ct_cli.c g6ct.h
	$(CC) $(F64FLAGS) -o $@ g6ct.c g6ct_cli.c $(LDLIBS)

libg6ct_ladspa.so: g6ct.c g6ct_ladspa.c g6ct.h
	$(CC) $(ALL_CFLAGS) -fPIC -shared -o $@ g6ct_ladspa.c g6ct.c $(LDLIBS)

libg6ct_ladspa_f64.so: g6ct.c g6ct_ladspa.c g6ct.h
	$(CC) $(F64FLAGS) -fPIC -shared -o $@ g6ct_ladspa.c g6ct.c $(LDLIBS)

check: all
	./test_ir > verification_unit_test.txt
	./test_ir64 > verification_unit_test_f64.txt
	./test_ladspa > verification_ladspa_test.txt
	./test_ladspa64 > verification_ladspa_test_f64.txt
	@tail -n 1 verification_unit_test.txt verification_unit_test_f64.txt
	@tail -n 1 verification_ladspa_test.txt verification_ladspa_test_f64.txt

# The f64 plugin's chunk loop is the code the first ASan host found the
# overrun in; keep a target that rebuilds the host tests with the sanitizers.
asan:
	$(CC) $(ALL_CFLAGS) -g -O1 -fsanitize=address,undefined \
	    -fno-omit-frame-pointer -o test_ladspa_asan \
	    g6ct.c g6ct_ladspa.c test_ladspa.c $(LDLIBS)
	$(CC) $(F64FLAGS) -g -O1 -fsanitize=address,undefined \
	    -fno-omit-frame-pointer -o test_ladspa64_asan \
	    g6ct.c g6ct_ladspa.c test_ladspa.c $(LDLIBS)
	ASAN_OPTIONS=detect_leaks=1 UBSAN_OPTIONS=halt_on_error=1 ./test_ladspa_asan
	ASAN_OPTIONS=detect_leaks=1 UBSAN_OPTIONS=halt_on_error=1 ./test_ladspa64_asan

clean:
	rm -f test_ir test_ir64 test_ladspa test_ladspa64 \
	      test_ladspa_asan test_ladspa64_asan \
	      g6ct_cli g6ct_cli64 \
	      libg6ct_ladspa.so libg6ct_ladspa_f64.so

.PHONY: all check asan clean
