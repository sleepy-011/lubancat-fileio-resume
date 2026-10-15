CC ?= cc
CPPFLAGS ?=
CFLAGS ?= -O2 -g
WARN = -std=c11 -Wall -Wextra -Wpedantic -Wconversion -Wshadow -Werror

.PHONY: all check clean sanitize dist
all: sparse-dl

sparse-dl: src/sparse_dl.c
	$(CC) $(CPPFLAGS) $(CFLAGS) $(WARN) $< $(LDFLAGS) -o $@

check: sparse-dl
	python3 tests/test_cli.py ./sparse-dl

sanitize:
	$(MAKE) clean
	SPARSE_SKIP_FAULT_TESTS=1 $(MAKE) CFLAGS='-O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer' LDFLAGS='-fsanitize=address,undefined' check

dist:
	python3 scripts/package.py

clean:
	rm -f sparse-dl
