.PHONY: \
	help \
	build \
	build-all \
	build-only-configuration-file \
	build-only-index \
	build-only-setup-verify-installation

help:
	@echo "Available targets:"
	@echo "  build              - Synonym of build-all"
	@echo "  build-all          - Build all *.md files"
	@echo "  build-only-*       - Build only the specified *.tmd file into the corresponding *.md file"

build: \
	build-all

build-all: \
	build-index

build-index: \
	build-only-configuration-file\
	build-only-setup-verify-installation \
	build-only-index

build-only-configuration-file:
	lucio -r lucio.rules.yaml -O -v -R CONFIGURATION_FILE.tmd

build-only-index:
	lucio -r lucio.rules.yaml -O -v -R INDEX.tmd

build-only-setup-verify-installation:
	lucio -r lucio.rules.yaml -O -v -R SETUP_VERIFY_INSTALLATION.tmd

build-docs: \
	build-all

