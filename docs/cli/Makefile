LUCIO = lucio -r lucio.rules.yaml -O -v -R

# every [0-9A-Z]*.tmd file, in this directory or in inc/, is built into the
# *.md file of the same name
SOURCES = $(wildcard [0-9A-Z]*.tmd) $(wildcard inc/[0-9A-Z]*.tmd)
TARGETS = $(SOURCES:.tmd=.md)

.PHONY: \
	help \
	build \
	build-all \
	build-only \
	clean \
	rebuild

# "make build-only FILE.tmd [FILE.tmd ...]": the files named after the target
# are collected here, and turned into no-op goals so that make does not try
# to build them itself
ifeq (build-only,$(firstword $(MAKECMDGOALS)))
BUILD_ONLY_FILES := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
.PHONY: $(BUILD_ONLY_FILES)
$(BUILD_ONLY_FILES):
	@:
endif

help:
	@echo "Available targets:"
	@echo "  build              - Synonym of build-all"
	@echo "  build-all          - Build the *.md files out of date w.r.t. their *.tmd file or the *.md files they include"
	@echo "  build-only FILE... - Build only the given *.tmd files into the corresponding *.md files"
	@echo "  clean              - Remove all [0-9A-Z]*.md and inc/[0-9A-Z]*.md files"
	@echo "  rebuild            - Run targets: clean, build-all"

build: \
	build-all

build-all: \
	$(TARGETS)

build-only:
	@test -n "$(BUILD_ONLY_FILES)" || { echo "Usage: make build-only FILE.tmd [FILE.tmd ...]"; exit 1; }
	@for f in $(BUILD_ONLY_FILES); do $(LUCIO) $$f || exit 1; done

clean:
	rm [0-9A-Z]*.md inc/[0-9A-Z]*.md

rebuild: \
	rebuild-all

rebuild-all: \
	clean \
	touch-all-tmd-files \
	build-all

rebuild-index-only:
	touch INDEX.tmd
	make build-only INDEX.tmd

touch-all-tmd-files:
	touch [0-9A-Z]*.tmd inc/[0-9A-Z]*.tmd

%.md: %.tmd
	$(LUCIO) $<

# a *.md file also depends on the *.md files of this directory or of inc/ that
# its *.tmd file includes (e.g., INDEX.md), read from the lucio include
# directives
include_deps = $(filter $(TARGETS),$(patsubst ./%,%,$(shell grep -o 'command=include path="\?\./[^" ]*\.md' $(1) | sed 's/.*path="\?//')))
$(foreach source,$(SOURCES),$(eval $(source:.tmd=.md): $(call include_deps,$(source))))
