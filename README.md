# volumito

Python client library and CLI tool for Volumio.


## Overview

`volumito` is a Python library and a command-line tool
that allows you to interact with your
[Volumio](https://volumio.com/)
player, programmatically or on a shell.


## Features

- Clean Python API to connect to and control a Volumio player
- Built-in comprehensive command-line tool with a lot of options
- Type-safe implementation with full type hints
- Comprehensive test coverage (100%)


## Requirements

- Python 3.13 or later
- A running Volumio player


## Installation

### From PyPI

Activate your virtual environment (`volumito_env`),
and install:

```bash
(volumito_env) $ pip install volumito
```

### From Source

Clone the repository and install from source
in a virtual environment:

```bash
$ git clone https://github.com/pettarin/volumito
$ cd volumito

$ # here Micromamba is used, choose your favorite
$ # package/virtual environment manager
$ micromamba env create -f environment.yml
$ micromamba activate volumito_dev

(volumito_dev) $ pip install -e .
(volumito_dev) $ # or
(volumito_dev) $ make install-e-this

(volumito_dev) $ # for developing volumito, use the dev configuration:
(volumito_dev) $ pip install -e .[dev]
(volumito_dev) $ # or
(volumito_dev) $ make install-e-this-dev
```

## Usage

### Basic Command

Query a Volumio instance at the default location (`volumio.local:3000`):

```bash
volumito info
```

### Connection Options

Specify custom connection parameters:

```bash
# Custom host
volumito info --host my-volumio.local
volumito info --host 192.168.1.100

# HTTPS connection
volumito info --scheme https

# Custom ports
volumito info --rest-api-port 8080 --mpd-port 7000

# Custom timeout (in seconds)
volumito info --timeout 10
```

### Output Formats

Choose from multiple output formats:

```bash
# Pretty JSON with 4-space indentation (default)
volumito info --format pretty

# Compact JSON with 2-space indentation
volumito info --format json

# Human-readable table
volumito info --format table

# Raw unformatted JSON
volumito info --raw
```

### Field Filtering

Control which fields are displayed:

```bash
# Show only key playback information (default)
volumito info --fields short

# Show all available fields
volumito info --fields all
```

Short fields include:
- position
- title
- artist
- album
- samplerate
- bitdepth
- channels
- service
- duration

### Verbosity Control

```bash
# Verbose mode - show connection details
volumito info --verbose

# Quiet mode - suppress error messages
volumito info --quiet
```

### Examples

Combine options for specific use cases:

```bash
# Table format with all fields
volumito info --format table --fields all

# Pipe to jq for advanced JSON processing
volumito info --raw | jq '.title, .artist'

# Save state to file
volumito info --format json > volumio_state.json

# Monitor playback every 5 seconds
while true; do
    clear
    volumito info --format table
    sleep 5
done
```

### Album Art

Get the current album art URL:

```bash
# Get URL only
volumito track albumart

# Download album art to file
volumito track albumart -o albumart.jpg

# With custom host and save path
volumito track albumart --host 192.168.1.100 -o /path/to/albumart.jpg
```

## Development

### Setup Development Environment

```bash
# Create micromamba environment
micromamba create -n volumito_dev python=3.13

# Activate environment
micromamba activate volumito_dev

# Install in development mode
pip install -e .
```

### Running Tests

```bash
# Run all checks (tests, linter, and type checker)
make test
# OR equivalently
make test-all

# Run unit tests only
make test-unit

# Run tests with coverage
make coverage

# Run linter
make lint

# Run type checker
make check-type-hints
```

### Project Structure

TODO

```
volumito/
├── src/
│   └── volumito/
│       ├── __init__.py
│       ├── api_client.py    # Volumio API client
│       └── cli.py           # Click-based CLI
├── tests/
│   ├── test_api_client.py
│   └── test_cli.py
├── examples/
│   └── README.md
├── pyproject.toml
├── Makefile
└── README.md
```

## API Reference

TODO


## License

This project is licensed under
the GNU General Public License v3.0 or later (GPLv3+).

See the [LICENSE](LICENSE) file for details.


## Authors

- Alberto Pettarin ([Web](https://www.albertopettarin.it))


### Contributing

Contributions are not currently being accepted,
as the Python API is not stable yet.


## Legal Disclaimers

Volumio and Volumio logo are a registered trademark of Volumio SRL,
a company registered in Italy (VAT ID: IT07009020483).

Please refer to the [Volumio Terms Of Service](https://volumio.com/terms-of-service/).

This project and its authors are not affiliated
nor endorsed by Volumio SRL.
