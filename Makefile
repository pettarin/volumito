.PHONY: \
	help \
	build \
	build-all \
	build-sdist \
	build-wheel \
	check-type-hints \
	clean \
	coverage \
	coverage-html \
	dist \
	install-e-this \
	install-e-this-all \
	install-e-this-async \
	install-e-this-dev \
	install-e-this-scp \
	lint \
	micromamba-create \
	micromamba-create-dev \
	micromamba-install-e-this \
	micromamba-install-e-this-dev \
	micromamba-reinstall-e-this \
	micromamba-reinstall-e-this-dev \
	micromamba-reinstall-e-this-dev-test \
	micromamba-remove \
	micromamba-remove-dev \
	reinstall-e-this \
	reinstall-e-this-all \
	reinstall-e-this-async \
	reinstall-e-this-dev \
	reinstall-e-this-dev-test \
	reinstall-e-this-scp \
	test \
	test-all \
	test-unit \
	uninstall-this \
	upload-production-pypi \
	upload-test-pypi

help:
	@echo "Available targets:"
	@echo "  build                      - Synonym of build-all"
	@echo "  build-all                  - Build all distribution packages"
	@echo "  build-sdist                - Build source distribution (sdist) tarball"
	@echo "  build-wheel                - Build wheel distribution"
	@echo "  check-type-hints           - Run mypy type checker"
	@echo "  clean                      - Remove build artifacts and cache files"
	@echo "  coverage                   - Run tests with coverage report (all formats)"
	@echo "  coverage-html              - Run tests with coverage report in HTML format"
	@echo "  dist                       - Create distribution packages (same as build)"
	@echo "  install-e-this             - Install package in editable mode"
	@echo "  install-e-this-all         - Install package in editable mode with all optional dependencies"
	@echo "  install-e-this-async       - Install package in editable mode with async dependencies"
	@echo "  install-e-this-dev         - Install package in editable mode with dev dependencies"
	@echo "  install-e-this-scp         - Install package in editable mode with scp dependencies"
	@echo "  lint                       - Run ruff linter"
	@echo "  reinstall-e-this           - Install package in editable mode"
	@echo "  reinstall-e-this-all       - Install package in editable mode with all optional dependencies"
	@echo "  reinstall-e-this-async     - Install package in editable mode with async dependencies"
	@echo "  reinstall-e-this-dev       - Install package in editable mode with dev dependencies"
	@echo "  reinstall-e-this-dev-test  - Install package in editable mode with dev dependencies and run all tests"
	@echo "  reinstall-e-this-scp       - Install package in editable mode with scp dependencies"
	@echo "  test                       - Synonym of test-all"
	@echo "  test-all                   - Run all checks (tests, linter, and type checker)"
	@echo "  test-unit                  - Run tests"
	@echo "  uninstall-this             - Uninstall the package"

install-e-this:
	pip install -e .

install-e-this-all:
	pip install -e .[all]

install-e-this-async:
	pip install -e .[async]

install-e-this-dev:
	pip install -e .[dev]

install-e-this-scp:
	pip install -e .[scp]

uninstall-this:
	pip uninstall volumito --yes

reinstall-e-this: \
	uninstall-this \
	install-e-this

reinstall-e-this-all: \
	uninstall-this \
	install-e-this-all

reinstall-e-this-async: \
	uninstall-this \
	install-e-this-async

reinstall-e-this-dev: \
	uninstall-this \
	install-e-this-dev

reinstall-e-this-dev-test: \
	reinstall-e-this-dev \
	test

reinstall-e-this-scp: \
	uninstall-this \
	install-e-this-scp

test: \
	test-all

test-all: \
	test-unit \
	lint \
	check-type-hints

test-unit:
	pytest

coverage: \
	coverage-html

coverage-html:
	pytest --cov-report=html

lint:
	ruff check src/ tests/

check-type-hints:
	mypy src/

clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info
	rm -rf src/*.egg-info
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf .ruff_cache/
	rm -rf htmlcov/
	rm -rf .coverage
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete

build: \
	build-all

build-all: \
	clean \
	build-sdist \
	build-wheel

build-sdist: \
	clean
	python -m build --sdist

build-wheel: \
	clean
	python -m build --wheel

dist: \
	build

# micromamba env specific
micromamba-create:
	micromamba create -n volumito_env python==3.13 --yes

micromamba-install-e-this:
	micromamba run -n volumito_env make install-e-this

micromamba-remove:
	micromamba env remove -n volumito_env --yes

micromamba-reinstall-e-this: \
	micromamba-remove\
	micromamba-create\
	micromamba-install-e-this

micromamba-create-dev:
	micromamba create -n volumito_dev python==3.13 --yes

micromamba-install-e-this-dev:
	micromamba run -n volumito_dev make install-e-this-dev

micromamba-remove-dev:
	micromamba env remove -n volumito_dev --yes

micromamba-reinstall-e-this-dev: \
	micromamba-remove-dev \
	micromamba-create-dev \
	micromamba-install-e-this-dev

micromamba-reinstall-e-this-dev-test: \
	micromamba-reinstall-e-this-dev \
	test

upload-production-pypi: \
	reinstall-e-this-dev-test \
	clean \
	build-sdist
	python3 -m twine upload --repository pypi dist/*

upload-test-pypi: \
	reinstall-e-this-dev-test \
	clean \
	build-sdist
	python3 -m twine upload --repository testpypi dist/*

