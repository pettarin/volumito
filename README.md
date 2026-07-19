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
volumito player state
```

`volumito info` is a synonym for `volumito player state`.

### Version

Print the `volumito` version:

```bash
volumito version

# Quoted version string, consumable by jq/yq (e.g. "0.0.8")
volumito --machine-readable version
```

### Connection Options

Specify custom connection parameters:

```bash
# Custom host
volumito player state --host my-volumio.local
volumito player state --host 192.168.1.100

# HTTPS connection
volumito player state --scheme https

# Custom ports
volumito player state --rest-api-port 8080 --mpd-port 7000

# Custom timeouts (in seconds)
volumito player state --rest-api-timeout 10
volumito track audio --mpd-timeout 3

# Pause before the resulting-state fetch (default 1.0 s; see Resulting State)
volumito --rest-api-sleep-before-next-call 0.5 player pause
```

The default MPD port is `6600`, as used by Volumio 4.
For Volumio 3 and earlier, which use MPD port `6599`,
pass `--mpd-port 6599`.

### Output Formats

Choose from multiple output formats:

```bash
# Pretty JSON with 4-space indentation (default)
volumito player state --format pretty

# Compact JSON with 2-space indentation
volumito player state --format json

# Human-readable table
volumito player state --format table

# Raw unformatted JSON
volumito player state --raw
```

### Field Filtering

Control which fields are displayed:

```bash
# Show only key playback information (default)
volumito player state --fields short

# Show all available fields
volumito player state --fields all
```

Short fields include:
- status
- position
- title
- artist
- album
- duration
- seek
- volume
- mute

### Verbosity Control

```bash
# Verbose mode
volumito player state --verbose

# Machine-readable mode (always supersedes the verbose option)
volumito player state --machine-readable
```

### Volume Control

Set, adjust, or show the playback volume:

```bash
# Print the current volume (no value)
volumito player volume

# Set an absolute level (integer between 0 and 100)
volumito player volume 75

# Step the volume one click up or down
volumito player volume plus     # also: increase, up
volumito player volume minus    # also: decrease, down

# Mute and unmute
volumito player volume mute
volumito player volume unmute

# `player mute` and `player unmute` are synonyms for the two commands above
volumito player mute
volumito player unmute
```

### Resulting State

By default, every `player` action subcommand (`toggle`, `play`, `pause`, `stop`, `next`, `previous`,
`volume`, `mute`, `unmute`) waits before fetching and printing the resulting `player state`. The pause
is 1 second by default; change it with the global `--rest-api-sleep-before-next-call` option. Disable
the whole behavior with `--no-print-resulting-state`:

```bash
# Pause, then show the resulting state (default)
volumito player pause

# Use a shorter pause before the resulting state
volumito --rest-api-sleep-before-next-call 0.5 player pause

# Pause without printing the resulting state
volumito player pause --no-print-resulting-state
```

### Examples

Combine options for specific use cases:

```bash
# Table format with all fields
volumito player state --format table --fields all

# Pipe to jq for advanced JSON processing
volumito player state --raw | jq '.title, .artist'

# Save state to file
volumito player state --format json > volumio_state.json

# Monitor playback every 5 seconds
while true; do
    clear
    volumito player state --format table
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

## API Reference

TODO


## Releases And Changelog

See the [CHANGELOG](CHANGELOG.md) file for the list of releases and their changes.


## Development

See [DEVELOPMENT.md](DEVELOPMENT.md) for how to set up a development environment,
run the tests, the project structure, and contributing.


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
