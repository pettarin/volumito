# volumito

Python client library and CLI tool for Volumio.


## Overview

`volumito` is a Python library and a CLI tool
that allows querying and controlling a
[Volumio](https://volumio.com/)
host.


## Features

- Clean Python API to query and control a Volumio host
- Type-safe implementation with type hints
- Comprehensive test coverage (100%)
- An extensive and configurable CLI tool


## Requirements

- Python 3.13 or later
- A package/virtual environment manager tool
- A running Volumio host


## Installation

**IMPORTANT**: the examples in the documentation use `micromamba`
               to manage virtual environments; feel free to replace it
               with your favorite tool (`conda`, `uv`, etc.)

### From PyPI

Create a virtual environment (only the first time),
activate it, and install the latest release of `volumito`
available on PyPI with `pip`:

```bash
micromamba create -n volumito_env python=3.13
micromamba activate volumito_env

(volumito_env) pip install volumito
```

You should be able to run:

```bash
(volumito_env) volumito version
volumito, version 0.0.13
```

### From Source

Clone this repository and install from source
in a virtual environment:

```bash
git clone https://github.com/pettarin/volumito
cd volumito

micromamba create -n volumito_env python=3.13
micromamba activate volumito_env

(volumito_env) pip install -e .
(volumito_env) # or
(volumito_env) make install-e-this
```

You should be able to run:

```bash
(volumito_env) volumito version
volumito, version 0.0.13
```


## Usage

### CLI Usage

The document
[docs/CLI_USAGE.md](docs/CLI_USAGE.md)
describes all the commands, subcommands, and options
of the CLI tool `volumito`.

### Library Usage

The document
[docs/LIBRARY_USAGE.md](docs/LIBRARY_USAGE.md)
contains the API reference of the Python library `volumito`.


## Releases And Changelog

The list of releases and their changes is contained
in the
[docs/CHANGELOG](docs/CHANGELOG.md)
document.


## Development

Consult the
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)
document to learn how to set up a development environment,
run the tests, browse the project structure, and contribute.


## License

This project is licensed under
the GNU General Public License v3.0 or later (GPLv3+).

See the [LICENSE](LICENSE) file for details.


## Authors

- Alberto Pettarin ([Web](https://www.albertopettarin.it))


## Legal Disclaimers

Volumio and Volumio logo are a registered trademark of Volumio SRL,
a company registered in Italy (VAT ID: IT07009020483).

Please refer to the [Volumio Terms Of Service](https://volumio.com/terms-of-service/).

This project and its authors are not affiliated
nor endorsed by Volumio SRL.
