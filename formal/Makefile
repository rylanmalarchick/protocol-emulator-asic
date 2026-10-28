# Run every SymbiYosys job in this folder. Needs sby, yosys, and boolector
# (OSS CAD Suite). Every job runs on every call, and make exits nonzero if
# any job fails.
SBY_FILES := $(wildcard *.sby)
JOBS      := $(SBY_FILES:.sby=)

.PHONY: all clean $(JOBS)
all: $(JOBS)

$(JOBS):
	sby -f $@.sby

clean:
	rm -rf $(JOBS)
