# g6ct - Creative MatrixEncoder (Sound BlasterX G6) 7.1 -> binaural downmixer
#
# The float32 build is bit-identical to KSUSBAPO64.dll (verified under Wine).
# The float64 build (G6CT_DOUBLE) keeps the exact same coefficients but runs
# the state and accumulation in double; it is a separate .so because the
# symbols have the same names with a different scalar type.

CC      ?= cc
CFLAGS  ?= -O2 -std=c11 -Wall -Wextra -ffp-contract=off
F64FLAGS = $(CFLAGS) -DG6CT_DOUBLE
LDLIBS   = -lm

all: test_ir test_ir64 g6ct_cli g6ct_cli64 \
     libg6ct_ladspa.so libg6ct_ladspa_f64.so

g6ct.c g6ct.h: ;

test_ir: g6ct.c test_ir.c g6ct.h
	$(CC) $(CFLAGS) -o $@ g6ct.c test_ir.c $(LDLIBS)

test_ir64: g6ct.c test_ir.c g6ct.h
	$(CC) $(F64FLAGS) -o $@ g6ct.c test_ir.c $(LDLIBS)

g6ct_cli: g6ct.c g6ct_cli.c g6ct.h
	$(CC) $(CFLAGS) -o $@ g6ct.c g6ct_cli.c $(LDLIBS)

g6ct_cli64: g6ct.c g6ct_cli.c g6ct.h
	$(CC) $(F64FLAGS) -o $@ g6ct.c g6ct_cli.c $(LDLIBS)

libg6ct_ladspa.so: g6ct.c g6ct_ladspa.c g6ct.h
	$(CC) $(CFLAGS) -fPIC -shared -o $@ g6ct_ladspa.c g6ct.c $(LDLIBS)

libg6ct_ladspa_f64.so: g6ct.c g6ct_ladspa.c g6ct.h
	$(CC) $(F64FLAGS) -fPIC -shared -o $@ g6ct_ladspa.c g6ct.c $(LDLIBS)

check: all
	./test_ir  > verification_unit_test.txt
	./test_ir64 > verification_unit_test_f64.txt
	@tail -1 verification_unit_test.txt verification_unit_test_f64.txt

clean:
	rm -f test_ir test_ir64 g6ct_cli g6ct_cli64 \
	      libg6ct_ladspa.so libg6ct_ladspa_f64.so

.PHONY: all check clean
