LUCIO = lucio -r lucio.rules.yaml -O -v -R

.PHONY: \
	help \
	build \
	build-all \
	build-index \
	build-only \
	clean \
	rebuild

# "make build-only FILE.tmd [FILE.tmd ...]": the files named after the target
# are collected here, and turned into no-op goals so that make does not try
# to build them itself (their extension is ignored: FILE.md works too)
ifeq (build-only,$(firstword $(MAKECMDGOALS)))
BUILD_ONLY_FILES := $(addsuffix .tmd,$(basename $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))))
.PHONY: $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
$(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS)):
	@:
endif

help:
	@echo "Available targets:"
	@echo "  build              - Synonym of build-all"
	@echo "  build-all          - Build all *.md files"
	@echo "  build-only FILE... - Build only the given *.tmd files into the corresponding *.md files"
	@echo "  clean              - Remove all [0-9A-Z]*.md files"
	@echo "  rebuild            - Run targets: clean, build-all"

build: \
	build-all

build-all: \
	build-index

build-index:
	$(LUCIO) CONFIGURATION_FILE.tmd
	$(LUCIO) SETUP_VERIFY_INSTALLATION.tmd
	$(LUCIO) INDEX.tmd

build-only:
	@test -n "$(BUILD_ONLY_FILES)" || { echo "Usage: make build-only FILE.tmd [FILE.tmd ...]"; exit 1; }
	@for f in $(BUILD_ONLY_FILES); do $(LUCIO) $$f || exit 1; done

clean:
	rm [0-9A-Z]*.md

rebuild: \
	clean \
	build-all
