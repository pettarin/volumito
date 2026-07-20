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

# Quoted version string, consumable by jq/yq (e.g. "0.0.9")
volumito --machine-readable version
```

### Connection Options

Specify custom connection parameters:

```bash
# Custom host (-H is a shorthand for --host)
volumito player state --host my-volumio.local
volumito player state -H 192.168.1.100

# HTTPS connection
volumito player state --scheme https

# Custom ports (-P for --rest-api-port, -M for --mpd-port)
volumito player state --rest-api-port 8080 --mpd-port 7000
volumito player state -P 8080 -M 7000

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

# Human-readable table (-F is a shorthand for --format)
volumito player state --format table
volumito player state -F table

# Raw unformatted JSON (-R is a shorthand for --raw)
volumito player state --raw
volumito player state -R
```

### Field Filtering

Control which fields are displayed:

```bash
# Show only key playback information (default)
volumito player state --fields short

# Show all available fields (-L is a shorthand for --fields)
volumito player state --fields all
volumito player state -L all
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
- trackType
- samplerate
- bitdepth
- channels

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

### Playing A Queue Position

Start playback of a specific track in the queue (1-indexed):

```bash
# -p is a shorthand for --position
volumito player play --position 3
volumito player play -p 3
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

### Track Information

Show metadata for the currently playing track. This works like `player state`
(same `--fields`/`--format`/`--raw` options, and their `-L`/`-F`/`-R` shorthands),
but its default `short` field set is track-oriented:

```bash
# Track-oriented short fields (default)
volumito track info

# All available fields, as compact JSON
volumito track info -L all -F json

# Raw unfiltered JSON
volumito track info -R
```

Its short fields are:
- position
- title
- artist
- album
- duration
- trackType
- samplerate
- bitdepth
- channels

### Album Art

Get the current album art URI:

```bash
# Get URI only
volumito track albumart

# Download to an exact file path (-o)
volumito track albumart -o /path/to/cover.jpg

# Download into a directory, using the file name from the URI (-d)
volumito track albumart -d /path/to/covers/

# Machine-readable mode prints the URI as a quoted string, consumable by jq/yq
volumito -m track albumart          # => "http://volumio.local:3000/albumart?..."
volumito -m track audio             # => "http://volumio.local:8000/music/..."
```

The `-o`/`--output-file` and `-d`/`--output-dir` options are mutually exclusive.
`track audio` accepts the same two download options:

```bash
# Download the current track to an exact file path
volumito track audio -o /path/to/song.flac

# Download the current track into a directory (file name taken from the URI)
volumito track audio -d /path/to/music/
```

By default, a download will not overwrite an existing destination file (it errors
out instead). Pass `--overwrite-existing-files` to allow overwriting:

```bash
volumito track albumart -o /path/to/cover.jpg --overwrite-existing-files
volumito track audio -d /path/to/music/ --overwrite-existing-files
```

When downloading into a directory with `-d`, the file name is built from
`-f`/`--file-name-template` (Python `str.format` syntax, default
`{file_name_from_uri}`). Any space in the resulting name becomes an underscore:

```bash
# e.g. writes /path/to/music/001_La_rondine.flac
volumito track audio -d /path/to/music/ -f "{position:03d}_{title}.{extension}"
```

Supported template keys:
- `file_name_from_uri` — the file name taken from the URI (the default)
- `position` — 1-indexed track position (e.g. `{position:03d}` → `001`)
- `title`, `album`, `artist`, `trackType`, `bitdepth`, `samplerate` — strings
- `duration` — track length as `HH:MM:SS`
- `channels` — integer
- `extension` — currently always `flac`

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
