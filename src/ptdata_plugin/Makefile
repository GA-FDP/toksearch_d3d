SRC_LIBPTDATA_SQLITE_C := sqlite_index.c

INCLUDE_DIR := 

# Check if CONDA_PREFIX is set. If it is, use the conda include directory
# for the sqlite3 header file.
ifdef CONDA_PREFIX
INCLUDE_DIR := $(CONDA_PREFIX)/include $(INCLUDE_DIR)
endif

$(info CONDA_PREFIX: $(CONDA_PREFIX))

INCLUDE_FLAGS := $(addprefix -I, $(INCLUDE_DIR))
LDFLAGS := $(addprefix -L, $(LIBDIR))

CFLAGS = -std=gnu99 -fPIC $(INCLUDE_FLAGS) -g

.PHONY: all
all: libindex_plugin.so

.PHONY: clean
clean:
	rm -f *.o *.so get_index

libindex_plugin.so: $(SRC_LIBPTDATA_SQLITE_C:.c=.o)
	$(CC) -shared -o $@ $^ $(LDFLAGS) $(LDLIBS) -lsqlite3

