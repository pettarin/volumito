# Development

**IMPORTANT**: the examples in the documentation use `micromamba`
               to manage virtual environments; feel free to replace it
               with your favorite tool (`conda`, `uv`, etc.)

## Setup Development Environment

Clone this repository and install from source
in a virtual environment, with development extras:

```bash
$ git clone https://github.com/pettarin/volumito
$ cd volumito

$ micromamba create -n volumito_dev python=3.13
$ micromamba activate volumito_dev

(volumito_dev) $ pip install -e ".[dev]"
(volumito_dev) $ # or
(volumito_dev) $ make install-e-this-dev
```

You should be able to run:

```bash
(volumito_dev) $ volumito version
volumito, version 0.0.13
```


## Running Tests

```bash
# Run all checks (unit tests, linter, and type checker)
(volumito_dev) $ make test-all
# OR equivalently
(volumito_dev) $ make test

# Run unit tests only
(volumito_dev) $ make test-unit

# Run unit tests with coverage (HTML report in htmlcov/)
(volumito_dev) $ make coverage

# Run linter
(volumito_dev) $ make lint

# Run type checker
(volumito_dev) $ make check-type-hints
```


## Project Structure

```
volumito/
├── docs/
│   ├── CHANGELOG.md                    # releases and their changes
│   ├── CLI_USAGE.md                    # CLI tool documentation
│   ├── DEVELOPMENT.md                  # this file
│   └── LIBRARY_USAGE.md                # Python library documentation
├── res/
│   └── copyright_header.txt            # header prepended to every source file
├── src/
│   └── volumito/
│       ├── __init__.py                 # public API re-exports and version
│       ├── cli/
│       │   ├── configuration.py        # YAML configuration file loading
│       │   └── volumito.py             # Click-based CLI
│       └── clients/
│           ├── errors.py               # VolumioError and its subclasses
│           ├── host_configuration.py   # VolumioHostConfiguration helper data class
│           ├── mpd/client.py           # MPD client (track URI)
│           └── rest/client.py          # REST API client
├── tests/                              # unit tests
│   ├── test_cli.py
│   ├── test_configuration.py
│   ├── test_host_configuration.py
│   ├── test_mpd_client.py
│   └── test_rest_client.py
├── LICENSE                             # full text of the license for this project
├── Makefile                            # make commands for the developer
├── MANIFEST.in                         # include/exclude additional files in the PyPI package
├── pyproject.toml                      # descriptor for building the PyPI package
└── README.md                           # main README file
```


## Contributing

Contributions are not currently being accepted,
as the Python API is not stable yet.

TODO: populate this section immediately before publishing v1.0.0.

